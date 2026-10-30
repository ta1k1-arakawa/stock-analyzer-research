"""EXP-014: monthly long-short sleeve ranked on CAPM residual momentum.

Pre-registration: docs/experiments/EXP-014_PREREGISTRATION.md
  - For each stock, regress daily returns on TOPIX daily returns over the
    trailing 120 trading days ending at the signal date d (pairwise, >= 90
    observations), giving alpha, beta and in-window daily residuals.
  - Score = mean / std of the residuals over days [d-119, d-21] (the most
    recent ~1 month skipped; >= 60 residual days required) -- a t-stat of
    residual momentum, Blitz-Huij-Martens style on a shortened window (the
    cache starts 2016-10-31, so the literature's 36-month estimation is
    impossible; see the pre-registration).
  - The score computed at close of d is traded at the open of the next
    trading day (score matrix shifted by one row), monthly, via EXP-010's
    simulate_monthly: long top 20 / short bottom 20, equal weight,
    long 1.0 x BUDGET, short 0.5 x BUDGET.
  - Judged standalone against S with the EXP-009 three criteria.

Usage:
    python experiments/exp014_residual_momentum.py <cache_dir>
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
from exp010_earnings_momentum import simulate_monthly  # noqa: E402

BUDGET = 2_000_000
PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}

REG_WIN = 120         # market-model estimation window (trading days)
REG_MIN_OBS = 90
SKIP = 21             # most recent days excluded from the formation window
FORM_MIN_OBS = 60     # formation window is REG_WIN - SKIP = 99 days


def _roll_sums(xv, mv, valid, win):
    z = 0.0
    return {
        "n": valid.rolling(win).sum(),
        "sx": xv.fillna(z).rolling(win).sum(),
        "sy": mv.fillna(z).rolling(win).sum(),
        "sxy": (xv * mv).fillna(z).rolling(win).sum(),
        "srr": (xv * xv).fillna(z).rolling(win).sum(),
        "smm": (mv * mv).fillna(z).rolling(win).sum(),
    }


def residual_momentum_scores(panel_c: pd.DataFrame, topix_c: pd.Series) -> pd.DataFrame:
    """Score as of each date's close (rows = dates). NaN where undefined."""
    rets = panel_c.pct_change()
    m = topix_c.pct_change()
    valid_np = rets.notna().to_numpy() & m.notna().to_numpy()[:, None]
    valid = pd.DataFrame(valid_np, index=rets.index, columns=rets.columns)
    xv = rets.where(valid)
    mv = pd.DataFrame(np.where(valid_np, m.to_numpy()[:, None], np.nan),
                      index=rets.index, columns=rets.columns)

    reg = _roll_sums(xv, mv, valid, REG_WIN)
    n = reg["n"]
    mean_r = reg["sx"] / n
    mean_m = reg["sy"] / n
    var_m = reg["smm"] / n - mean_m ** 2
    cov = reg["sxy"] / n - mean_r * mean_m
    beta = (cov / var_m).where((n >= REG_MIN_OBS) & (var_m > 0))
    alpha = mean_r - beta * mean_m

    form = _roll_sums(xv, mv, valid, REG_WIN - SKIP)
    nf = form["n"].shift(SKIP)
    fr = (form["sx"] / form["n"]).shift(SKIP)
    fm = (form["sy"] / form["n"]).shift(SKIP)
    var_r = ((form["srr"] / form["n"]).shift(SKIP) - fr ** 2)
    var_mf = ((form["smm"] / form["n"]).shift(SKIP) - fm ** 2)
    cov_f = ((form["sxy"] / form["n"]).shift(SKIP) - fr * fm)

    mean_eps = fr - alpha - beta * fm
    var_eps = var_r + beta ** 2 * var_mf - 2.0 * beta * cov_f
    score = (mean_eps / np.sqrt(var_eps)).where(
        (nf >= FORM_MIN_OBS) & beta.notna() & (var_eps > 0))
    return score


def main(cache: Path) -> None:
    if not (cache / "topix.json").exists():
        raise SystemExit(f"cache not found: {cache} (expected topix.json inside)")
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    score_s = comp.to_numpy()
    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    sc = residual_momentum_scores(panel["C"], topix["C"])
    # traded at the next day's open: row t carries the score as of close t-1
    trade = sc.shift(1)
    trade_np = trade.to_numpy()

    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start : end + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_s, o, c, start, end, cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                simulate_monthly(trade_np, o, c, dates, a, b, cost, carry), index=idx))

    g = lambda p, k: res[f"{p}_A_base"][k]  # noqa: E731
    s = lambda p, k: res[f"{p}_S_base"][k]  # noqa: E731
    c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
    c2 = all((g(p, "annual_over_dd") or -9) > (s(p, "annual_over_dd") or -9)
             for p in ("first_half", "second_half"))
    gf, sf = res["full_A_stress"], res["full_S_stress"]
    c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > (sf["annual_over_dd"] or -9)
    verdict = {"A": {
        "1_profit_positive_both_halves": bool(c1),
        "2_ratio_gt_S_both_halves": bool(c2),
        "3_full_stress_positive_and_ratio_gt_S": bool(c3),
        "promising": bool(c1 and c2 and c3),
    }}

    # diagnostics: eligible names on the rows the engine actually trades on
    firsts = {}
    for t in range(len(dates)):
        key = (dates[t].year, dates[t].month)
        firsts.setdefault(key, t)
    elig = [int(np.isfinite(trade_np[t]).sum()) for t in firsts.values()]
    traded_months = [k for k, t in firsts.items() if np.isfinite(trade_np[t]).sum() >= 40]
    diag = {
        "months_total": len(elig),
        "months_with_full_book": len(traded_months),
        "first_full_book_month": f"{traded_months[0][0]}-{traded_months[0][1]:02d}" if traded_months else None,
        "mean_eligible_on_rebalance_rows": float(np.mean(elig)),
        "score_row_std_mean": float(sc.std(axis=1).mean()),
    }
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag}, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
