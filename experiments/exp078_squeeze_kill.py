"""Descriptive kill test for round-8 idea 3: short-leg squeeze screen.

Kill rule (from the sweep report): crowded names must contribute at
least 1.5x their weight to short-leg losses on rebound days, else kill.

Crowded = within A's bottom-40 score band, top quintile of aggregate
disclosed short ratio (EXP-042 agg_panel, holders' latest reports).
Rebound days = forward-20bd days where the equal-weight bottom-40
return >= +1.0%. Short loss on a day = max(-ret, 0) summed per name.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent))
import exp003_rotation as E3
import exp010_earnings_momentum as E10
import exp042_short_report as E42

CACHE = Path("/home/hatch/workspace/cache/jquants_exp002")
REPORTS = Path("/home/hatch/workspace/cache/short_report_exp042")
STEP, FWD = 20, 20


def main() -> None:
    topix, panel, fins = E3.load(CACHE)
    dates = topix.index
    close = panel["C"].ffill()
    codes = list(close.columns)
    ret = close.pct_change(fill_method=None)
    comp = E3.signals(panel, fins, dates)["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid)) / 2.0).where(valid)
    agg = E42.agg_panel(REPORTS, dates, codes)

    R = ret.to_numpy()
    idx = {c: j for j, c in enumerate(codes)}
    tot_loss = crowd_loss = 0.0
    tot_w = crowd_w = 0
    tot_loss_all = crowd_loss_all = 0.0
    points = 0
    for t in range(1, len(dates) - FWD, STEP):
        srow = score_a.iloc[t - 1].dropna()
        if len(srow) < 40:
            continue
        band = list(srow.nsmallest(40).index)
        arow = agg.iloc[t - 1]
        pos = {c: arow.get(c, np.nan) for c in band}
        pos = {c: v for c, v in pos.items() if np.isfinite(v) and v > 0}
        if len(pos) < 5:
            continue
        thr = np.quantile(list(pos.values()), 0.8)
        crowded = {c for c, v in pos.items() if v >= thr}
        fw = R[t:t + FWD]
        band_ret = np.nanmean(fw[:, [idx[c] for c in band]], axis=1)
        rebound = band_ret >= 0.01
        points += 1
        tot_w += len(band)
        crowd_w += len(crowded)
        for c in band:
            r = fw[:, idx[c]]
            loss_all = np.nansum(np.where(r > 0, r, 0.0))
            loss_reb = np.nansum(np.where(rebound & (r > 0), r, 0.0))
            tot_loss_all += loss_all
            tot_loss += loss_reb
            if c in crowded:
                crowd_loss_all += loss_all
                crowd_loss += loss_reb
    w_share = crowd_w / tot_w
    l_share = crowd_loss / tot_loss if tot_loss > 0 else np.nan
    l_share_all = crowd_loss_all / tot_loss_all if tot_loss_all > 0 else np.nan
    ratio = l_share / w_share if w_share > 0 else np.nan
    print(f"formation points: {points}")
    print(f"crowded weight share: {w_share:.3f}")
    print(f"crowded share of rebound-day short losses: {l_share:.3f} "
          f"(ratio {ratio:.2f}x) -> {'KILL' if ratio < 1.5 else 'pass'}")
    print(f"reference: crowded share of ALL-day short losses: {l_share_all:.3f} "
          f"(ratio {l_share_all / w_share:.2f}x)")
    print("VERDICT:", "KILLED" if ratio < 1.5 else "SURVIVES - eligible for preregistration draft")


if __name__ == "__main__":
    main()
