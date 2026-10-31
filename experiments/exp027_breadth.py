"""EXP-027: multi-line revision breadth + coherence for A's leg.

Preregistration: docs/experiments/EXP-027_PREREGISTRATION.md

Generalises EXP-010's revision-momentum extraction from net profit to
three forecast lines (Sales / OP / NP), using the same forecast-selection
rule and the same trailing 90-calendar-day window. Per disclosure step,
the step score is the sum of the three lines' revision signs, except
that when NP and OP move in opposite directions both are cancelled
(coherence rule), leaving only the Sales sign. A_br replaces A's
NP-only leg with the breadth leg: A_br = (comp_r + breadth_r) / 2.
Judged against A (recomputed; S also reported) by the standard three
criteria.

Usage:
    python experiments/exp027_breadth.py <cache_dir>
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
# (current-FY field, next-FY field); note the irregular NP spelling
LINES = {"sales": ("FSales", "NxFSales"), "op": ("FOP", "NxFOP"),
         "np": ("FNP", "NxFNp")}


def _line_value(r: dict, fields: tuple[str, str]) -> float:
    if r.get("CurPerType") == "FY" and "FinancialStatements" in str(
            r.get("DocType", "")):
        v = r.get(fields[1])
    else:
        v = r.get(fields[0])
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def _records(fins) -> pd.DataFrame:
    rows = []
    for code, r in E10._iter_code_records(fins):
        row = {"code": code, "disc_date": r.get("DiscDate"),
               "disc_time": str(r.get("DiscTime") or "")}
        for k, fields in LINES.items():
            row[k] = _line_value(r, fields)
        rows.append(row)
    df = pd.DataFrame(rows)
    df["disc_date"] = pd.to_datetime(df["disc_date"], errors="coerce")
    df = df.dropna(subset=["disc_date"])
    return df.sort_values(["code", "disc_date", "disc_time"]) \
        .reset_index(drop=True)


def breadth_scores(fins, dates, codes) -> tuple[pd.DataFrame, dict]:
    rec = _records(fins)
    g = rec.groupby("code")
    for k in LINES:
        rec[f"s_{k}"] = np.sign(g[k].diff()).fillna(0.0)
        # a line contributes only when both values exist
        rec.loc[g[k].diff().isna(), f"s_{k}"] = 0.0
    incoherent = (rec["s_np"] * rec["s_op"] < 0)
    rec["step"] = rec["s_sales"] + rec["s_op"] + rec["s_np"]
    rec.loc[incoherent, "step"] = rec.loc[incoherent, "s_sales"]
    steps = rec[rec["step"] != 0].copy()
    diag = {"steps_total": int((rec.groupby('code').cumcount() > 0).sum()),
            "steps_nonzero": int(len(steps)),
            "steps_incoherent_cancelled": int(incoherent.sum())}

    dates = pd.DatetimeIndex(dates)
    out = pd.DataFrame(0.0, index=dates, columns=list(codes))
    dvals = dates.to_numpy()
    lo_vals = dvals - np.timedelta64(WINDOW_DAYS, "D")
    for code, gg in steps.groupby("code"):
        if code not in out.columns:
            continue
        gd = gg["disc_date"].to_numpy()
        gs = gg["step"].to_numpy(dtype=float)
        order = np.argsort(gd, kind="stable")
        gd, gs = gd[order], gs[order]
        cum = np.cumsum(gs)
        hi = np.searchsorted(gd, dvals, side="right") - 1
        lo = np.searchsorted(gd, lo_vals, side="right") - 1
        tot = np.where(hi >= 0, cum[np.clip(hi, 0, len(cum) - 1)], 0.0)
        tot_lo = np.where(lo >= 0, cum[np.clip(lo, 0, len(cum) - 1)], 0.0)
        out[code] = tot - tot_lo
    return out.rank(axis=1, pct=True), diag


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)
    breadth, diag = breadth_scores(fins, dates, codes)

    valid = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    score_a = ((comp_r + mom.where(valid)) / 2.0).where(valid)
    score_br = ((comp_r + breadth.where(valid)) / 2.0).where(valid)

    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    mats = {"S": comp.to_numpy(), "A": score_a.to_numpy(),
            "A_br": score_br.to_numpy()}

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
            res[f"{p}_A_br_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_br_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_br_stress"]["profit"] > 0
            and ratio("full_A_br_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
