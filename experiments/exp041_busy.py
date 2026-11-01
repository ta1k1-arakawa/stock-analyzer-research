"""EXP-041: busy-day distraction x earnings surprise (descriptive).

Preregistration: docs/experiments/EXP-041_PREREGISTRATION.md

Signed surprise events use EXP-018's forecast-tracking machinery,
extended to both directions: FY/2Q results whose actual NP beats
the last company forecast disclosed before them by >= +10% (pos)
or misses by >= 10% (neg). A disclosure day is "busy" when the
number of universe codes announcing earnings that day is in the
top tercile of all announcement days. Excess returns vs TOPIX are
measured from the next trading day's open at +5/+10/+20 days
(the EXP-033/036 convention). Kill rule (preregistered): if the
busy-minus-nonbusy signed-drift interaction at +10d is below
+0.5%, the direction is closed.

Usage:
    python experiments/exp041_busy.py <cache_dir>
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3

THRESHOLD = 0.10
HOLD_DAYS = (5, 10, 20)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def signed_events(cache: Path) -> list[dict]:
    events = []
    for f in sorted((cache / "fins").glob("*.json")):
        code = f.stem
        recs = [r for r in json.loads(f.read_text())
                if r.get("DiscDate")]
        recs.sort(key=lambda r: (r["DiscDate"],
                                 r.get("DiscTime") or "",
                                 r.get("DiscNo") or ""))
        last_fnp: dict[str, float] = {}
        last_fnp2q: dict[str, float] = {}
        seen: set[tuple] = set()
        for r in recs:
            pt = str(r.get("CurPerType", ""))
            en = r.get("CurFYEn", "")
            np_act = _num(r.get("NP"))
            sales = _num(r.get("Sales"))
            if np_act is not None and sales is not None and en:
                kind, fc = None, None
                if pt.endswith("FY"):
                    kind, fc = "FY", last_fnp.get(en)
                elif pt == "2Q":
                    kind, fc = "2Q", last_fnp2q.get(en)
                if kind and fc and fc > 0:
                    surp = np_act / fc - 1.0
                    if abs(surp) >= THRESHOLD \
                            and (r["DiscDate"], code) not in seen:
                        seen.add((r["DiscDate"], code))
                        events.append({
                            "disc_date": r["DiscDate"], "code": code,
                            "surprise": surp,
                            "sign": "pos" if surp > 0 else "neg"})
            v = _num(r.get("FNP"))
            if v is not None and en:
                last_fnp[en] = v
            v2 = _num(r.get("FNP2Q"))
            if v2 is not None and en:
                last_fnp2q[en] = v2
    return events


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    cidx = {c: i for i, c in enumerate(codes)}
    O = panel["O"].to_numpy()
    C = panel["C"].to_numpy()
    TC = topix["C"].to_numpy()

    # busy-day counts: earnings announcements per date (code-deduped)
    day_codes: dict[str, set] = {}
    for code, recs in fins.items():
        for r in recs:
            if str(r.get("CurPerType", "")) in ("FY", "1Q", "2Q", "3Q") \
                    and r.get("DiscDate"):
                day_codes.setdefault(r["DiscDate"][:10], set()).add(code)
    counts = np.array(sorted(len(v) for v in day_codes.values()))
    thr = float(np.quantile(counts, 2.0 / 3.0))
    busy_dates = {d for d, v in day_codes.items() if len(v) >= thr}

    events = signed_events(cache)
    rows = []
    for ev in events:
        d = pd.Timestamp(ev["disc_date"][:10])
        ti = int(dates.searchsorted(d, side="right"))
        i = cidx.get(ev["code"])
        if i is None or ti >= len(dates) or not np.isfinite(O[ti, i]) \
                or O[ti, i] <= 0:
            continue
        row = {"code": ev["code"], "disc_date": ev["disc_date"][:10],
               "sign": ev["sign"],
               "busy": ev["disc_date"][:10] in busy_dates,
               "surprise": ev["surprise"]}
        ok = True
        for hd in HOLD_DAYS:
            if ti + hd >= len(dates) \
                    or not np.isfinite(C[ti + hd, i]):
                ok = False
                break
            row[f"ex{hd}"] = float(
                (C[ti + hd, i] / O[ti, i] - 1.0)
                - (TC[ti + hd] / TC[ti] - 1.0))
        if ok:
            rows.append(row)
    df = pd.DataFrame(rows)

    def cell(mask, hd):
        s = df.loc[mask, f"ex{hd}"]
        return {"n": int(len(s)),
                "mean_pct": round(float(s.mean()) * 100, 2)
                if len(s) else None,
                "median_pct": round(float(s.median()) * 100, 2)
                if len(s) else None}

    groups = {}
    for sign in ("pos", "neg"):
        for busy in (True, False):
            m = (df["sign"] == sign) & (df["busy"] == busy)
            groups[f"{sign}_{'busy' if busy else 'non'}"] = {
                hd: cell(m, hd) for hd in HOLD_DAYS}

    def signed(group, hd):
        m = groups[group][hd]["mean_pct"]
        if m is None:
            return None
        return m if group.startswith("pos") else -m

    interaction = {}
    for hd in HOLD_DAYS:
        vals = [signed("pos_busy", hd), signed("pos_non", hd),
                signed("neg_busy", hd), signed("neg_non", hd)]
        interaction[str(hd)] = None if any(v is None for v in vals) \
            else round(((vals[0] - vals[1]) + (vals[2] - vals[3])) / 2.0,
                       2)
    eras = {}
    for era, (a, b) in {"first_half": ("2017-01-04", "2021-12-30"),
                        "second_half": ("2022-01-04",
                                        "2026-09-25")}.items():
        sub = df[(df["disc_date"] >= a) & (df["disc_date"] <= b)]
        eras[era] = {"n": int(len(sub)),
                     "pos_busy_10": round(float(sub[
                         (sub["sign"] == "pos") & sub["busy"]
                         ]["ex10"].mean()) * 100, 2) if len(sub) else None,
                     "pos_non_10": round(float(sub[
                         (sub["sign"] == "pos") & ~sub["busy"]
                         ]["ex10"].mean()) * 100, 2) if len(sub) else None}
    print(json.dumps(
        {"busy_threshold_count": thr,
         "announcement_days": int(len(counts)),
         "busy_days": int(len(busy_dates)),
         "events_total": int(len(df)),
         "groups": groups, "interaction_pct": interaction,
         "eras": eras}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
