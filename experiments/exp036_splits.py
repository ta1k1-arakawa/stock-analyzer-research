"""EXP-036: descriptive event study of stock-split announcements.

Preregistration: docs/experiments/EXP-036_PREREGISTRATION.md
Events: TDnet titles containing 株式分割 and none of
訂正 / 中止 / 基本方針, deduplicated by (code, date). Long entry
at the open of the first trading day strictly after the
disclosure date; excess return vs TOPIX at +5 / +10 / +20 trading
days (same convention as EXP-033). A secondary split reports the
pre-announcement investment unit (prior close x 100 shares)
above / below JPY 500,000. No pass/fail criteria.

Usage:
    python experiments/exp036_splits.py <cache_dir> <tdnet_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3

EXCL = ("訂正", "中止", "基本方針")
HORIZONS = (5, 10, 20)


def load_events(tdnet_dir: Path) -> list[dict]:
    out, seen = [], set()
    for f in sorted(tdnet_dir.glob("*.json")):
        for it in json.loads(f.read_text())["items"]:
            t = it["title"]
            if "株式分割" not in t or any(x in t for x in EXCL):
                continue
            key = (it["code"], it["pubdate"][:10])
            if key in seen:
                continue
            seen.add(key)
            out.append({"code": it["code"], "date": it["pubdate"][:10]})
    return sorted(out, key=lambda e: e["date"])


def main(cache: Path, tdnet_dir: Path) -> None:
    topix, panel, _ = E3.load(cache)
    dates = topix.index
    tpx = topix["C"]
    events = load_events(tdnet_dir)
    rows = []
    for ev in events:
        code = ev["code"]
        if code not in panel["O"].columns:
            continue
        d0 = pd.Timestamp(ev["date"])
        ei = int(dates.searchsorted(d0, side="right"))
        if ei >= len(dates):
            continue
        entry_open = panel["O"][code].iloc[ei]
        prev_close = panel["C"][code].iloc[ei - 1]
        if not np.isfinite(entry_open) or entry_open <= 0:
            continue
        row = {"code": code, "disc": ev["date"],
               "half": "FH" if d0 < pd.Timestamp("2022-01-01") else "SH",
               "unit_hi": bool(np.isfinite(prev_close)
                               and prev_close * 100 >= 500_000)}
        for h in HORIZONS:
            xi = ei + h
            if xi >= len(dates):
                row[f"ex{h}"] = None
                continue
            r_stock = panel["C"][code].iloc[xi] / entry_open - 1.0
            r_tpx = tpx.iloc[xi] / tpx.iloc[ei - 1] - 1.0
            row[f"ex{h}"] = float(r_stock - r_tpx) \
                if np.isfinite(r_stock) else None
        rows.append(row)
    df = pd.DataFrame(rows)
    print(f"events measured: {len(df)} (of {len(events)} classified)")
    summary = {}
    groups = {"ALL": df, "FH": df[df["half"] == "FH"],
              "SH": df[df["half"] == "SH"],
              "unit_hi": df[df["unit_hi"]],
              "unit_lo": df[~df["unit_hi"]]}
    for name, sub in groups.items():
        if sub.empty:
            continue
        cell = {"n": int(len(sub))}
        for h in HORIZONS:
            v = sub[f"ex{h}"].dropna()
            if len(v):
                cell[f"h{h}"] = {
                    "n": int(len(v)),
                    "mean_pct": round(float(v.mean()) * 100, 2),
                    "median_pct": round(float(v.median()) * 100, 2),
                    "share_positive": round(float((v > 0).mean()), 3),
                }
        summary[name] = cell
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
