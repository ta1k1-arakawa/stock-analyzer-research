"""EXP-025: dividend-policy upgrade tilt added to A.

Preregistration: docs/experiments/EXP-025_PREREGISTRATION.md

An event is a disclosure whose annual dividend forecast (FY convention:
NxFDivAnn for FY statements, else FDivAnn) rises >= +10% versus the
previous disclosure for the same stock (previous value > 0), provided
the net-profit forecast is not cut at the same step. The policy leg is
a 60-trading-day linear decay from each event, cross-sectionally ranked
inside A's valid set; A_pay = (comp_r + mom_r + policy_rank) / 3.
Judged against A (recomputed; S also reported) by the standard three
criteria.

Usage:
    python experiments/exp025_payout_tilt.py <cache_dir>
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
DECAY = 60
THRESHOLD = 0.10


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fc(r, base):
    pre = "NxF" if str(r.get("DocType", "")).startswith("FY") else "F"
    return _num(r.get(pre + base))


def detect_events(fins) -> list[tuple[str, str]]:
    """(code, disc_date) pairs satisfying the preregistered definition."""
    out = []
    for code, recs in fins.items():
        rows = [r for r in recs if r.get("DiscDate")]
        rows.sort(key=lambda r: (r["DiscDate"], r.get("DiscTime") or ""))
        prev = None
        for r in rows:
            if prev is not None:
                d0, d1 = _fc(prev, "DivAnn"), _fc(r, "DivAnn")
                n0, n1 = _fc(prev, "NP"), _fc(r, "NP")
                if d0 is not None and d1 is not None and d0 > 0 \
                        and d1 / d0 - 1.0 >= THRESHOLD \
                        and not (n0 is not None and n1 is not None
                                 and n1 < n0):
                    out.append((code, r["DiscDate"]))
            prev = r
    return out


def policy_raw(events, dates, codes) -> np.ndarray:
    T, N = len(dates), len(codes)
    col_of = {c: j for j, c in enumerate(codes)}
    raw = np.zeros((T, N))
    for code, d in events:
        j = col_of.get(code)
        if j is None:
            continue
        u = int(dates.searchsorted(pd.Timestamp(d), side="left"))
        for t in range(u, min(u + DECAY, T)):
            v = 1.0 - (t - u) / DECAY
            if v > raw[t, j]:
                raw[t, j] = v
    return raw


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)

    valid = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    mom_r = mom.where(valid)
    score_a = ((comp_r + mom_r) / 2.0).where(valid)

    events = detect_events(fins)
    raw = pd.DataFrame(policy_raw(events, dates, codes),
                       index=dates, columns=codes)
    pol_r = raw.where(valid).rank(axis=1, pct=True)
    score_pay = ((comp_r + mom_r + pol_r) / 3.0).where(valid)

    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    mats = {"S": comp.to_numpy(), "A": score_a.to_numpy(),
            "A_pay": score_pay.to_numpy()}

    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            for nm, mat in mats.items():
                res[f"{pname}_{nm}_{cname}"] = E9.stats(pd.Series(
                    E9.simulate(mat, o, c_ff, start, end, cost, carry,
                                1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_pay_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_pay_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_pay_stress"]["profit"] > 0
            and ratio("full_A_pay_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict,
                      "diag": {"events": len(events)}},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
