"""EXP-010: earnings-momentum leg (np_forecast revision momentum) added to the EXP-009 long-short.

Pre-registration: docs/experiments/EXP-010_PREREGISTRATION.md
Amendment 1: docs/experiments/EXP-010_AMENDMENT_1.md
  - The momentum leg was redefined from "operating-profit YoY acceleration" to
    np_forecast (company earnings-guidance) revision momentum, because the
    cached financial summary has no operating-profit field.
  - Lot rounding stays OFF to match EXP-009 (no rounding exists in EXP-003..009).
Amendment 2: docs/experiments/EXP-010_AMENDMENT_2.md
  - Adapter fix only: _as_records() now maps the RAW J-Quants v2 record
    schema (DiscDate/DiscTime/FNP/NxFNp) via EXP-003's forecast rule.
    No change to the hypothesis, variants, criteria, periods or costs.

Design (incremental test, everything else identical to EXP-009 S):
  - S : EXP-009 long-short on the composite score (B/P rank + forecast ROE rank),
        recomputed here with the same engine for a fair head-to-head.
  - A : composite score + persistent earnings-momentum tilt, same 2-day
        staggered rebalance as EXP-009.
  - B : monthly-rebalance sleeve on the earnings-momentum score alone
        (first trading day of each month; matches a "buy on a fixed monthly day"
        operating rhythm).

Usage:
    python experiments/exp010_earnings_momentum.py <cache_dir>
    # e.g. python experiments/exp010_earnings_momentum.py data/jquants_exp002

ADAPTER NOTES (check these if the script fails in the local environment):
  - E3.load(cache) must return (topix, panel, fins) like in EXP-003/009, with
    panel["O"]/panel["C"] as DataFrames indexed by trading date.
  - `fins` is the dict code -> list of RAW J-Quants v2 records returned by
    E3.load() (fields: DiscDate / DiscTime / DocType / CurPerType / FNP /
    NxFNp). _as_records() maps them to code / disc_date / np_forecast using
    EXP-003's own forecast-selection rule (see Amendment 2).
  - E9.simulate(score, o, c_ff, start, end, cost, carry, long_frac, short_frac)
    and E9.stats(equity_series) are reused unchanged from EXP-009 so that
    variant A and the S baseline run on the identical engine.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3  # noqa: E402
import exp009_long_short as E9  # noqa: E402

BUDGET = 2_000_000
PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
# (one-way trading cost, annual short carry) -- identical to EXP-009
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
N_NAMES = 20          # long top-20 / short bottom-20, like the rule's 20 names
MOM_WINDOW_DAYS = 90  # revision lookback window for the momentum leg


# ----------------------------------------------------------------------------
# earnings-momentum leg (point-in-time, from cached financial summary)
# ----------------------------------------------------------------------------
def _forecast_value(r: dict) -> float:
    """EXP-003's forecast-selection rule, verbatim: NxFNp for FY financial
    statements, FNP otherwise."""
    if r.get("CurPerType") == "FY" and "FinancialStatements" in str(r.get("DocType", "")):
        v = r.get("NxFNp")
    else:
        v = r.get("FNP")
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def _iter_code_records(fins):
    """Yield (code, raw record) pairs from the shapes E3.load() can return."""
    if isinstance(fins, dict):
        for code, recs in fins.items():
            for r in recs:
                yield str(code), r
    elif isinstance(fins, pd.DataFrame):
        for _, row in fins.iterrows():
            r = row.to_dict()
            yield str(r.get("Code", r.get("code"))), r
    else:  # list of dicts
        for r in fins:
            yield str(r.get("Code", r.get("code"))), r


def _as_records(fins) -> pd.DataFrame:
    """Normalize the cached financial summary to code/disc_date/np_forecast rows.

    The cache holds RAW J-Quants v2 records (DiscDate / DiscTime / DocType /
    CurPerType / FNP / NxFNp), not the normalized free-data schema. Rows are
    ordered by (code, DiscDate, DiscTime) — EXP-003's own ordering — so that
    consecutive-disclosure diffs in revision_momentum_scores() compare the
    same forecast series EXP-003 uses.
    """
    rows = []
    for code, r in _iter_code_records(fins):
        rows.append({
            "code": code,
            "disc_date": r.get("DiscDate"),
            "disc_time": str(r.get("DiscTime") or ""),
            "np_forecast": _forecast_value(r),
        })
    df = pd.DataFrame(rows)
    df["disc_date"] = pd.to_datetime(df["disc_date"], errors="coerce")
    out = df[["code", "disc_date", "disc_time", "np_forecast"]].dropna(
        subset=["disc_date", "np_forecast"])
    return out.sort_values(["code", "disc_date", "disc_time"]).reset_index(drop=True)


def revision_momentum_scores(fins, dates, codes) -> pd.DataFrame:
    """Net upward-revision momentum per (date, stock), cross-sectionally ranked.

    For each stock, revision sign = sign(np_forecast - previous np_forecast of
    the same stock), dated at disc_date (point-in-time: no look-ahead).
    Score at date d = sum of signs of disclosures with
    disc_date in (d - 90 days, d]. Ranked to [0, 1] each day; 0.5 = neutral.
    """
    rec = _as_records(fins)
    rec["rev_sign"] = np.sign(rec.groupby("code")["np_forecast"].diff())
    rev = rec[rec["rev_sign"] != 0].copy()  # drop first disclosure / unchanged
    dates = pd.DatetimeIndex(dates)
    mom = pd.DataFrame(0.0, index=dates, columns=list(codes))
    if rev.empty:
        return mom.rank(axis=1, pct=True)

    dvals = dates.to_numpy()
    lo_vals = dvals - np.timedelta64(MOM_WINDOW_DAYS, "D")
    for code, g in rev.groupby("code"):
        if code not in mom.columns:
            continue
        gd = g["disc_date"].to_numpy()
        gs = g["rev_sign"].to_numpy(dtype=float)
        order = np.argsort(gd, kind="stable")
        gd, gs = gd[order], gs[order]
        cum = np.cumsum(gs)
        hi = np.searchsorted(gd, dvals, side="right") - 1
        lo = np.searchsorted(gd, lo_vals, side="right") - 1
        tot = np.where(hi >= 0, cum[np.clip(hi, 0, len(cum) - 1)], 0.0)
        tot_lo = np.where(lo >= 0, cum[np.clip(lo, 0, len(cum) - 1)], 0.0)
        mom[code] = tot - tot_lo
    return mom.rank(axis=1, pct=True)


# ----------------------------------------------------------------------------
# variant B: monthly-rebalance sleeve on the momentum score alone
# ----------------------------------------------------------------------------
def simulate_monthly(mom, o, c_ff, dates, start, end, cost, carry, n_names=N_NAMES):
    """Single-tranche monthly sleeve. Rebalance on the first trading day of each
    month: close everything at the open, rank the momentum score, long the top
    n_names / short the bottom n_names, equal weight. Long notional = BUDGET,
    short notional = 0.5 * BUDGET (same fractions as EXP-009 LS).

    Returns a numpy array of daily equity values over [start, end].
    """
    dates = pd.DatetimeIndex(dates)
    s = int(dates.searchsorted(pd.Timestamp(start)))
    e = int(dates.searchsorted(pd.Timestamp(end), side="right")) - 1
    n = len(dates)

    first_of_month = {}
    for t in range(s, e + 1):
        key = (dates[t].year, dates[t].month)
        if key not in first_of_month:
            first_of_month[key] = t
    reb = set(first_of_month.values())

    equity = np.full(n, np.nan)
    cash = float(BUDGET)
    longs: dict[int, float] = {}          # stock idx -> shares
    shorts: dict[int, tuple] = {}         # stock idx -> (shares, entry_price)
    carry_d = carry / 252.0

    for t in range(s, e + 1):
        if t in reb:
            # close everything at the open ("寄成")
            for j, sh in longs.items():
                px = o[t, j]
                if px > 0 and np.isfinite(px):
                    cash += sh * px * (1.0 - cost)
            longs = {}
            for j, (sh, _ep) in shorts.items():
                px = o[t, j]
                if px > 0 and np.isfinite(px):
                    cash -= sh * px * (1.0 + cost)  # buy to cover
            shorts = {}
            # rank momentum cross-sectionally
            row = mom[t]
            valid = np.isfinite(row) & np.isfinite(o[t]) & (o[t] > 0)
            vidx = np.flatnonzero(valid)
            if len(vidx) >= 2 * n_names:
                r = np.argsort(np.argsort(row[vidx], kind="stable"), kind="stable")
                top = vidx[r >= len(vidx) - n_names]
                bot = vidx[r < n_names]
                for j in top:
                    px = o[t, j]
                    notional = BUDGET / n_names
                    sh = notional / (px * (1.0 + cost))
                    longs[j] = sh
                    cash -= notional
                for j in bot:
                    px = o[t, j]
                    notional = 0.5 * BUDGET / n_names
                    sh = notional / px
                    shorts[j] = (sh, px)
                    cash += sh * px * (1.0 - cost)
        # mark to market at the close
        lv = sum(sh * c_ff[t, j] for j, sh in longs.items()
                 if np.isfinite(c_ff[t, j]))
        sv = sum(sh * (ep - c_ff[t, j]) for j, (sh, ep) in shorts.items()
                 if np.isfinite(c_ff[t, j]))
        # daily short-carry accrual on entry notional
        cash -= sum(sh * ep * carry_d for _j, (sh, ep) in shorts.items())
        equity[t] = cash + lv + sv
    return equity[s : e + 1]


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main(cache: Path) -> None:
    if not (cache / "topix.json").exists():
        raise SystemExit(f"cache not found: {cache} (expected topix.json inside)")
    topix, panel, fins = E3.load(cache)
    dates = topix.index

    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = revision_momentum_scores(fins, dates, codes)

    mask = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    mom_r = mom.where(mask)
    score_a = ((comp_r + mom_r) / 2.0).where(mask)  # variant A: persistent tilt

    score = comp.to_numpy()
    score_a_np = score_a.to_numpy()
    mom_np = mom.where(mask).to_numpy()
    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start : end + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(
                pd.Series(E9.simulate(score, o, c, start, end, cost, carry, 1.0, 0.5), index=idx)
            )
            res[f"{pname}_A_{cname}"] = E9.stats(
                pd.Series(E9.simulate(score_a_np, o, c, start, end, cost, carry, 1.0, 0.5), index=idx)
            )
            res[f"{pname}_B_{cname}"] = E9.stats(
                pd.Series(simulate_monthly(mom_np, o, c, dates, a, b, cost, carry), index=idx)
            )

    def verdict() -> dict:
        out = {}
        for v in ("A", "B"):
            g = lambda p, k: res[f"{p}_{v}_base"][k]  # noqa: E731
            s = lambda p, k: res[f"{p}_S_base"][k]  # noqa: E731
            c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
            c2 = all((g(p, "annual_over_dd") or -9) > (s(p, "annual_over_dd") or -9)
                     for p in ("first_half", "second_half"))
            gf, sf = res[f"full_{v}_stress"], res["full_S_stress"]
            c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > (sf["annual_over_dd"] or -9)
            out[v] = {
                "1_profit_positive_both_halves": bool(c1),
                "2_ratio_gt_S_both_halves": bool(c2),
                "3_full_stress_positive_and_ratio_gt_S": bool(c3),
                "promising": bool(c1 and c2 and c3),
            }
        return out

    print(json.dumps({"res": res, "verdict": verdict()}, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
