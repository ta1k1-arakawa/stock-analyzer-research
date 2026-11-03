"""Descriptive kill test for round-8 idea 1: asymmetric-beta construction.

Kill if ANY of:
 (a) 20bd-ahead rank autocorrelation of (beta- - beta+) < 0.3
 (b) in crash windows, the low-beta- long subset's realised down-day beta
     is NOT at least 0.15 below the champion top-20's
 (c) non-crash mean-return give-up of the low-beta- subset exceeds 15%
     of the champion long subset's mean return
Estimation: trailing 250bd, TOPIX down/up days split. Subsets formed
from A's top-40 by score at each 20bd point; forward window 20bd.
Crash windows (DD diagnostic episodes): 2018-10-01..2020-03-31,
2024-07-01..2024-09-30.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent))
import exp003_rotation as E3
import exp010_earnings_momentum as E10

CACHE = Path("/home/hatch/workspace/cache/jquants_exp002")
CRASH = [(pd.Timestamp("2018-10-01"), pd.Timestamp("2020-03-31")),
         (pd.Timestamp("2024-07-01"), pd.Timestamp("2024-09-30"))]
WIN, STEP, FWD = 250, 20, 20


def main() -> None:
    topix, panel, fins = E3.load(CACHE)
    dates = topix.index
    close = panel["C"].ffill()
    ret = close.pct_change(fill_method=None)
    tret = topix["C"].pct_change(fill_method=None)
    comp = E3.signals(panel, fins, dates)["composite"]
    mom = E10.revision_momentum_scores(fins, dates, list(close.columns))
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid)) / 2.0).where(valid)

    R = ret.to_numpy()
    T = tret.to_numpy()
    in_crash = np.zeros(len(dates), dtype=bool)
    for a, b in CRASH:
        in_crash |= (dates >= a) & (dates <= b)

    points = list(range(WIN + 1, len(dates) - FWD, STEP))
    asym_series = {}
    persist = []
    prev_asym = None
    down_pairs = {k: ([], []) for k in ("L1", "L2")}   # (subset ret, topix ret) on down days in crash
    noncrash = {k: [] for k in ("L1", "L2")}
    n_form = 0
    for t in points:
        w = slice(t - WIN, t)
        tw = T[w]
        down = tw < 0
        up = tw > 0
        if down.sum() < 40:
            continue
        rw = R[w]
        ok = np.isfinite(rw).sum(axis=0) >= 200

        def beta(mask):
            x = tw[mask]
            y = rw[mask]
            xm = np.nanmean(x)
            num = np.nansum((y - np.nanmean(y, axis=0)) * (x - xm)[:, None], axis=0)
            den = np.sum((x - xm) ** 2)
            return num / den

        bm, bp = beta(down), beta(up)
        asym = pd.Series(bm - bp, index=close.columns).where(ok)
        if prev_asym is not None:
            both = pd.concat([prev_asym, asym], axis=1).dropna()
            if len(both) > 50:
                persist.append(spearmanr(both.iloc[:, 0], both.iloc[:, 1]).statistic)
        prev_asym = asym

        srow = score_a.iloc[t - 1].dropna()
        if len(srow) < 40:
            continue
        top40 = srow.nlargest(40).index
        l1 = list(srow.nlargest(20).index)
        bminus = pd.Series(bm, index=close.columns)
        cand = [c for c in top40 if np.isfinite(bminus.get(c, np.nan))]
        if len(cand) < 20:
            continue
        l2 = list(bminus[cand].nsmallest(20).index)
        n_form += 1
        fw = slice(t, t + FWD)
        fr = R[fw]
        ft = T[fw]
        fc = in_crash[fw]
        idx = {c: j for j, c in enumerate(close.columns)}
        for key, names in (("L1", l1), ("L2", l2)):
            sub = np.nanmean(fr[:, [idx[c] for c in names]], axis=1)
            dmask = fc & (ft < 0) & np.isfinite(sub)
            down_pairs[key][0].extend(sub[dmask])
            down_pairs[key][1].extend(ft[dmask])
            nmask = ~fc & np.isfinite(sub)
            noncrash[key].extend(sub[nmask])

    def slope(x, y):
        x, y = np.asarray(x), np.asarray(y)
        return float(np.sum((x - x.mean()) * (y - y.mean())) / np.sum((x - x.mean()) ** 2))

    b1 = slope(down_pairs["L1"][1], down_pairs["L1"][0])
    b2 = slope(down_pairs["L2"][1], down_pairs["L2"][0])
    m1 = float(np.mean(noncrash["L1"]))
    m2 = float(np.mean(noncrash["L2"]))
    giveup = (m1 - m2) / m1 if m1 > 0 else np.nan
    ac = float(np.mean(persist)) if persist else np.nan
    print(f"formation points: {n_form}, persistence obs: {len(persist)}")
    print(f"(a) rank autocorr of asymmetry: {ac:.3f}  -> {'KILL' if ac < 0.3 else 'pass'}")
    print(f"(b) crash down-day beta: champion {b1:.3f} vs low-beta- {b2:.3f} "
          f"(gap {b1 - b2:.3f}) -> {'KILL' if (b1 - b2) < 0.15 else 'pass'}")
    print(f"(c) non-crash mean daily ret: champion {m1 * 100:.4f}% vs low-beta- {m2 * 100:.4f}% "
          f"(give-up {giveup * 100:.1f}%) -> {'KILL' if giveup > 0.15 else 'pass'}")
    killed = (ac < 0.3) or ((b1 - b2) < 0.15) or (giveup > 0.15)
    print("VERDICT:", "KILLED" if killed else "SURVIVES - eligible for preregistration draft")


if __name__ == "__main__":
    main()
