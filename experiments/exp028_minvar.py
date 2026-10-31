"""EXP-028: minimum-variance construction of A's book.

Preregistration: docs/experiments/EXP-028_PREREGISTRATION.md

Selection is A's, unchanged. At each tranche rebalance, the selected
names on each side are weighted by a shrunk-covariance minimum-variance
rule (trailing 120 trading days of close-to-close returns, covariance
shrunk 50% to its diagonal, weights clipped to [0.02, 0.10] with two
clip-renormalise rounds; equal weights on any failure). simulate_w is
EXP-013's simulate2 with only the purchase sizing generalised; a gate
check verifies that forcing equal weights reproduces A exactly before
any A_mv number is trusted. Judged against A (recomputed; S also
reported) by the standard three criteria.

Usage:
    python experiments/exp028_minvar.py <cache_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3
import exp009_long_short as E9
import exp010_earnings_momentum as E10

PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
BUDGET = 2_000_000
NT, PT, HOLD = E3.N_TRANCHES, E3.PER_TRANCHE, E3.HOLD_DAYS
COV_WIN, MIN_OBS = 120, 60
W_LO, W_HI = 0.02, 0.10


def simulate_w(long_score, short_score, o, c_ff, start, end, cost, carry,
               long_frac, short_frac, weights_fn):
    """EXP-013 simulate2 with weighted purchase sizing.

    weights_fn(candidates, t, basket) -> dict j -> weight (sums to 1),
    or None for equal weights. basket is the side's whole book for the
    weight calculation (Amendment 1): other tranches' holdings plus this
    tranche's candidates, topped up by score order to NT*PT names.
    """
    step = HOLD // NT
    longs = [dict() for _ in range(NT)]
    lcash = [BUDGET * long_frac / NT] * NT
    idle = BUDGET * (1 - long_frac)
    shorts = [dict() for _ in range(NT)]
    realized = 0.0
    values = []

    def short_unreal(t):
        return sum(n * (1 - c_ff[t, j] / p)
                   for s in shorts for j, (p, n) in s.items())

    def equity(t):
        return idle + sum(lcash) + sum(
            sh * c_ff[t, j] for h in longs for j, sh in h.items()) \
            + realized + short_unreal(t)

    for t in range(start, end + 1):
        i = t - start
        due = range(NT) if i == 0 else (
            [(i % HOLD) // step] if i % step == 0 else [])
        sl = long_score[t - 1]
        ok_l = np.flatnonzero(np.isfinite(sl))
        order_l = ok_l[np.lexsort((ok_l, -sl[ok_l]))]
        ss = short_score[t - 1]
        ok_s = np.flatnonzero(np.isfinite(ss))
        order_s = ok_s[np.lexsort((ok_s, -ss[ok_s]))]
        eq_prev = equity(t - 1) if i > 0 else BUDGET
        for k in due:
            lcash[k] += sum(
                sh * (o[t, j] if o[t, j] > 0 else c_ff[t - 1, j])
                * (1 - cost) for j, sh in longs[k].items())
            held = set().union(*(longs[m] for m in range(NT) if m != k))
            cand = [j for j in order_l
                    if o[t, j] > 0 and j not in held][:PT]
            longs[k] = {}
            if cand:
                basket = list(held) + cand
                if len(basket) < NT * PT:
                    for j in order_l:
                        if o[t, j] > 0 and j not in basket:
                            basket.append(j)
                        if len(basket) >= NT * PT:
                            break
                w = weights_fn(cand, t, basket) or {j: 1.0 / len(cand)
                                                    for j in cand}
                longs[k] = {j: lcash[k] * w[j] / (o[t, j] * (1 + cost))
                            for j in cand}
                lcash[k] = 0.0
            if short_frac > 0:
                for j, (p, n) in shorts[k].items():
                    px = (o[t, j] if o[t, j] > 0 else c_ff[t - 1, j]) \
                        * (1 + cost)
                    realized += n * (1 - px / p)
                held_s = set().union(*(shorts[m] for m in range(NT)
                                       if m != k))
                cand_s = [j for j in order_s[::-1]
                          if o[t, j] > 0 and j not in held_s][:PT]
                notional = eq_prev * short_frac / NT
                if cand_s:
                    basket_s = list(held_s) + cand_s
                    if len(basket_s) < NT * PT:
                        for j in order_s[::-1]:
                            if o[t, j] > 0 and j not in basket_s:
                                basket_s.append(j)
                            if len(basket_s) >= NT * PT:
                                break
                    w = weights_fn(cand_s, t, basket_s) or {
                        j: 1.0 / len(cand_s) for j in cand_s}
                    shorts[k] = {j: (o[t, j] * (1 - cost),
                                     notional * w[j]) for j in cand_s}
                else:
                    shorts[k] = {}
        realized -= sum(n for sh in shorts for _, n in sh.values()) \
            * carry / 245
        values.append(equity(t))
    last = end
    final = idle + sum(lcash) + sum(
        sh * c_ff[last, j] * (1 - cost)
        for h in longs for j, sh in h.items()) + realized + sum(
            n * (1 - c_ff[last, j] * (1 + cost) / p)
            for s in shorts for j, (p, n) in s.items())
    values[-1] = final
    return np.array(values)


def make_minvar_fn(rets: np.ndarray):
    """Basket-level min-variance weights (preregistration rule), then
    the tranche's candidates keep their relative basket weights
    (Amendment 1)."""
    def fn(cand, t, basket):
        if t - COV_WIN < 0 or len(basket) < 2:
            return None
        win = rets[t - COV_WIN:t][:, basket]
        rows = win[np.all(np.isfinite(win), axis=1)]
        if len(rows) < MIN_OBS:
            return None
        cov = np.cov(rows, rowvar=False)
        cov = 0.5 * cov + 0.5 * np.diag(np.diag(cov))
        try:
            x = np.linalg.solve(cov, np.ones(len(basket)))
        except np.linalg.LinAlgError:
            return None
        if not np.all(np.isfinite(x)) or x.sum() <= 0:
            return None
        w = x / x.sum()
        for _ in range(2):
            w = np.clip(w, W_LO, W_HI)
            w = w / w.sum()
        bw = {j: float(w[i]) for i, j in enumerate(basket)}
        sub = {j: bw[j] for j in cand}
        tot = sum(sub.values())
        if tot <= 0:
            return None
        return {j: v / tot for j, v in sub.items()}
    return fn


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)

    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid)) / 2.0) \
        .where(valid)
    a_np = score_a.to_numpy()

    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    rets = panel["C"].pct_change().to_numpy()
    mv_fn = make_minvar_fn(rets)
    eq_fn = lambda cand, t, basket: None  # noqa: E731

    # --- gate: equal weights through simulate_w must reproduce A ---
    fs = int(dates.searchsorted(pd.Timestamp("2017-01-04")))
    fe = int(dates.searchsorted(pd.Timestamp("2026-09-25"),
                                 side="right")) - 1
    ref = E9.simulate(a_np, o, c_ff, fs, fe, 0.0003, 0.03, 1.0, 0.5)
    chk = simulate_w(a_np, a_np, o, c_ff, fs, fe, 0.0003, 0.03, 1.0, 0.5,
                     eq_fn)
    gate = float(np.max(np.abs(ref - chk)))
    if gate > 1e-6 * BUDGET:
        raise SystemExit(f"GATE FAILED: simulate_w(equal) != A "
                         f"(max diff {gate})")

    fallbacks = {"n": 0}
    def counting_mv(cand, t, basket):
        w = mv_fn(cand, t, basket)
        if w is None:
            fallbacks["n"] += 1
        return w

    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(comp.to_numpy(), o, c_ff, start, end, cost,
                            carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(a_np, o, c_ff, start, end, cost, carry,
                            1.0, 0.5), index=idx))
            res[f"{pname}_A_mv_{cname}"] = E9.stats(pd.Series(
                simulate_w(a_np, a_np, o, c_ff, start, end, cost, carry,
                           1.0, 0.5, counting_mv), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_mv_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_mv_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_mv_stress"]["profit"] > 0
            and ratio("full_A_mv_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict,
                      "diag": {"gate_max_diff": gate,
                               "equal_weight_fallbacks": fallbacks["n"]}},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
