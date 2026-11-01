"""EXP-043: rebalance structure and timing luck (descriptive).

Preregistration: docs/experiments/EXP-043_PREREGISTRATION.md

For tranche counts NT in {1, 2, 4, 5, 10, 20} (20/NT names per
tranche, 20-day hold, stagger step 20/NT), A's book is simulated
under every phase offset of the rebalance grid (phase = shift of
the simulation anchor by r extra warmup days, r in 0..step-1,
with 20 warmup days before the measured period; the measured
segment is rebased to the budget). Reports, per period and
structure, the mean / SD / min / max across phases of profit,
annual/DD ratio and max DD. Base costs only. A sanity line
reproduces the canonical NT=10 phase-0 (no warmup) numbers.

Usage:
    python experiments/exp043_rtl.py <cache_dir> <nt>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3

NT = int(sys.argv[2])
E3.N_TRANCHES = NT
E3.PER_TRANCHE = 20 // NT
import exp009_long_short as E9
import exp010_earnings_momentum as E10

PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
}
COST, CARRY = 0.0003, 0.03
BUDGET = 2_000_000.0
HOLD = 20


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    o_np = panel["O"].to_numpy()
    c_np = panel["C"].ffill().to_numpy()
    comp = E3.signals(panel, fins, dates)["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid))
               / 2.0).where(valid)
    S = score_a.to_numpy()
    step = HOLD // NT
    out = {"nt": NT, "step": step, "periods": {}}
    for pname, (a, b) in PERIODS.items():
        p0 = int(dates.searchsorted(pd.Timestamp(a)))
        p1 = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        runs = []
        for r in range(step):
            s0 = p0 - HOLD - r
            curve = E9.simulate(S, o_np, c_np, s0, p1, COST, CARRY,
                                1.0, 0.5)
            seg = np.asarray(curve)[p0 - s0:]
            seg = seg * (BUDGET / seg[0])
            st = E9.stats(pd.Series(seg, index=dates[p0:p1 + 1]))
            runs.append(st)
        agg = {}
        for k in ("profit", "annual_over_dd", "max_dd_pct"):
            v = np.array([x[k] for x in runs], dtype=float)
            agg[k] = {"mean": float(v.mean()), "sd": float(v.std()),
                      "min": float(v.min()), "max": float(v.max())}
        out["periods"][pname] = {"n_phases": len(runs), "agg": agg}
    if NT == 10:
        chk = {}
        for pname, (a, b) in PERIODS.items():
            p0 = int(dates.searchsorted(pd.Timestamp(a)))
            p1 = int(dates.searchsorted(pd.Timestamp(b),
                                        side="right")) - 1
            st = E9.stats(pd.Series(
                E9.simulate(S, o_np, c_np, p0, p1, COST, CARRY, 1.0,
                            0.5), index=dates[p0:p1 + 1]))
            chk[pname] = st
        out["canonical_check"] = chk
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
