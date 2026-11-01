"""EXP-046: repeat numeric-restatement long exclusion on A.

Preregistration: docs/experiments/EXP-046_PREREGISTRATION.md

A numeric-correction event is a TDnet disclosure whose title
contains both the numeric-data-correction marker and the
earnings-release marker. A code is flagged on a day when it has
had >= 2 such events in the trailing 24 calendar months (an
event counts from the first trading day strictly after its
disclosure date). A_rst excludes flagged codes from A's long
side only (short side unchanged, via EXP-013's simulate2).

Usage:
    python experiments/exp046_restate_screen.py <cache_dir> \
        <tdnet_dir>
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


def load_events(tdnet_dir: Path, codes: list[str]) -> dict[str, list]:
    code_set = set(codes)
    events: dict[str, list] = {}
    for f in sorted(tdnet_dir.glob("*.json")):
        for it in json.loads(f.read_text())["items"]:
            code = str(it.get("code", ""))[:4]
            title = it.get("title", "")
            if code in code_set and "数値データ訂正" in title \
                    and "決算短信" in title:
                events.setdefault(code, []).append(
                    pd.Timestamp(str(it["pubdate"])[:10]))
    return events


def flag_matrix(dates: pd.DatetimeIndex, codes: list[str],
                events: dict[str, list]) -> np.ndarray:
    T, N = len(dates), len(codes)
    counts = np.zeros((T, N))
    for j, code in enumerate(codes):
        for d0 in events.get(code, []):
            eff = int(dates.searchsorted(d0, side="right"))
            end = int(dates.searchsorted(d0 + pd.DateOffset(
                months=24), side="right")) - 1
            if eff < T:
                counts[eff:min(end, T - 1) + 1, j] += 1
    return counts >= 2


def main(cache: Path, tdnet_dir: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    o_np = panel["O"].to_numpy()
    c_np = panel["C"].ffill().to_numpy()
    comp = E3.signals(panel, fins, dates)["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid))
               / 2.0).where(valid)

    events = load_events(tdnet_dir, codes)
    flagged = flag_matrix(dates, codes, events)
    long_a = score_a.to_numpy()
    long_rst = long_a.copy()
    long_rst[flagged] = np.nan

    res: dict = {"n_events": int(sum(len(v)
                                     for v in events.values())),
                 "flagged_names_median": float(np.median(
                     flagged.sum(axis=1)))}
    for pname, (a, b) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a)))
        e = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(long_a, o_np, c_np, s, e, cost, carry,
                            1.0, 0.5), index=idx))
            res[f"{pname}_A_rst_{cname}"] = E9.stats(pd.Series(
                E13.simulate2(long_rst, long_a, o_np, c_np, s, e,
                              cost, carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_rst_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_rst_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_rst_stress"]["profit"] > 0
            and ratio("full_A_rst_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
