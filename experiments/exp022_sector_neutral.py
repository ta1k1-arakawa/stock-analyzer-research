"""EXP-022: sector-neutral A (within-S17 ranks for both legs).

Preregistration: docs/experiments/EXP-022_PREREGISTRATION.md

A's two legs (composite = B/P rank + forecast-ROE rank sum, and the
revision-momentum rank) are re-ranked WITHIN each TOPIX-17 sector
(experiments/exp022_sectors.json, fixed assignment) instead of globally:
    A_neutral = (within_sector_rank(composite) + within_sector_rank(mom)) / 2
on exactly A's valid set. Everything else (top/bottom 20, 1.0/0.5,
costs, periods) is unchanged from EXP-009/010. Judged against A by the
standard three criteria. S and A are recomputed on the same cache and
must reproduce the published figures.

Usage:
    python experiments/exp022_sector_neutral.py <cache_dir>
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
HERE = Path(__file__).resolve().parent


def within_sector_rank(df: pd.DataFrame, sector_of: dict) -> pd.DataFrame:
    """Percentile rank of each row computed within each sector group."""
    out = pd.DataFrame(np.nan, index=df.index, columns=df.columns)
    groups: dict[str, list[str]] = {}
    for c in df.columns:
        groups.setdefault(sector_of[c], []).append(c)
    for cols in groups.values():
        out[cols] = df[cols].rank(axis=1, pct=True)
    return out


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)
    sector_of = json.loads((HERE / "exp022_sectors.json").read_text())
    assert all(c in sector_of for c in codes), "sector map incomplete"

    mask = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    mom_r = mom.where(mask)
    score_a = ((comp_r + mom_r) / 2.0).where(mask)

    comp_w = within_sector_rank(comp, sector_of).where(mask)
    mom_w = within_sector_rank(mom, sector_of).where(mask)
    score_n = ((comp_w + mom_w) / 2.0).where(mask)

    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    mats = {"S": comp.to_numpy(), "A": score_a.to_numpy(),
            "A_neutral": score_n.to_numpy()}

    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            for nm, mat in mats.items():
                res[f"{pname}_{nm}_{cname}"] = E9.stats(pd.Series(
                    E9.simulate(mat, o, c_ff, start, end, cost, carry,
                                1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_neutral_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_neutral_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_neutral_stress"]["profit"] > 0
            and ratio("full_A_neutral_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
