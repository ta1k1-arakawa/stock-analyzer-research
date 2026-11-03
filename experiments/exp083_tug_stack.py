"""EXP-083: EXP-037 tug-of-war tilt x short fraction 0.75 (round 10).

Preregistration: docs/experiments/EXP-037_PREREGISTRATION.md

A tug-of-war day has overnight return > 0 (open / prior close - 1)
and intraday return < 0 (close / open - 1). The leg is the share
of tug-of-war days in the trailing 20 trading days (at least 15
valid days required, else neutral 0.5), ranked within A's valid
set. Long score = (composite + revision momentum + tug rank) / 3;
short score = A unchanged (the source paper's effect is
long-leg only). Two-sided simulation via EXP-013's simulate2.
Judged against A by the standard three criteria.

Usage:
    python experiments/exp037_tug_of_war.py <cache_dir>
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
import exp013_vol_managed as E13

PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}


def tow_frame(panel) -> pd.DataFrame:
    o, c = panel["O"], panel["C"]
    overnight = o / c.shift(1) - 1.0
    intraday = c / o - 1.0
    tug = ((overnight > 0) & (intraday < 0)).where(
        overnight.notna() & intraday.notna())
    return tug.rolling(20, min_periods=15).mean()


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)
    tow = tow_frame(panel)

    valid = comp.notna()
    win = (dates >= pd.Timestamp("2017-01-04")) \
        & (dates <= pd.Timestamp("2026-09-25"))
    diag = {"tow_coverage_median": float(
        (tow.notna() & valid).sum(axis=1)[win].div(
            valid.sum(axis=1)[win]).median()),
        "tow_share_median": float(tow[win].median().median())}

    comp_r = comp.rank(axis=1, pct=True)
    tow_r = tow.where(valid).rank(axis=1, pct=True) \
        .where(tow.notna(), 0.5)
    score_a = ((comp_r + mom.where(valid)) / 2.0).where(valid)
    long_t = ((comp_r + mom.where(valid) + tow_r) / 3.0).where(valid)

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
            res[f"{pname}_A_tow_{cname}"] = E9.stats(pd.Series(
                E13.simulate2(long_t.to_numpy(), score_a.to_numpy(),
                              o, c_ff, start, end, cost, carry,
                              1.0, 0.75), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_tow_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_tow_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_tow_stress"]["profit"] > 0
            and ratio("full_A_tow_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
