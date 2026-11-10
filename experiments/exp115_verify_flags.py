"""EXP-115: equivalence check of the forward engine's
guidance_flags() (exp004_forward, live file) against EXP-114's
own flag matrix (flag_matrix_registered on the EXP-002 cache).

Comparisons (all must be exact, 0 mismatches):
- every 10th trading day of 2017-01-04..2026-09-25;
- every trading day of calendar 2019 and 2024 (full submatrix);
- boundary days (eff-1, eff, eff+59, eff+60) around 40 sampled
  flag events.

Usage: python exp115_verify_flags.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HOME = Path.home()
sys.path.insert(0, str(HOME / "workspace" / "exp114_run"))
sys.path.insert(0, str(HOME / "workspace" / "forward_live" / "experiments"))
import exp003_rotation as E3  # noqa: E402
import exp114_joint as E114  # noqa: E402
import exp004_forward as F4  # noqa: E402

CACHE = HOME / "workspace" / "cache" / "jquants_exp002"


def main() -> None:
    topix, panel, fins = E3.load(CACHE)
    dates = topix.index
    codes = list(panel["C"].columns)
    fy = E114.build_fy_frame(fins)
    flagged, _ = E114.flag_matrix_registered(dates, codes, fy)
    print(f"matrix flagged name-days (full calendar): {int(flagged.sum())}")

    lo = int(dates.searchsorted(pd.Timestamp("2017-01-04")))
    hi = int(dates.searchsorted(pd.Timestamp("2026-09-25"), side="right")) - 1
    sample = set(range(lo, hi + 1, 10))
    for yr in ("2019", "2024"):
        a = int(dates.searchsorted(pd.Timestamp(f"{yr}-01-01")))
        b = int(dates.searchsorted(pd.Timestamp(f"{yr}-12-31"),
                                   side="right")) - 1
        sample.update(range(a, b + 1))
    fl = fy[fy["flag"]].head(400)
    rng = np.random.default_rng(115)
    for disc in fl["disc"].iloc[rng.choice(len(fl), size=40,
                                           replace=False)]:
        eff = int(dates.searchsorted(pd.Timestamp(disc), side="right"))
        for t in (eff - 1, eff, eff + 59, eff + 60):
            if lo <= t <= hi:
                sample.add(t)
    sample = sorted(sample)
    print(f"sampled days: {len(sample)}")

    mism = 0
    for t in sample:
        day = dates[t]
        want = {codes[j] for j in np.flatnonzero(flagged[t])}
        got = F4.guidance_flags(day, dates)
        if want != got:
            mism += 1
            if mism <= 5:
                print(f"MISMATCH {day.date()}: only-matrix "
                      f"{sorted(want - got)}, only-forward "
                      f"{sorted(got - want)}")
    print(f"mismatched days: {mism} / {len(sample)}")
    assert mism == 0
    print("EQUIVALENCE OK")


if __name__ == "__main__":
    main()
