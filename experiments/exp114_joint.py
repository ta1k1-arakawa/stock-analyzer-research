"""EXP-114 book test (preregistration pushed first, commit 0c3b841a).

EXP-114 (A_pn): A with a -0.10 long-side penalty tilt on names flagged
by a downbeat next-year guidance at the FY disclosure: NxFNp <=
0.90 * NP (both NP and NxFNp positive and non-missing). FY disclosure
identification follows the preregistration and the descriptive gate
(mine_nxfnp.py): per (code, CurFYEn), the last DiscDate row carrying an
actual NP defines the disclosure; NxFNp is taken from that row, else
from the latest row in the group that has it (gate construction; the
fallback changes exactly 1 of 671 flag events -- strict same-row gives
670 -- and both counts are reported). Flag effective from the first
trading day AFTER DiscDate for 60 trading days; at the next FY
disclosure the flag is re-judged: qualifying extends it (fresh 60
trading days), non-qualifying expires it at that disclosure (registered
rule; implemented as truncation, counted in diagnostics). Short side
unchanged (EXP-013 simulate2).

The -0.10 penalty is applied to the A score exactly as prior tilts are
applied (score - 0.10 * flagged). No clipping; simulate only uses
ordering.

S and A are recomputed in-script; A must reproduce the current-cache
reference (FH +970,644 / 0.348 / DD -23.76%; SH +4,133,557 / 1.584;
full stress ratio 0.428) or the run is invalid.

Diagnostics required by the preregistration / task:
- gate reproduction (FY rows 4,910; deduped FY disclosures 2,925;
  flag 671 events, FH 311 / SH 360);
- flagged state name counts (median / max per day, 60-day window);
- overlap with A's long book (replicated tranche selection): share of
  flagged name-days already in A's long book (initial occupancy);
- tilt contribution decomposition (book-selection changes caused by
  the penalty and their forward excess, as far as feasible);
- capturability: flag events' cumulative forward excess at day 1 / 5 /
  20 / 60 and paired drifts, set against the book outcome (most of the
  descriptive effect accrues on day 1, before a next-open book can
  enter).

Usage: python exp114_joint.py <cache_dir> <out_dir>
"""
from __future__ import annotations

import bisect
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

A_REFERENCE = {
    "first_half_A_base": {"profit": 970644, "annual_over_dd": 0.348,
                          "max_dd_pct": -23.76},
    "second_half_A_base": {"profit": 4133557, "annual_over_dd": 1.584},
    "full_A_stress": {"annual_over_dd": 0.428},
}

NT, PT, HOLD = E3.N_TRANCHES, E3.PER_TRANCHE, E3.HOLD_DAYS
FH_END, SH_START = "2021-12-30", "2022-01-04"


def fnum(x):
    try:
        if x is None or x == "":
            return np.nan
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def build_fy_frame(fins: dict) -> pd.DataFrame:
    """FY disclosures, gate construction (mine_nxfnp.py): per
    (code, CurFYEn) the last DiscDate row with NP present defines the
    disclosure; NxFNp falls back to the latest non-null NxFNp row in
    the group when the adopted row lacks it."""
    rows = []
    for code, recs in fins.items():
        for r in recs:
            if r.get("CurPerType") != "FY":
                continue
            rows.append({
                "code": str(code)[:4],
                "fy_en": r.get("CurFYEn", ""),
                "disc": r.get("DiscDate", ""),
                "NP": fnum(r.get("NP")),
                "NxFNp": fnum(r.get("NxFNp")),
            })
    raw = pd.DataFrame(rows)
    n_raw = len(raw)
    d = raw[raw["disc"] != ""].copy().sort_values(["code", "fy_en", "disc"])
    base = d[d["NP"].notna()].groupby(["code", "fy_en"],
                                      as_index=False).tail(1).copy()
    nx_latest = (d[d["NxFNp"].notna()].groupby(["code", "fy_en"],
                                              as_index=False)
                 .tail(1)[["code", "fy_en", "NxFNp"]]
                 .rename(columns={"NxFNp": "NxFNp_fb"}))
    base = base.merge(nx_latest, on=["code", "fy_en"], how="left")
    base["NxFNp_strict"] = base["NxFNp"]
    base["NxFNp"] = base["NxFNp"].fillna(base["NxFNp_fb"])
    base = base.sort_values(["code", "disc"]).reset_index(drop=True)
    base["nx_growth"] = base["NxFNp"] / base["NP"].replace(0, np.nan) - 1.0
    base.loc[(base["NP"] <= 0) | (base["NxFNp"] <= 0), "nx_growth"] = np.nan
    base["nx_growth_strict"] = (base["NxFNp_strict"]
                                / base["NP"].replace(0, np.nan) - 1.0)
    base.loc[(base["NP"] <= 0) | (base["NxFNp_strict"] <= 0),
             "nx_growth_strict"] = np.nan
    base["flag"] = base["nx_growth"] <= -0.10
    base["flag_strict"] = base["nx_growth_strict"] <= -0.10
    # consecutive-FY current-year NP growth (mechanism diagnostic)
    base["fy_y"] = pd.to_datetime(base["fy_en"], errors="coerce").dt.year
    g = base.groupby("code")
    consec = base["fy_y"] - g["fy_y"].shift(1) == 1
    base["g_np_yoy"] = base["NP"] / g["NP"].shift(1).replace(0, np.nan) - 1.0
    base.loc[~consec, "g_np_yoy"] = np.nan
    base.attrs["n_raw"] = n_raw
    return base


def flag_matrix_registered(dates: pd.DatetimeIndex, codes: list[str],
                           fy: pd.DataFrame) -> tuple[np.ndarray, dict]:
    """bool (T, N) + info. Per code, FY disclosures are processed in
    DiscDate order: a qualifying disclosure sets the flag for
    [eff, eff+60) trading days (eff = first trading day after
    DiscDate); a non-qualifying FY disclosure expires any active flag
    from its eff (registered re-judgement rule)."""
    T, N = len(dates), len(codes)
    flagged = np.zeros((T, N), dtype=bool)
    cidx = {c_: j for j, c_ in enumerate(codes)}
    trunc_events = 0
    trunc_days = 0
    for code, grp in fy.groupby("code"):
        j = cidx.get(str(code)[:4])
        if j is None:
            continue
        for disc, fl in zip(grp["disc"], grp["flag"]):
            eff = int(dates.searchsorted(pd.Timestamp(disc), side="right"))
            if eff >= T:
                continue
            if fl:
                flagged[eff:min(eff + 60, T), j] = True
            else:
                if flagged[eff:, j].any():
                    trunc_events += 1
                    trunc_days += int(flagged[eff:, j].sum())
                    flagged[eff:, j] = False
    return flagged, {"rejudge_truncation_events": trunc_events,
                     "rejudge_truncation_days_removed": trunc_days}


def long_selection(score: np.ndarray, o: np.ndarray,
                   start: int, end: int):
    """Replicate E9.simulate's long-leg tranche selection (same due
    rule, same held-exclusion). Returns (held bool (T,N) over the
    window, selection events list of (t, tranche, tuple of chosen
    column indices)). Used only for diagnostics; no P&L here."""
    T = end - start + 1
    N = score.shape[1]
    step = HOLD // NT
    longs: list[set] = [set() for _ in range(NT)]
    held_mat = np.zeros((T, N), dtype=bool)
    events = []
    for t in range(start, end + 1):
        i = t - start
        due = range(NT) if i == 0 else ([(i % HOLD) // step]
                                        if i % step == 0 else [])
        s = score[t - 1]
        ok = np.flatnonzero(np.isfinite(s))
        order = ok[np.lexsort((ok, -s[ok]))]
        for k in due:
            held = set().union(*(longs[m] for m in range(NT) if m != k))
            cand = [j for j in order if o[t, j] > 0 and j not in held][:PT]
            longs[k] = set(cand)
            events.append((t, k, tuple(cand)))
        for j in set().union(*longs):
            held_mat[i, j] = True
    return held_mat, events


def quantiles(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0}
    return {"n": int(len(s)),
            "mean": round(float(s.mean()), 4),
            "median": round(float(s.median()), 4),
            "p25": round(float(s.quantile(0.25)), 4),
            "p75": round(float(s.quantile(0.75)), 4)}


def capturability(cache: Path, flag_events: pd.DataFrame) -> dict:
    """Gate-method forward excess vs TOPIX (close-to-close from the
    DiscDate close; per-code AdjC bars; TOPIX close), cumulative at
    day 1/5/20/60 plus paired drifts. Descriptive only."""
    bars = {}
    want = set(flag_events["code"])
    for fp in sorted((cache / "bars").glob("*.json")):
        if fp.stem not in want:
            continue
        recs = json.loads(fp.read_text())
        df = pd.DataFrame([{"date": r["Date"], "adjc": float(r["AdjC"])}
                           for r in recs if r.get("AdjC") is not None])
        bars[fp.stem] = df.sort_values("date").reset_index(drop=True)
    topix = pd.DataFrame(json.loads((cache / "topix.json").read_text()))
    topix = topix.rename(columns={"C": "c"}).sort_values("Date") \
        .reset_index(drop=True)
    tclose = {dd: float(c) for dd, c in zip(topix["Date"], topix["c"])}
    t_idx = {dd: i for i, dd in enumerate(topix["Date"])}

    def fwd_excess(code, disc, horizon):
        df = bars.get(code)
        if df is None or len(df) < horizon + 2:
            return np.nan
        dlist = list(df["date"])
        i0 = bisect.bisect_left(dlist, disc)
        if i0 >= len(dlist) or i0 + horizon >= len(dlist):
            return np.nan
        base_d, end_d = dlist[i0], dlist[i0 + horizon]
        if base_d not in t_idx or end_d not in t_idx:
            return np.nan
        return (df["adjc"].iloc[i0 + horizon] / df["adjc"].iloc[i0] - 1.0
                - (tclose[end_d] / tclose[base_d] - 1.0))

    out: dict = {}
    ex = {}
    for h in (1, 5, 20, 60):
        ex[h] = np.array([fwd_excess(c, dd, h) for c, dd in
                          zip(flag_events["code"], flag_events["disc"])],
                         dtype=float)
        s = pd.Series(ex[h]).dropna()
        out[f"cum_ex{h}"] = {"n": int(len(s)),
                             "mean_pct": round(float(s.mean() * 100), 2),
                             "median_pct": round(float(s.median() * 100), 2)}
    for a, b in ((1, 5), (5, 20), (5, 60), (1, 20)):
        pair = pd.DataFrame({"a": ex[a], "b": ex[b]}).dropna()
        drift = (1 + pair["b"]) / (1 + pair["a"]) - 1
        out[f"paired_drift_{a}_to_{b}"] = {
            "n": int(len(pair)),
            "mean_pp": round(float(drift.mean() * 100), 2),
            "median_pp": round(float(drift.median() * 100), 2)}
    out["gate_horizon_reference_neg_le_-10"] = {
        "cum_mean_pct": {"h1": -2.50, "h5": -3.02, "h20": -3.91,
                         "h60": -3.34},
        "paired_drift_5_to_20_mean_pp": -0.97,
        "paired_drift_5_to_60_mean_pp": -0.39,
        "source": "mine_nxfnp_horizon.json (2026-11-10 19:45 run)"}
    return out


def main(cache: Path, out_dir: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    mask = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    score_a = ((comp_r + mom.where(mask)) / 2.0).where(mask)

    # ---- flag construction (preregistration definition) ----
    fy = build_fy_frame(fins)
    flagged, trunc_info = flag_matrix_registered(dates, codes, fy)
    flag_events = fy[fy["flag"]].copy()

    long_a = score_a.to_numpy()
    long_pn = np.where(flagged & np.isfinite(long_a), long_a - 0.10, long_a)

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    res: dict = {}
    for pname, (a_, b_) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a_)))
        e = int(dates.searchsorted(pd.Timestamp(b_), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            for vname, (ls, ss) in {"A": (long_a, long_a),
                                    "PN": (long_pn, long_a)}.items():
                sim = E9.simulate(ls, o, c, s, e, cost, carry, 1.0, 0.5) \
                    if vname == "A" else \
                    E13.simulate2(ls, ss, o, c, s, e, cost, carry, 1.0, 0.5)
                res[f"{pname}_{vname}_{cname}"] = E9.stats(
                    pd.Series(sim, index=idx))

    # ---- faithfulness gate ----
    faith_checks = {}
    faithful = True
    for key, ref in A_REFERENCE.items():
        for k, v in ref.items():
            got = res[key][k]
            okk = (got == v)
            faith_checks[f"{key}.{k}"] = {"expected": v, "got": got,
                                          "match": bool(okk)}
            faithful = faithful and okk

    def std_verdict(v, base="A"):
        g = lambda p, k: res[f"{p}_{v}_base"][k]
        bb = lambda p, k: res[f"{p}_{base}_base"][k]
        c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
        c2 = all((g(p, "annual_over_dd") or -9) > (bb(p, "annual_over_dd") or -9)
                 for p in ("first_half", "second_half"))
        gf, bf = res[f"full_{v}_stress"], res[f"full_{base}_stress"]
        c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > \
            (bf["annual_over_dd"] or -9)
        return {"1_profit_positive_both_halves": bool(c1),
                "2_ratio_gt_base_both_halves": bool(c2),
                "3_full_stress_positive_and_ratio_gt_base": bool(c3),
                "promising": bool(c1 and c2 and c3)}

    verdict = std_verdict("PN") if faithful else None

    # ---- diagnostics ----
    per_day = flagged.sum(axis=1)
    valid_np = mask.to_numpy()
    fh_mask = (dates >= "2017-01-04") & (dates <= FH_END)
    sh_mask = (dates >= SH_START) & (dates <= "2026-09-25")
    s_full = int(dates.searchsorted(pd.Timestamp("2017-01-04")))
    e_full = int(dates.searchsorted(pd.Timestamp("2026-09-25"),
                                    side="right")) - 1
    a_book, a_events = long_selection(long_a, o, s_full, e_full)
    pn_book, pn_events = long_selection(long_pn, o, s_full, e_full)
    flagged_full = flagged[s_full:e_full + 1]
    both = flagged_full & a_book

    # tilt contribution: selection changes at rebalance events and the
    # forward 20-trading-day excess (close-to-close vs TOPIX on the
    # panel calendar) of swapped-out vs swapped-in names.
    tc = panel["C"].ffill()
    txc = topix["C"]
    pn_map = {(t, k): set(v) for t, k, v in pn_events}
    changed_events = 0
    swapped_out: list[float] = []
    swapped_in: list[float] = []
    n_swap_pairs = 0
    for t, k, chosen in a_events:
        alt = pn_map.get((t, k), set())
        base_set = set(chosen)
        if alt == base_set:
            continue
        changed_events += 1
        for j in base_set - alt:
            n_swap_pairs += 1
            if t + 20 <= e_full:
                r_s = tc.iloc[t + 20, j] / tc.iloc[t, j] - 1.0
                r_t = txc.iloc[t + 20] / txc.iloc[t] - 1.0
                if np.isfinite(r_s):
                    swapped_out.append(float(r_s - r_t))
        for j in alt - base_set:
            if t + 20 <= e_full:
                r_s = tc.iloc[t + 20, j] / tc.iloc[t, j] - 1.0
                r_t = txc.iloc[t + 20] / txc.iloc[t] - 1.0
                if np.isfinite(r_s):
                    swapped_in.append(float(r_s - r_t))
    book_diff_days = int((a_book != pn_book).sum())

    cap = capturability(cache, flag_events)

    diag = {
        "gate_reproduction": {
            "fy_rows_raw": int(fy.attrs["n_raw"]),
            "fy_dedup_disclosures_with_np": int(len(fy)),
            "codes": int(fy["code"].nunique()),
            "nxfnp_nonnull_after_fill": int(fy["NxFNp"].notna().sum()),
            "nx_growth_judgeable": int(fy["nx_growth"].notna().sum()),
            "n_flag_gate_construction": int(fy["flag"].sum()),
            "n_flag_codes_gate_construction": int(
                flag_events["code"].nunique()),
            "n_flag_FH": int((flag_events["disc"] <= FH_END).sum()),
            "n_flag_SH": int((flag_events["disc"] >= SH_START).sum()),
            "n_flag_strict_samerow": int(fy["flag_strict"].sum()),
            "n_flag_codes_strict_samerow": int(
                fy[fy["flag_strict"]]["code"].nunique()),
            "note": "Gate: 671 events / FH 311 / SH 360 reproduce "
                    "exactly under the gate construction (NxFNp "
                    "fallback). Strict same-row gives 670 (one FH "
                    "event, 6189 disc 2016-11-24, lacks NxFNp on the "
                    "adopted row). The preregistration text's '259 "
                    "codes' matches the gate audit's nx_growth<=0 "
                    "group (944 events); the flag group's own code "
                    "count is 238 under both constructions.",
        },
        "flag_state": {
            **trunc_info,
            "flagged_name_days_total": int(flagged.sum()),
            "flagged_name_days_FH_window": int(flagged[fh_mask].sum()),
            "flagged_name_days_SH_window": int(flagged[sh_mask].sum()),
            "flagged_names_median_per_day": float(np.median(per_day)),
            "flagged_names_mean_per_day": round(float(per_day.mean()), 2),
            "flagged_names_max_per_day": int(per_day.max()),
            "flagged_names_median_per_day_FH": float(
                np.median(per_day[fh_mask])),
            "flagged_names_median_per_day_SH": float(
                np.median(per_day[sh_mask])),
            "flagged_valid_name_days": int((flagged & valid_np).sum()),
            "flagged_share_of_valid_days": round(
                float((flagged & valid_np).sum() / valid_np.sum()), 4),
        },
        "a_long_book_overlap": {
            "method": "tranche selection replicated from E9.simulate "
                      "(full-window phasing from 2017-01-04); A book = "
                      "names held long by A on that day",
            "a_book_name_days": int(a_book.sum()),
            "flagged_name_days_in_window": int(flagged_full.sum()),
            "flagged_in_a_book_days": int(both.sum()),
            "flagged_in_a_book_share": round(
                float(both.sum() / flagged_full.sum()), 4)
            if flagged_full.sum() else None,
            "a_book_flagged_share": round(
                float(both.sum() / a_book.sum()), 4)
            if a_book.sum() else None,
            "flagged_codes_in_a_book_ever": int(len(
                set(codes[j] for j in np.flatnonzero(
                    (flagged_full & a_book).any(axis=0))))),
            "flagged_codes_total": int(flag_events["code"].nunique()),
        },
        "tilt_contribution": {
            "method": "Replicated long selection for A vs A_pn over "
                      "the full window; rebalance events where the "
                      "chosen pair differs; forward 20-trading-day "
                      "excess (panel close-to-close vs TOPIX) of "
                      "swapped-out (A-only) vs swapped-in (PN-only) "
                      "names. Descriptive attribution only.",
            "rebalance_events_total": int(len(a_events)),
            "rebalance_events_changed": int(changed_events),
            "book_name_days_differing": book_diff_days,
            "swapped_out_n": int(len(swapped_out)),
            "swapped_out_fwd20_excess_mean_pct": round(
                float(np.mean(swapped_out) * 100), 2) if swapped_out
            else None,
            "swapped_out_fwd20_excess_median_pct": round(
                float(np.median(swapped_out) * 100), 2) if swapped_out
            else None,
            "swapped_in_n": int(len(swapped_in)),
            "swapped_in_fwd20_excess_mean_pct": round(
                float(np.mean(swapped_in) * 100), 2) if swapped_in
            else None,
            "swapped_in_fwd20_excess_median_pct": round(
                float(np.median(swapped_in) * 100), 2) if swapped_in
            else None,
        },
        "flag_event_distributions": {
            "nx_growth_flagged": quantiles(flag_events["nx_growth"]),
            "g_np_yoy_flagged": quantiles(flag_events["g_np_yoy"]),
            "note": "g_np_yoy = current-year NP growth vs the "
                    "previous consecutive FY (mechanism check: the "
                    "flag captures downbeat guidance after a strong "
                    "current year).",
        },
        "capturability": cap,
        "A_FH": res["first_half_A_base"],
        "A_SH": res["second_half_A_base"],
        "A_full_stress": res["full_A_stress"],
    }

    out = {"faithful": bool(faithful), "faith_checks": faith_checks,
           "res": res, "verdict": verdict, "diag": diag}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({"faithful": bool(faithful),
                      "faith_checks": faith_checks,
                      "verdict": verdict,
                      "PN_FH": res["first_half_PN_base"],
                      "PN_SH": res["second_half_PN_base"],
                      "PN_full_base": res["full_PN_base"],
                      "PN_full_stress": res["full_PN_stress"],
                      "A_FH": res["first_half_A_base"],
                      "A_SH": res["second_half_A_base"],
                      "A_full_stress": res["full_A_stress"],
                      "diag": diag}, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
