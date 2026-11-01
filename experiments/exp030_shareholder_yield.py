"""EXP-030: total shareholder yield (level) tilt.

Preregistration: docs/experiments/EXP-030_PREREGISTRATION.md

TSY = forecast dividend yield (annual dividend forecast, FY
convention, over the day's close) + buyback yield (negative YoY
change in net shares outstanding, ShOutFY - TrShFY, measured between
consecutive distinct observed values). Point-in-time from disclosure
dates; forward-filled. A_tsy = (composite rank + revision-momentum
rank + TSY rank) / 3 on A's valid set; missing TSY ranked neutral
0.5, and the buyback component is 0 until a share-count pair exists.
Judged against A (recomputed; S also reported) by the standard three
criteria.

Usage:
    python experiments/exp030_shareholder_yield.py <cache_dir>
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


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _div_forecast(r: dict) -> float:
    if r.get("CurPerType") == "FY" and "FinancialStatements" in str(
            r.get("DocType", "")):
        return _num(r.get("NxFDivAnn"))
    return _num(r.get("FDivAnn"))


def _net_shares(r: dict) -> float:
    sh = _num(r.get("ShOutFY"))
    if not np.isfinite(sh) or sh <= 0:
        return float("nan")
    tr = _num(r.get("TrShFY"))
    return sh - (tr if np.isfinite(tr) else 0.0)


def tsy_frame(fins, dates: pd.DatetimeIndex, codes: list[str],
              close: pd.DataFrame):
    """Daily TSY per code: (tsy, diag)."""
    div_ev: dict[str, list] = {}
    bb_ev: dict[str, list] = {}
    for code in codes:
        recs = fins.get(code, [])
        rows = []
        for r in recs:
            d = pd.to_datetime(r.get("DiscDate"), errors="coerce")
            if pd.isna(d):
                continue
            rows.append((d.normalize(), str(r.get("DiscTime", "")), r))
        rows.sort(key=lambda x: (x[0], x[1]))
        divs, bbs = [], []
        last_sh = None
        prev_sh = None
        for d, _t, r in rows:
            dv = _div_forecast(r)
            if np.isfinite(dv):
                divs.append((d, dv))
            ns = _net_shares(r)
            if np.isfinite(ns) and ns != last_sh:
                prev_sh, last_sh = last_sh, ns
                if prev_sh is not None and prev_sh > 0:
                    bbs.append((d, -(ns / prev_sh - 1.0)))
        div_ev[code], bb_ev[code] = divs, bbs

    def step_series(events, fill_from_first=True):
        out = pd.DataFrame(np.nan, index=dates, columns=codes, dtype=float)
        for code, ev in events.items():
            if not ev:
                continue
            col = np.full(len(dates), np.nan)
            for d, v in ev:
                i = int(dates.searchsorted(d))
                if i < len(dates):
                    col[i] = v
            out[code] = pd.Series(col).ffill().to_numpy()
        return out

    div_fc = step_series(div_ev)
    bb = step_series(bb_ev).fillna(0.0)
    div_yield = div_fc / close
    tsy = div_yield + bb.where(div_yield.notna())
    diag = {
        "codes_with_div_forecast": int(div_fc.notna().any().sum()),
        "codes_with_buyback_pair": int(
            sum(1 for v in bb_ev.values() if v)),
        "median_tsy_coverage_valid": None,
    }
    return tsy, div_yield, diag


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)

    tsy, div_yield, diag = tsy_frame(fins, dates, codes, panel["C"])
    valid = comp.notna()
    win = (dates >= pd.Timestamp("2017-01-04")) \
        & (dates <= pd.Timestamp("2026-09-25"))
    cov = (tsy.notna() & valid).sum(axis=1) / valid.sum(axis=1)
    diag["median_tsy_coverage_valid"] = float(cov[win].median())
    diag["mean_div_yield_pct"] = float(
        np.nanmean(div_yield.to_numpy()[win]) * 100)

    comp_r = comp.rank(axis=1, pct=True)
    tsy_r = tsy.where(valid).rank(axis=1, pct=True).where(tsy.notna(), 0.5)
    score_a = ((comp_r + mom.where(valid)) / 2.0).where(valid)
    score_t = ((comp_r + mom.where(valid) + tsy_r) / 3.0).where(valid)

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
            res[f"{pname}_A_tsy_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_t.to_numpy(), o, c_ff, start, end,
                            cost, carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_tsy_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_tsy_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_tsy_stress"]["profit"] > 0
            and ratio("full_A_tsy_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
