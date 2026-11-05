"""EXP-087C: A with short fraction 0.625 (dose point between the
tested 0.5 and 0.75). Standard 3 criteria vs A.
Usage: python experiments/exp087c_short625.py <cache_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import exp003_rotation as E3
import exp009_long_short as E9
import exp010_earnings_momentum as E10

PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid)) / 2.0).where(valid)
    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(comp.to_numpy(), o, c_ff, start, end, cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_a.to_numpy(), o, c_ff, start, end, cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A625_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_a.to_numpy(), o, c_ff, start, end, cost, carry, 1.0, 0.625), index=idx))
    g = lambda p, k: res[f"{p}_A625_base"][k]  # noqa: E731
    av = lambda p, k: res[f"{p}_A_base"][k]  # noqa: E731
    verdict = {
        "1_profit_positive_both_halves": bool(all(g(p, "profit") > 0 for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all((g(p, "annual_over_dd") or -9) > (av(p, "annual_over_dd") or -9) for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(res["full_A625_stress"]["profit"] > 0 and (res["full_A625_stress"]["annual_over_dd"] or -9) > (res["full_A_stress"]["annual_over_dd"] or -9)),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict}, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
