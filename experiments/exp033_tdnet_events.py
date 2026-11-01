"""EXP-033: descriptive event study of adverse TDnet disclosures in
the 306-name universe (yuutai abolition / dilutive issuance).

Preregistration: docs/experiments/EXP-033_PREREGISTRATION.md
No pass/fail criteria. Titles were fetched from the free yanoshin
TDnet mirror (daily lists 2016-10-01..2026-09-30, all 3,652 days;
306-code items kept in <tdnet_dir>). Entry is the open of the first
trading day strictly after the disclosure date; exits at the close
5 / 10 / 20 trading days after the entry day. Excess return is vs
TOPIX over the matched window (TOPIX entry leg uses the prior
close, as TOPIX opens are not in the cache).

Usage:
    python experiments/exp033_tdnet_events.py <cache_dir> <tdnet_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3

EXCL = ("払込完了", "訂正", "子会社", "取得", "繰上償還", "権利発生",
        "行使価額の修正", "信託", "変更")
HORIZONS = (5, 10, 20)


def classify(title: str) -> str | None:
    if "優待" in title and "廃止" in title:
        return "Y"
    if "発行" in title and not any(x in title for x in EXCL):
        target = ("新株式" in title or "新株予約権付社債" in title
                  or "転換社債" in title)
        route = "第三者割当" in title or "公募" in title
        if target and route:
            return "ISS-A" if "提携" in title else "ISS-P"
    return None


def load_events(tdnet_dir: Path) -> list[dict]:
    out = []
    for f in sorted(tdnet_dir.glob("*.json")):
        for it in json.loads(f.read_text())["items"]:
            cls = classify(it["title"])
            if cls:
                out.append({"cls": cls, "code": it["code"],
                            "date": it["pubdate"][:10],
                            "title": it["title"]})
    return out


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
        if not np.isfinite(entry_open) or entry_open <= 0:
            continue
        row = {"cls": ev["cls"], "code": code, "disc": ev["date"],
               "half": "FH" if d0 < pd.Timestamp("2022-01-01") else "SH"}
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
    print(f"events measured: {len(df)} "
          f"(of {len(events)} classified)")
    summary = {}
    for cls in ("Y", "ISS-A", "ISS-P"):
        for half in ("ALL", "FH", "SH"):
            sub = df if half == "ALL" else df[df["half"] == half]
            sub = sub[sub["cls"] == cls]
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
                        "share_negative": round(float((v < 0).mean()), 3),
                    }
            summary[f"{cls}_{half}"] = cell
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
