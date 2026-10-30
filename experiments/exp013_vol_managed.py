"""EXP-013: volatility-managed overlay (A) and beta-neutralised ranks with a
high-volatility short ban (B), on top of the EXP-009 long-short S.

Pre-registration: docs/experiments/EXP-013_PREREGISTRATION.md
  - Variant A: Moreira-Muir style inverse-variance scaling of the whole
    LS book, applied as an overlay on S's daily returns. Target vol 15%,
    trailing 60-trading-day realised vol, weight floored at 0.10 and capped
    at 1.0 (de-risking only), weight-change costs charged at the book's own
    one-way cost rate. Weights use only returns strictly before the day
    they apply to.
  - Variant B: composite score cross-sectionally residualised on trailing
    120-day beta vs TOPIX each day, and names in the top volatility decile
    (trailing 60-day) are banned from the short side only.
  - Sector neutralisation and inverse-vol sizing are out of scope (see the
    pre-registration: no sector data in the cache; sizing would change the
    engine core).

simulate2() below is EXP-009's simulate() generalised to separate long and
short score matrices. Self-check: with long_score == short_score == the S
composite it must reproduce EXP-009's simulate() exactly; the max abs diff
is printed in the diagnostics and the run is invalid if it is not 0.

Usage:
    python experiments/exp013_vol_managed.py <cache_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3  # noqa: E402
import exp009_long_short as E9  # noqa: E402

BUDGET = 2_000_000
PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
NT, PT, HOLD = E3.N_TRANCHES, E3.PER_TRANCHE, E3.HOLD_DAYS

TARGET_VOL = 0.15     # fixed ex ante, see pre-registration
VOL_WIN = 60          # realised-vol window (trading days) for A and B's ban
BETA_WIN = 120        # beta window (trading days) for B
BETA_MIN_OBS = 60
W_FLOOR = 0.10


# ----------------------------------------------------------------------------
# EXP-009 simulate() generalised to two score matrices (long / short)
# ----------------------------------------------------------------------------
def simulate2(long_score, short_score, o, c_ff, start, end, cost, carry,
              long_frac, short_frac):
    step = HOLD // NT
    longs = [dict() for _ in range(NT)]
    lcash = [BUDGET * long_frac / NT] * NT
    idle = BUDGET * (1 - long_frac)
    shorts = [dict() for _ in range(NT)]     # j -> (entry price net of cost, notional)
    realized = 0.0
    values = []

    def short_unreal(t):
        return sum(n * (1 - c_ff[t, j] / p) for s in shorts for j, (p, n) in s.items())

    def equity(t):
        return idle + sum(lcash) + sum(sh * c_ff[t, j] for h in longs for j, sh in h.items()) + realized + short_unreal(t)

    for t in range(start, end + 1):
        i = t - start
        due = range(NT) if i == 0 else ([(i % HOLD) // step] if i % step == 0 else [])
        sl = long_score[t - 1]
        ok_l = np.flatnonzero(np.isfinite(sl))
        order_l = ok_l[np.lexsort((ok_l, -sl[ok_l]))]
        ss = short_score[t - 1]
        ok_s = np.flatnonzero(np.isfinite(ss))
        order_s = ok_s[np.lexsort((ok_s, -ss[ok_s]))]
        eq_prev = equity(t - 1) if i > 0 else BUDGET
        for k in due:
            lcash[k] += sum(sh * (o[t, j] if o[t, j] > 0 else c_ff[t - 1, j]) * (1 - cost) for j, sh in longs[k].items())
            held = set().union(*(longs[m] for m in range(NT) if m != k))
            cand = [j for j in order_l if o[t, j] > 0 and j not in held][:PT]
            longs[k] = {}
            if cand:
                longs[k] = {j: lcash[k] / len(cand) / (o[t, j] * (1 + cost)) for j in cand}
                lcash[k] = 0.0
            if short_frac > 0:
                for j, (p, n) in shorts[k].items():
                    px = (o[t, j] if o[t, j] > 0 else c_ff[t - 1, j]) * (1 + cost)
                    realized += n * (1 - px / p)
                held_s = set().union(*(shorts[m] for m in range(NT) if m != k))
                cand_s = [j for j in order_s[::-1] if o[t, j] > 0 and j not in held_s][:PT]
                notional = eq_prev * short_frac / NT
                shorts[k] = {j: (o[t, j] * (1 - cost), notional / len(cand_s)) for j in cand_s} if cand_s else {}
        realized -= sum(n for sh in shorts for _, n in sh.values()) * carry / 245
        values.append(equity(t))
    last = end
    final = idle + sum(lcash) + sum(sh * c_ff[last, j] * (1 - cost) for h in longs for j, sh in h.items()) + realized \
        + sum(n * (1 - c_ff[last, j] * (1 + cost) / p) for s in shorts for j, (p, n) in s.items())
    values[-1] = final
    return np.array(values)


# ----------------------------------------------------------------------------
# variant A: volatility-managed overlay on S's full-period equity curve
# ----------------------------------------------------------------------------
def overlay_weights(returns: np.ndarray) -> np.ndarray:
    """W[t] = weight applied to day t's return, from the 60 returns strictly
    before t. 1.0 until 60 past returns exist."""
    n = len(returns)
    w = np.ones(n)
    for t in range(VOL_WIN, n):
        win = returns[t - VOL_WIN : t]
        if np.all(np.isfinite(win)):
            sigma = float(np.std(win, ddof=1) * np.sqrt(252))
            if sigma > 0:
                w[t] = min(1.0, max(W_FLOOR, (TARGET_VOL / sigma) ** 2))
    return w


def managed_equity(returns: np.ndarray, w: np.ndarray, cost: float,
                   ps: int, pe: int) -> np.ndarray:
    """Managed equity over full-curve indices [ps, pe], starting at BUDGET.
    Day-t: E = E_prev * (1 + W[t] * r[t]) - cost * |W[t] - W[t-1]| * E_prev.
    No weight-change cost on the period's first day."""
    out = np.empty(pe - ps + 1)
    e = float(BUDGET)
    prev_w = w[ps]
    for i, t in enumerate(range(ps, pe + 1)):
        e = e * (1.0 + w[t] * returns[t]) - cost * abs(w[t] - prev_w) * e
        prev_w = w[t]
        out[i] = e
    return out


# ----------------------------------------------------------------------------
# variant B inputs: trailing beta, trailing vol, neutralised scores
# ----------------------------------------------------------------------------
def trailing_beta_vol(panel_c: pd.DataFrame, topix_c: pd.Series):
    rets = panel_c.pct_change()
    m = topix_c.pct_change()
    # NOTE: DataFrame & Series would align the Series on columns; broadcast
    # the market-valid mask explicitly over rows instead.
    valid_np = rets.notna().to_numpy() & m.notna().to_numpy()[:, None]
    valid = pd.DataFrame(valid_np, index=rets.index, columns=rets.columns)
    xv = rets.where(valid)
    mv = pd.DataFrame(np.where(valid_np, m.to_numpy()[:, None], np.nan),
                      index=rets.index, columns=rets.columns)
    z = 0.0
    n = valid.rolling(BETA_WIN).sum()
    sx = xv.fillna(z).rolling(BETA_WIN).sum()
    sy = mv.fillna(z).rolling(BETA_WIN).sum()
    sxy = (xv * mv).fillna(z).rolling(BETA_WIN).sum()
    syy = (mv * mv).fillna(z).rolling(BETA_WIN).sum()
    cov = sxy - sx * sy / n
    var = syy - sy * sy / n
    beta = (cov / var).where((n >= BETA_MIN_OBS) & (var > 0))
    vol = rets.rolling(VOL_WIN).std()
    return beta, vol


def neutralised_scores(comp: pd.DataFrame, beta: pd.DataFrame,
                       vol: pd.DataFrame):
    """Return (long_score, short_score, diag): composite residualised on
    [1, beta] per day; short score additionally NaN for the top vol decile."""
    mask = comp.notna()
    b = beta.copy()
    med = b.median(axis=1)
    b = b.where(b.notna(), med, axis=0).where(mask)
    long_score = comp.copy()
    banned_share = []
    for d in comp.index:
        y = comp.loc[d]
        ok = y.notna() & b.loc[d].notna()
        if ok.sum() >= 30:
            X = np.column_stack([np.ones(int(ok.sum())), b.loc[d][ok].to_numpy()])
            coef, *_ = np.linalg.lstsq(X, y[ok].to_numpy(), rcond=None)
            resid = y.copy()
            resid[ok] = y[ok].to_numpy() - X @ coef
            long_score.loc[d] = resid
        else:  # too few betas: intercept-only (demeaned composite)
            long_score.loc[d] = y - y.mean()
    v = vol.where(mask)
    thr = v.quantile(0.9, axis=1)
    banned = v.ge(thr, axis=0) & v.notna()
    short_score = long_score.where(~banned)
    elig = mask.to_numpy()
    banned_share.append(float((banned.to_numpy() & elig).sum() / elig.sum()))
    diag = {"banned_share_of_eligible": float(np.mean(banned_share)),
            "beta_coverage_share": float(beta.where(mask).notna().to_numpy()[elig].mean())}
    return long_score, short_score, diag


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main(cache: Path) -> None:
    if not (cache / "topix.json").exists():
        raise SystemExit(f"cache not found: {cache} (expected topix.json inside)")
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    score = comp.to_numpy()
    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    f0 = int(dates.searchsorted(pd.Timestamp(PERIODS["full"][0])))
    f1 = int(dates.searchsorted(pd.Timestamp(PERIODS["full"][1]), side="right")) - 1

    # self-check: simulate2 with identical scores must equal EXP-009 simulate
    chk_a = E9.simulate(score, o, c, f0, f1, *COSTS["base"], 1.0, 0.5)
    chk_b = simulate2(score, score, o, c, f0, f1, *COSTS["base"], 1.0, 0.5)
    self_check = float(np.max(np.abs(chk_a - chk_b)))

    beta, vol = trailing_beta_vol(panel["C"], topix["C"])
    long_b, short_b, diag_b = neutralised_scores(comp, beta, vol)
    long_b_np, short_b_np = long_b.to_numpy(), short_b.to_numpy()

    res: dict = {}
    w_diag = {}
    for cname, (cost, carry) in COSTS.items():
        s_full = simulate2(score, score, o, c, f0, f1, cost, carry, 1.0, 0.5)
        rets = np.empty(len(s_full))
        rets[0] = s_full[0] / BUDGET - 1.0
        rets[1:] = s_full[1:] / s_full[:-1] - 1.0
        w = overlay_weights(rets)
        w_diag[cname] = {"mean_w": float(w.mean()),
                         "share_days_scaled": float((w < 1.0).mean())}
        for pname, (a, bb) in PERIODS.items():
            ps = int(dates.searchsorted(pd.Timestamp(a)))
            pe = int(dates.searchsorted(pd.Timestamp(bb), side="right")) - 1
            idx = dates[ps : pe + 1]
            # S and B are simulated fresh per period, exactly as EXP-010/012
            # do (slicing the full-period curve would misstate profit/DD).
            s_p = s_full if (ps, pe) == (f0, f1) else simulate2(
                score, score, o, c, ps, pe, cost, carry, 1.0, 0.5)
            b_p = simulate2(long_b_np, short_b_np, o, c, ps, pe, cost, carry, 1.0, 0.5)
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(s_p, index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                managed_equity(rets, w, cost, ps - f0, pe - f0), index=idx))
            res[f"{pname}_B_{cname}"] = E9.stats(pd.Series(b_p, index=idx))

    def verdict() -> dict:
        out = {}
        for v in ("A", "B"):
            g = lambda p, k: res[f"{p}_{v}_base"][k]  # noqa: E731
            s = lambda p, k: res[f"{p}_S_base"][k]  # noqa: E731
            c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
            c2 = all((g(p, "annual_over_dd") or -9) > (s(p, "annual_over_dd") or -9)
                     for p in ("first_half", "second_half"))
            gf, sf = res[f"full_{v}_stress"], res["full_S_stress"]
            c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > (sf["annual_over_dd"] or -9)
            out[v] = {
                "1_profit_positive_both_halves": bool(c1),
                "2_ratio_gt_S_both_halves": bool(c2),
                "3_full_stress_positive_and_ratio_gt_S": bool(c3),
                "promising": bool(c1 and c2 and c3),
            }
        return out

    diag = {"self_check_max_abs_diff": self_check, "weights": w_diag, **diag_b}
    print(json.dumps({"res": res, "verdict": verdict(), "diag": diag},
                     ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
