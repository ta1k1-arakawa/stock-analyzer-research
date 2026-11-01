"""EXP-042: disclosed short-position reports - guard + change tilt.

Preregistration: docs/experiments/EXP-042_PREREGISTRATION.md

Aggregation (registered): exact-duplicate records dropped; holder
key = (SSName, DICName, FundName); a holder's current ratio is
their latest report by (CalcDate, DiscDate), effective from its
DiscDate; agg(code, day) = sum of current ratios over holders
whose latest DiscDate is within the trailing 365 days; codes with
no reports have agg = 0.
A_g1: A on the long side; short side excludes names whose agg is
at or above the day's 90th percentile among agg > 0 names.
A_chg: d = agg - agg 20 trading days earlier; long score =
(comp + mom + rank(-d)) / 3, short score = (comp + mom +
rank(+d)) / 3, via EXP-013's two-sided simulator.
Both variants are judged against A by the standard criteria.

Usage:
    python experiments/exp042_short_report.py <cache_dir> \
        <short_report_dir>
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
STALE_DAYS = 365


def agg_panel(report_dir: Path, dates, codes) -> pd.DataFrame:
    out = pd.DataFrame(0.0, index=dates, columns=codes)
    for code in codes:
        fp = report_dir / f"{code}.json"
        if not fp.exists():
            continue
        rows = json.loads(fp.read_text())
        seen = set()
        events = []
        for r in rows:
            key = json.dumps(r, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            try:
                ratio = float(r.get("ShrtPosToSO"))
                dd = pd.Timestamp(r["DiscDate"])
                cd = pd.Timestamp(r["CalcDate"])
            except (TypeError, ValueError, KeyError):
                continue
            holder = (r.get("SSName"), r.get("DICName"),
                      r.get("FundName"))
            events.append((dd, cd, holder, ratio))
        if not events:
            continue
        events.sort(key=lambda e: (e[0], e[1]))
        state: dict = {}
        ei = 0
        vals = np.zeros(len(dates))
        for ti, t in enumerate(dates):
            while ei < len(events) and events[ei][0] <= t:
                _, _, holder, ratio = events[ei]
                state[holder] = (ratio, events[ei][0])
                ei += 1
            cutoff = t - pd.Timedelta(days=STALE_DAYS)
            vals[ti] = sum(v for v, last in state.values()
                           if last >= cutoff)
        out[code] = vals
    return out


def main(cache: Path, report_dir: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    o_np = panel["O"].to_numpy()
    c_np = panel["C"].ffill().to_numpy()

    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    score_a = ((comp_r + mom.where(valid)) / 2.0).where(valid)

    agg = agg_panel(report_dir, dates, codes)
    n_positive = (agg > 0).sum(axis=1)

    # A_g1: short-side guard
    short_g1 = score_a.copy()
    thr = agg.where(agg > 0).quantile(0.9, axis=1)
    guarded = (agg >= thr.to_numpy()[:, None]) & (agg > 0) & valid
    short_g1 = short_g1.mask(guarded)

    # A_chg: change tilt, two-sided
    d = agg - agg.shift(20)
    leg_long = (-d).where(valid).rank(axis=1, pct=True)
    leg_short = d.where(valid).rank(axis=1, pct=True)
    long_chg = ((comp_r + mom.where(valid) + leg_long) / 3.0) \
        .where(valid)
    short_chg = ((comp_r + mom.where(valid) + leg_short) / 3.0) \
        .where(valid)

    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        s0 = int(dates.searchsorted(pd.Timestamp(a)))
        e0 = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[s0:e0 + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(comp.to_numpy(), o_np, c_np, s0, e0, cost,
                            carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_a.to_numpy(), o_np, c_np, s0, e0,
                            cost, carry, 1.0, 0.5), index=idx))
            for nm, ls, ss in (("A_g1", score_a, short_g1),
                               ("A_chg", long_chg, short_chg)):
                res[f"{pname}_{nm}_{cname}"] = E9.stats(pd.Series(
                    E13.simulate2(ls.to_numpy(), ss.to_numpy(), o_np,
                                  c_np, s0, e0, cost, carry, 1.0, 0.5),
                    index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    def judge(nm):
        v = {
            "1_profit_positive_both_halves": bool(all(
                res[f"{p}_{nm}_base"]["profit"] > 0
                for p in ("first_half", "second_half"))),
            "2_ratio_beats_A_both_halves": bool(all(
                ratio(f"{p}_{nm}_base") > ratio(f"{p}_A_base")
                for p in ("first_half", "second_half"))),
            "3_full_stress_beats_A": bool(
                res[f"full_{nm}_stress"]["profit"] > 0
                and ratio(f"full_{nm}_stress")
                > ratio("full_A_stress")),
        }
        v["promising"] = bool(all(v.values()))
        return v

    print(json.dumps(
        {"res": res,
         "verdict_g1": judge("A_g1"), "verdict_chg": judge("A_chg"),
         "names_with_agg_median": float(n_positive.median()),
         "guarded_names_median": float(
             guarded.sum(axis=1).median())},
        ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
