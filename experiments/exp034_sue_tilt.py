"""EXP-034: earnings-surprise (SUE) tilt inside A.

Preregistration: docs/experiments/EXP-034_PREREGISTRATION.md

The surprise machinery is EXP-018's, unchanged: forecasts are
tracked in disclosure order per fiscal year (FY vs FNP, 2Q vs
FNP2Q); a surprise is recorded for every results record carrying
both NP and Sales when the tracked forecast is > 0. The leg value
on a trading day is the most recent surprise whose DiscDate is at
most 90 calendar days old (usable from the first trading day on or
after DiscDate). A_sue = (composite rank + revision-momentum rank
+ surprise rank) / 3 on A's valid set; names with no active
surprise are ranked neutral 0.5. Judged against A by the standard
three criteria.

Usage:
    python experiments/exp034_sue_tilt.py <cache_dir>
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
WINDOW_DAYS = 90


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def surprises(cache: Path) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = {}
    for f in sorted((cache / "fins").glob("*.json")):
        code = f.stem
        recs = [r for r in json.loads(f.read_text()) if r.get("DiscDate")]
        recs.sort(key=lambda r: (r["DiscDate"], r.get("DiscTime") or "",
                                 r.get("DiscNo") or ""))
        last_fnp: dict[str, float] = {}
        last_fnp2q: dict[str, float] = {}
        evs: list[tuple[str, float]] = []
        for r in recs:
            pt = str(r.get("CurPerType", ""))
            en = r.get("CurFYEn", "")
            np_act, sales = _num(r.get("NP")), _num(r.get("Sales"))
            if np_act is not None and sales is not None and en:
                fc = None
                if pt.endswith("FY"):
                    fc = last_fnp.get(en)
                elif pt == "2Q":
                    fc = last_fnp2q.get(en)
                if fc and fc > 0:
                    evs.append((r["DiscDate"], np_act / fc - 1.0))
            v = _num(r.get("FNP"))
            if v is not None and en:
                last_fnp[en] = v
            v2 = _num(r.get("FNP2Q"))
            if v2 is not None and en:
                last_fnp2q[en] = v2
        if evs:
            out[code] = evs
    return out


def sue_frame(cache: Path, dates: pd.DatetimeIndex,
              codes: list[str]) -> pd.DataFrame:
    evs_by_code = surprises(cache)
    frame = pd.DataFrame(np.nan, index=dates, columns=codes)
    for code, evs in evs_by_code.items():
        if code not in frame.columns:
            continue
        col = np.full(len(dates), np.nan)
        for disc, val in evs:
            d0 = pd.Timestamp(disc)
            i0 = int(dates.searchsorted(d0))
            i1 = int(dates.searchsorted(d0 + pd.Timedelta(
                days=WINDOW_DAYS), side="right")) - 1
            if i0 < len(dates):
                col[i0:max(i1, i0) + 1] = val
        frame[code] = col
    return frame


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)
    sue = sue_frame(cache, dates, codes)

    valid = comp.notna()
    win = (dates >= pd.Timestamp("2017-01-04")) \
        & (dates <= pd.Timestamp("2026-09-25"))
    diag = {"sue_coverage_median": float(
        (sue.notna() & valid).sum(axis=1)[win].div(
            valid.sum(axis=1)[win]).median()),
        "codes_with_surprise": int(sue.notna().any().sum())}

    comp_r = comp.rank(axis=1, pct=True)
    sue_r = sue.where(valid).rank(axis=1, pct=True) \
        .where(sue.notna(), 0.5)
    score_a = ((comp_r + mom.where(valid)) / 2.0).where(valid)
    score_s = ((comp_r + mom.where(valid) + sue_r) / 3.0).where(valid)

    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(comp.to_numpy(), o, c_ff, start, end, cost,
                            carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_a.to_numpy(), o, c_ff, start, end,
                            cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_sue_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_s.to_numpy(), o, c_ff, start, end,
                            cost, carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_sue_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_sue_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_sue_stress"]["profit"] > 0
            and ratio("full_A_sue_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
