"""EXP-023: combine the EXP-015 guidance-revision sleeve and the EXP-018
SUE sleeve at 50/50 capital.

Preregistration: docs/experiments/EXP-023_PREREGISTRATION.md

Each sleeve runs independently on a 1,000,000 yen budget (100,000 yen x
max 10 positions) with the unchanged EXP-015 event engine; the combined
book is the sum of the two daily value series (starts at 2,000,000 yen).
Standalone sleeves at the full 2,000,000 yen budget are also re-run to
reproduce the published EXP-015 / EXP-018 figures. Judged against S
(recomputed on the same cache) by the standard three criteria.

Usage:
    python experiments/exp023_event_combo.py <cache_dir>
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
import exp015_guidance_sleeve as E15
import exp018_sue as E18

PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
FULL = 2_000_000
HALF = 1_000_000


def run_sleeve(mod, events, col_of, o, c_ff, dates, start, end, cost,
               budget):
    # each sleeve module carries its own engine copy and budget globals
    mod.BUDGET = float(budget)
    mod.NOTIONAL = budget // mod.MAX_POS
    vals, _dg = mod.simulate_events(events, col_of, o, c_ff, dates,
                                    start, end, cost)
    return np.asarray(vals, dtype=float)


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(panel["C"].columns)
    col_of = {c: j for j, c in enumerate(codes)}
    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    score_s = comp.to_numpy()

    ev_g = E15.detect_events(cache)
    ev_s = E18.detect_events(cache)

    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_s, o, c_ff, start, end, cost, carry,
                            1.0, 0.5), index=idx))
            for nm, mod, ev in (("guidance", E15, ev_g), ("sue", E18, ev_s)):
                series = run_sleeve(mod, ev, col_of, o, c_ff, dates, start,
                                    end, cost, FULL)
                res[f"{pname}_{nm}_{cname}"] = E9.stats(
                    pd.Series(series, index=idx))
            combo = (run_sleeve(E15, ev_g, col_of, o, c_ff, dates, start,
                                end, cost, HALF)
                     + run_sleeve(E18, ev_s, col_of, o, c_ff, dates, start,
                                  end, cost, HALF))
            res[f"{pname}_combo_{cname}"] = E9.stats(
                pd.Series(combo, index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_combo_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_S_both_halves": bool(all(
            ratio(f"{p}_combo_base") > ratio(f"{p}_S_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_S": bool(
            res["full_combo_stress"]["profit"] > 0
            and ratio("full_combo_stress") > ratio("full_S_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    diag = {"guidance_events": len(ev_g), "sue_events": len(ev_s)}
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
