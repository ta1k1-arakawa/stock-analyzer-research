"""EXP-040: earnings announcement delay tilt.

Preregistration: docs/experiments/EXP-040_PREREGISTRATION.md

For each earnings disclosure in the J-Quants summary records
(CurPerType FY/1Q/2Q/3Q), delay = (gap in days to the immediately
preceding same-period-type disclosure) - 365, defined when the
gap is 300-400 days. The daily leg is the most recent measured
delay (no expiry), usable from the first trading day >= the
disclosure date; leg score = -delay. A_delay = (composite rank +
revision-momentum rank + leg rank) / 3 on A's valid set, missing
leg = neutral 0.5. Judged against A by the standard criteria.

Usage:
    python experiments/exp040_delay.py <cache_dir>
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


def delay_panel(fins, dates, codes) -> pd.DataFrame:
    events: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    for code in codes:
        rs = []
        for r in fins.get(code, []):
            dd = r.get("DiscDate")
            pt = r.get("CurPerType")
            if dd and pt in ("FY", "1Q", "2Q", "3Q"):
                try:
                    rs.append((pd.Timestamp(dd), pt))
                except (ValueError, TypeError):
                    pass
        rs.sort()
        prev: dict[str, pd.Timestamp] = {}
        ev = []
        for d, pt in rs:
            p = prev.get(pt)
            if p is not None:
                gap = (d - p).days
                if 300 <= gap <= 400:
                    ev.append((d, float(gap - 365)))
            prev[pt] = d
        events[code] = ev
    out = pd.DataFrame(np.nan, index=dates, columns=codes)
    for code, ev in events.items():
        if not ev:
            continue
        ev_dates = pd.DatetimeIndex([d for d, _ in ev])
        vals = np.array([v for _, v in ev])
        pos = dates.searchsorted(ev_dates, side="left")
        ser = pd.Series(vals, index=pos)
        ser = ser[~ser.index.duplicated(keep="last")]
        col = pd.Series(np.nan, index=range(len(dates)))
        col.loc[ser.index] = ser.values
        out[code] = col.ffill().reindex(range(len(dates))).to_numpy()
    return out


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    o_np = panel["O"].to_numpy()
    c_np = panel["C"].ffill().to_numpy()

    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid)) / 2.0) \
        .where(valid)

    delay = delay_panel(fins, dates, codes)
    leg = -delay
    cov = (leg.where(valid).notna() & valid).sum(axis=1) \
        / valid.sum(axis=1)
    leg_rank = leg.where(valid).rank(axis=1, pct=True)
    score = ((comp.rank(axis=1, pct=True) + mom.where(valid)
              + leg_rank.fillna(0.5)) / 3.0).where(valid)

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
            res[f"{pname}_A_delay_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score.to_numpy(), o_np, c_np, s0, e0, cost,
                            carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_delay_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_delay_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_delay_stress"]["profit"] > 0
            and ratio("full_A_delay_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps(
        {"res": res, "verdict": verdict,
         "leg_coverage_median": float(cov.median())},
        ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
