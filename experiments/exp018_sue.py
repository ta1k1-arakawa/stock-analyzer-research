"""EXP-018: earnings-surprise (SUE-type) long-only event sleeve.

Preregistration: docs/experiments/EXP-018_PREREGISTRATION.md (committed
before this code was run).  An event fires when a results statement's
actual NP beats the last company forecast disclosed before it by
>= +10% (FY statements vs FNP for that fiscal year; 2Q statements vs
FNP2Q).  The event engine, portfolio rules and yardstick are EXP-015's,
unchanged: enter at the next open after DiscDate, hold 60 trading
days, long-only, at most 10 concurrent positions of JPY 200,000.

Run:  python experiments/exp018_sue.py [cache_dir]
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import exp003_rotation as E3
import exp009_long_short as E9

CACHE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/jquants_exp002")
BUDGET = 2_000_000.0
PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
THRESHOLD = 0.10
HOLD_DAYS = 60
MAX_POS = 10
NOTIONAL = BUDGET // MAX_POS


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def detect_events(cache: Path) -> list[dict]:
    events = []
    for f in sorted((cache / "fins").glob("*.json")):
        code = f.stem
        recs = [r for r in json.loads(f.read_text()) if r.get("DiscDate")]
        recs.sort(key=lambda r: (r["DiscDate"], r.get("DiscTime") or "",
                                 r.get("DiscNo") or ""))
        last_fnp: dict[str, float] = {}
        last_fnp2q: dict[str, float] = {}
        seen: set[tuple] = set()
        for r in recs:
            pt = str(r.get("CurPerType", ""))
            en = r.get("CurFYEn", "")
            np_act, sales = _num(r.get("NP")), _num(r.get("Sales"))
            if np_act is not None and sales is not None and en:
                kind, fc = None, None
                if pt.endswith("FY"):
                    kind, fc = "FY", last_fnp.get(en)
                elif pt == "2Q":
                    kind, fc = "2Q", last_fnp2q.get(en)
                if kind and fc and fc > 0 and np_act / fc - 1.0 >= THRESHOLD \
                        and (r["DiscDate"], code) not in seen:
                    seen.add((r["DiscDate"], code))
                    events.append({"disc_date": r["DiscDate"], "code": code,
                                   "standalone": kind == "FY"})
            v = _num(r.get("FNP"))
            if v is not None and en:
                last_fnp[en] = v
            v2 = _num(r.get("FNP2Q"))
            if v2 is not None and en:
                last_fnp2q[en] = v2
    events.sort(key=lambda e: (e["disc_date"], e["code"]))
    return events


def simulate_events(events, col_of, o, c_ff, dates, start, end, cost):
    """EXP-015's event engine, unchanged (diag key renamed only)."""
    by_entry: dict[int, list[dict]] = {}
    for e in events:
        entry = int(dates.searchsorted(pd.Timestamp(e["disc_date"]), side="right"))
        if start <= entry <= end and e["code"] in col_of:
            by_entry.setdefault(entry, []).append({**e, "j": col_of[e["code"]]})
    cash = float(BUDGET)
    pos: dict[int, tuple] = {}   # j -> (shares, exit_day)
    values = []
    diag = {"executed": 0, "skipped_full": 0, "skipped_cash": 0,
            "skipped_held": 0, "skipped_noprice": 0, "executed_fy": 0}
    for t in range(start, end + 1):
        for j in [j for j, (_sh, xd) in pos.items() if xd == t]:
            sh, _ = pos.pop(j)
            px = o[t, j] if o[t, j] > 0 else c_ff[t - 1, j]
            cash += sh * px * (1.0 - cost)
        for e in by_entry.get(t, []):
            j = e["j"]
            if j in pos:
                diag["skipped_held"] += 1
            elif len(pos) >= MAX_POS:
                diag["skipped_full"] += 1
            elif cash < NOTIONAL:
                diag["skipped_cash"] += 1
            elif not (o[t, j] > 0 and np.isfinite(o[t, j])):
                diag["skipped_noprice"] += 1
            else:
                pos[j] = (NOTIONAL / (o[t, j] * (1.0 + cost)), t + HOLD_DAYS)
                cash -= NOTIONAL
                diag["executed"] += 1
                diag["executed_fy"] += int(e["standalone"])
        values.append(cash + sum(sh * c_ff[t, j] for j, (sh, _xd) in pos.items()))
    values[-1] = cash + sum(sh * c_ff[end, j] * (1.0 - cost) for j, (sh, _xd) in pos.items())
    return np.array(values), diag


def main(cache: Path) -> None:
    if not (cache / "topix.json").exists():
        raise SystemExit(f"cache not found: {cache} (expected topix.json inside)")
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    score = comp.to_numpy()
    col_of = {c: i for i, c in enumerate(panel["C"].columns)}
    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    events = detect_events(cache)

    res: dict = {}
    diags: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start : end + 1]
        tp = topix["C"].iloc[end] / topix["O"].iloc[start] - 1
        res[f"{pname}_TOPIX"] = {"profit": round(float(tp) * BUDGET)}
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score, o, c, start, end, cost, carry, 1.0, 0.5), index=idx))
            vals, dg = simulate_events(events, col_of, o, c, dates, start, end, cost)
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(vals, index=idx))
            if cname == "base":
                diags[pname] = dg

    g = lambda p, k: res[f"{p}_A_base"][k]  # noqa: E731
    s = lambda p, k: res[f"{p}_S_base"][k]  # noqa: E731
    c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
    c2 = all((g(p, "annual_over_dd") or -9) > (s(p, "annual_over_dd") or -9)
             for p in ("first_half", "second_half"))
    gf, sf = res["full_A_stress"], res["full_S_stress"]
    c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > (sf["annual_over_dd"] or -9)
    verdict = {"A": {
        "1_profit_positive_both_halves": bool(c1),
        "2_ratio_gt_S_both_halves": bool(c2),
        "3_full_stress_positive_and_ratio_gt_S": bool(c3),
        "promising": bool(c1 and c2 and c3),
    }}
    diag = {"events_total_detected": len(events),
            "events_fy": sum(int(e["standalone"]) for e in events),
            "per_period_base": diags}
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag}, ensure_ascii=False))


if __name__ == "__main__":
    main(CACHE)
