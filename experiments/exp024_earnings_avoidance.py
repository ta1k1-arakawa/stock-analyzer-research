"""EXP-024: avoid holding longs over earnings announcements.

Preregistration: docs/experiments/EXP-024_PREREGISTRATION.md

For each stock and each disclosure date D in the cached financial
summary, let iD be the first trading day after D (the first session that
prices the announcement). The stock's LONG score is masked to NaN on
[iD-2, iD]. The short side keeps A's score unchanged; positions are run
through EXP-013's two-sided engine. Judged against A (recomputed;
S also reported) by the standard three criteria.

Usage:
    python experiments/exp024_earnings_avoidance.py <cache_dir>
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


def build_mask(fins, dates, codes) -> np.ndarray:
    """True where (day, code) falls in [iD-2, iD] for a disclosure."""
    T, N = len(dates), len(codes)
    col_of = {c: j for j, c in enumerate(codes)}
    mask = np.zeros((T, N), dtype=bool)
    for code, recs in fins.items():
        j = col_of.get(code)
        if j is None:
            continue
        seen = set()
        for r in recs:
            d = r.get("DiscDate")
            if not d or d in seen:
                continue
            seen.add(d)
            iD = int(dates.searchsorted(pd.Timestamp(d), side="right"))
            for t in (iD - 2, iD - 1, iD):
                if 0 <= t < T:
                    mask[t, j] = True
    return mask


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)

    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid)) / 2.0) \
        .where(valid)
    mask = build_mask(fins, dates, codes)
    long_avoid = score_a.mask(pd.DataFrame(mask, index=dates, columns=codes))

    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    mats = {"S": comp.to_numpy(), "A": score_a.to_numpy(),
            "A_avoid": long_avoid.to_numpy()}
    short_a = score_a.to_numpy()

    res: dict = {}
    diag: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        v = valid.to_numpy()[start:end + 1]
        m = mask[start:end + 1]
        diag[pname] = {"masked_share_of_valid_cells":
                       float((m & v).sum() / max(v.sum(), 1))}
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(mats["S"], o, c_ff, start, end, cost, carry,
                            1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(mats["A"], o, c_ff, start, end, cost, carry,
                            1.0, 0.5), index=idx))
            res[f"{pname}_A_avoid_{cname}"] = E9.stats(pd.Series(
                E13.simulate2(mats["A_avoid"], short_a, o, c_ff, start, end,
                              cost, carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_avoid_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_avoid_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_avoid_stress"]["profit"] > 0
            and ratio("full_A_avoid_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
