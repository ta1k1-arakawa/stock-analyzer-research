"""EXP-085 descriptive gate: partial sector neutralisation.

Preregistration: docs/experiments/EXP-085_PREREGISTRATION.md
(a) Activation share: days where A's top-20 book has a sector whose
    weight deviates from the benchmark (universe market-cap sector
    weights) by more than the trailing-500d 80th percentile of the
    daily max divergence. Must be 10-40% of days.
(b) The mean max divergence in the two factor-winter episodes
    (2021-09..11, 2026-02..05) must exceed the non-episode mean.
Both must hold, else KILLED without a book test.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import exp003_rotation as E3
import exp010_earnings_momentum as E10

CACHE = Path("/home/hatch/workspace/cache/jquants_exp002")
SECTORS = Path("/home/hatch/workspace/exp080_kill/sectors.json")


def main() -> None:
    topix, panel, fins = E3.load(CACHE)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid)) / 2.0).where(valid)
    sec = pd.Series(json.loads(SECTORS.read_text())).reindex(codes)
    mcap = panel["MktCap"].reindex(columns=codes)

    win = (dates >= "2017-01-04") & (dates <= "2026-09-25")
    maxdiv = pd.Series(np.nan, index=dates, dtype=float)
    for i in np.flatnonzero(win):
        s = score_a.iloc[i].dropna()
        if len(s) < 20:
            continue
        top = s.nlargest(20).index
        bw = sec[top].value_counts(normalize=True)
        mc = mcap.iloc[i]
        bench = mc.groupby(sec).sum()
        bench = bench / bench.sum()
        both = bw.index.union(bench.index)
        d = (bw.reindex(both, fill_value=0.0) - bench.reindex(both, fill_value=0.0)).abs()
        maxdiv.iloc[i] = float(d.max())
    md = maxdiv[win].dropna()
    thr = md.rolling(500, min_periods=250).quantile(0.8)
    active = (md > thr)
    share = float(active.dropna().mean())
    ep = ((md.index >= "2021-09-01") & (md.index <= "2021-11-30")) | \
         ((md.index >= "2026-02-01") & (md.index <= "2026-05-31"))
    ep_mean = float(md[ep].mean())
    norm_mean = float(md[~ep].mean())
    a_ok = 0.10 <= share <= 0.40
    b_ok = ep_mean > norm_mean
    print(json.dumps({
        "max_divergence_mean": round(float(md.mean()), 4),
        "activation_share": round(share, 3), "a_ok_10_40pct": bool(a_ok),
        "episode_mean_divergence": round(ep_mean, 4),
        "normal_mean_divergence": round(norm_mean, 4), "b_ok": bool(b_ok),
        "verdict": "SURVIVES" if (a_ok and b_ok) else "KILLED"},
        ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
