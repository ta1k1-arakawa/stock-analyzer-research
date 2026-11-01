"""EXP-032: liquidity-shock underreaction tilt.

Preregistration: docs/experiments/EXP-032_PREREGISTRATION.md

ILLIQ(d) = |daily return| / trading value (days with value > 0).
shock(d) = ln(mean ILLIQ over [d-249, d-20]) - ln(mean ILLIQ over
[d-19, d]); positive means recent illiquidity is below the stock's
own prior norm (liquidity improved). Windows require >= 150 / >= 15
valid days. A_liq = (composite rank + revision-momentum rank +
shock rank) / 3 on A's valid set; missing shock ranked neutral 0.5.
Judged against A (recomputed; S also reported) by the standard
three criteria.

Usage:
    python experiments/exp032_liquidity_shock.py <cache_dir>
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


def shock_frame(panel) -> pd.DataFrame:
    ret = panel["C"].pct_change()
    va = panel["Va"]
    illiq = ret.abs().div(va.where(va > 0))
    short = illiq.rolling(20, min_periods=15).mean()
    long = illiq.shift(20).rolling(230, min_periods=150).mean()
    shock = np.log(long.where(long > 0)) - np.log(short.where(short > 0))
    return shock


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)

    shock = shock_frame(panel)
    valid = comp.notna()
    win = (dates >= pd.Timestamp("2017-01-04")) \
        & (dates <= pd.Timestamp("2026-09-25"))
    diag = {"shock_coverage_median": float(
        (shock.notna() & valid).sum(axis=1)[win].div(
            valid.sum(axis=1)[win]).median())}

    comp_r = comp.rank(axis=1, pct=True)
    shock_r = shock.where(valid).rank(axis=1, pct=True) \
        .where(shock.notna(), 0.5)
    score_a = ((comp_r + mom.where(valid)) / 2.0).where(valid)
    score_l = ((comp_r + mom.where(valid) + shock_r) / 3.0).where(valid)

    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
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
                E9.simulate(score_a.to_numpy(), o, c_ff, start, end,
                            cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_liq_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_l.to_numpy(), o, c_ff, start, end,
                            cost, carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_liq_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_liq_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_liq_stress"]["profit"] > 0
            and ratio("full_A_liq_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
