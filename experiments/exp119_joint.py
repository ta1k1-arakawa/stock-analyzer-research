"""EXP-119 book test (preregistration pushed first, commit ada2c70c).

EXP-119 (A_disc): A with a +0.10 long-side bonus tilt on names flagged
by DISCRETE-quarter (3-month, differenced) NP growth at INTERIM
disclosures only: per (code, FY, quarter type) the last DiscDate row
gives cumulative NP; the discrete quarter NP is the within-FY
difference (1Q = cum1Q, 2Q = cum2Q - cum1Q, 3Q = cum3Q - cum2Q);
g_disc = discrete NP / prior-year same-quarter discrete NP - 1
(defined only when the prior-year discrete NP > 0). Flag if
ptype in {1Q, 2Q, 3Q} and g_disc >= +0.30. FY disclosures never flag.
Flag effective from the first trading day AFTER DiscDate for 60
trading days. Registered validity rule: a later qualifying disclosure
starts a fresh 60-trading-day window; a non-qualifying disclosure does
NOT expire an active flag; no stacking -- with equal-length windows
the union of flag-event windows is exactly "latest window wins", so
the active set is the union. Short side unchanged (EXP-013 simulate2).

Construction ambiguities, resolved BEFORE running per the task
instruction (gate construction primary, EXP-114/118 precedent) and
disclosed in the results document:

1. Row adoption. The preregistration prose says "last DiscDate row
   with NP present" per (code, qtype, fy_en), but its cited mining
   script (round12_run/mine_discrete_q.py) and the audit scripts take
   the last DiscDate row regardless of NP presence (after the
   DocType = FinancialStatements filter and DiscDate/CurFYEn/
   CurPerType presence). The PRIMARY run uses the gate construction
   verbatim (including the DocType filter, which matters: dropping it
   gives 1,919 interim flags). The NP-nonmissing reading is run as
   variant XN with the same standard criteria.

2. Clipping. The preregistration says g_disc outside [-2, +3] is
   treated as missing, parenthetically claiming the flag judgement is
   invariant to the clipping. That claim is FALSE for the
   missing-treatment reading: 281 interim events have g_disc > +3,
   and dropping them cuts the flag count to 1,654, contradicting the
   preregistration's own registered count of 1,935. The gate scripts
   apply NO clipping (equivalently, winsorising to [-2, +3] leaves
   every flag unchanged, since the threshold is +0.30). The PRIMARY
   run therefore uses the gate construction (no missing-treatment),
   which reproduces the registered 1,935 flags exactly; the
   missing-treatment reading is run as variant XC with the same
   standard criteria so the dependence of the verdict on this
   interpretation is disclosed.

S and A are recomputed in-script; A must reproduce the current-cache
reference (FH +970,644 / 0.348 / DD -23.76%; SH +4,133,557 / 1.584 /
DD -16.91%; full base +6,095,904; full stress +4,357,329 / 0.428)
or the run is invalid.

Diagnostics:
- gate reproduction (g_disc coverage 8,409 events / 305 codes, by
  quarter 1Q 2,143 / 2Q 2,098 / 3Q 2,134 / FY 2,034; interim flag
  1,935 events / 292 codes, by quarter 1Q 677 / 2Q 615 / 3Q 643,
  FH 748 / SH 1,187; all-quarter flag 2,552 of which FY 617);
- flagged state name counts (median / max per day, 60-day window);
- overlap with A's long book (replicated tranche selection), plus the
  same share in the tilted book;
- tilt contribution decomposition (selection changes and their
  forward excess);
- capturability: flag events' cumulative forward excess at day
  1 / 5 / 20 / 60 (gate method; gate reference for the interim flag:
  5d +1.67%, 20d +2.41%, 60d +2.30%).

Usage: python exp119_joint.py <cache_dir> <out_dir>
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
    "second_half_A_base": {"profit": 4133557, "annual_over_dd": 1.584,
                            "max_dd_pct": -16.91},
    "full_A_base": {"profit": 6095904},
    "full_A_stress": {"profit": 4357329, "annual_over_dd": 0.428},
}

NT, PT, HOLD = E3.N_TRANCHES, E3.PER_TRANCHE, E3.HOLD_DAYS
FH_END, SH_START = "2021-12-30", "2022-01-04"
ORDER = {"1Q": 1, "2Q": 2, "3Q": 3, "FY": 4}
DOSE = 0.10
WINDOW = 60


def fnum(x):
    try:
        if x is None or x == "":
            return np.nan
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def build_discrete_frame(fins: dict, np_nonmissing: bool = False,
                         clip_missing: bool = False) -> pd.DataFrame:
    """Discrete-quarter event frame, gate construction
    (round12_run/mine_discrete_q.py verbatim): FinancialStatements
    rows with DiscDate/CurFYEn/CurPerType present; per
    (code, fy_en, ptype) the last row by (disc, discno) defines the
    disclosure; discrete NP = within-FY difference of cumulative NP;
    g_disc vs the prior-year same-quarter discrete NP (shift within
    (code, q) in fy_en order), defined only when that base > 0.
    np_nonmissing=True first restricts rows to NP-present ones
    (preregistration-prose variant XN; sensitivity only).
    clip_missing=True drops g_disc outside [-2, +3]
    (preregistration-prose variant XC; sensitivity only)."""
    rows = []
    for code, recs in fins.items():
        for r in recs:
            if "FinancialStatements" not in str(r.get("DocType", "")):
                continue
            if not r.get("DiscDate") or not r.get("CurFYEn") \
                    or not r.get("CurPerType"):
                continue
            rows.append({"code": str(code)[:4], "disc": r["DiscDate"],
                         "discno": r.get("DiscNo", ""),
                         "fy_en": r["CurFYEn"], "ptype": r["CurPerType"],
                         "NP": fnum(r.get("NP"))})
    d = pd.DataFrame(rows)
    if np_nonmissing:
        d = d[d["NP"].notna()].copy()
    d = d.sort_values(["code", "fy_en", "ptype", "disc", "discno"])
    d = d.groupby(["code", "fy_en", "ptype"], as_index=False).tail(1).copy()
    d["q"] = d["ptype"].map(ORDER)
    d = d[d["q"].notna()].copy()
    d["q"] = d["q"].astype(int)
    piv = d.pivot_table(index=["code", "fy_en"], columns="q",
                        values="NP", aggfunc="first")
    piv.columns = [f"cum{c}" for c in piv.columns]
    d = d.merge(piv, on=["code", "fy_en"], how="left")
    for c in (1, 2, 3, 4):
        if f"cum{c}" not in d:
            d[f"cum{c}"] = np.nan
    d["cum_prev"] = np.where(d["q"] == 1, 0.0, np.nan)
    for q in (2, 3, 4):
        d.loc[d["q"] == q, "cum_prev"] = d.loc[d["q"] == q, f"cum{q-1}"]
    d["disc_np"] = d["NP"] - d["cum_prev"]
    d = d.sort_values(["code", "fy_en", "q"]).reset_index(drop=True)
    d["disc_py"] = d.groupby(["code", "q"])["disc_np"].shift(1)
    d["g_disc"] = np.where(d["disc_py"] > 0,
                           d["disc_np"] / d["disc_py"] - 1.0, np.nan)
    if clip_missing:
        d["g_disc"] = d["g_disc"].where(d["g_disc"].between(-2, 3))
    d["flag"] = d["ptype"].isin(["1Q", "2Q", "3Q"]) & (d["g_disc"] >= 0.30)
    d["flag_all"] = d["g_disc"] >= 0.30
    return d


def flag_matrix_union(dates: pd.DatetimeIndex, codes: list[str],
                      ev: pd.DataFrame) -> tuple[np.ndarray, dict]:
    """bool (T, N) + info. Registered EXP-119 rule: each flag event
    sets [eff, eff+60) trading days (eff = first trading day after
    DiscDate); non-qualifying disclosures never truncate and windows
    never stack, so the active set is the union of event windows."""
    T, N = len(dates), len(codes)
    flagged = np.zeros((T, N), dtype=bool)
    cidx = {c_: j for j, c_ in enumerate(codes)}
    fe = ev[ev["flag"]]
    n_window_overlap_events = 0
    for code, disc in zip(fe["code"], fe["disc"]):
        j = cidx.get(str(code)[:4])
        if j is None:
            continue
        eff = int(dates.searchsorted(pd.Timestamp(disc), side="right"))
        if eff >= T:
            continue
        if flagged[eff:min(eff + WINDOW, T), j].any():
            n_window_overlap_events += 1
        flagged[eff:min(eff + WINDOW, T), j] = True
    return flagged, {"events_extending_active_window":
                     n_window_overlap_events}


def long_selection(score: np.ndarray, o: np.ndarray,
                   start: int, end: int):
    """Replicate E9.simulate's long-leg tranche selection (same due
    rule, same held-exclusion). Returns (held bool (T,N) over the
    window, selection events list). Diagnostics only; no P&L here."""
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
    out["gate_reference"] = {
        "cum_mean_pct": {"h5": 1.67, "h20": 2.41, "h60": 2.30},
        "source": "mine_discrete_q_audit2.json interim.disc_up "
                  "(2026-11-12 23:53 run)"}
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

    # ---- flag construction (registered definitions) ----
    ev = build_discrete_frame(fins)
    flagged, union_info = flag_matrix_union(dates, codes, ev)
    flag_events = ev[ev["flag"]].copy()
    ev_n = build_discrete_frame(fins, np_nonmissing=True)
    flagged_n, union_info_n = flag_matrix_union(dates, codes, ev_n)
    flag_events_n = ev_n[ev_n["flag"]].copy()
    ev_c = build_discrete_frame(fins, clip_missing=True)
    flagged_c, union_info_c = flag_matrix_union(dates, codes, ev_c)
    flag_events_c = ev_c[ev_c["flag"]].copy()

    long_a = score_a.to_numpy()
    long_x = np.where(flagged & np.isfinite(long_a), long_a + DOSE, long_a)
    long_xn = np.where(flagged_n & np.isfinite(long_a),
                       long_a + DOSE, long_a)
    long_xc = np.where(flagged_c & np.isfinite(long_a),
                       long_a + DOSE, long_a)

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    res: dict = {}
    for pname, (a_, b_) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a_)))
        e = int(dates.searchsorted(pd.Timestamp(b_), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            for vname, (ls, ss) in {"A": (long_a, long_a),
                                    "X": (long_x, long_a),
                                    "XN": (long_xn, long_a),
                                    "XC": (long_xc, long_a)}.items():
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

    verdict = std_verdict("X") if faithful else None
    verdict_n = std_verdict("XN") if faithful else None
    verdict_c = std_verdict("XC") if faithful else None

    # ---- diagnostics ----
    evg = ev[ev["g_disc"].notna()]
    per_day = flagged.sum(axis=1)
    valid_np = mask.to_numpy()
    fh_mask = (dates >= "2017-01-04") & (dates <= FH_END)
    sh_mask = (dates >= SH_START) & (dates <= "2026-09-25")
    s_full = int(dates.searchsorted(pd.Timestamp("2017-01-04")))
    e_full = int(dates.searchsorted(pd.Timestamp("2026-09-25"),
                                    side="right")) - 1
    a_book, a_events = long_selection(long_a, o, s_full, e_full)
    x_book, x_events = long_selection(long_x, o, s_full, e_full)
    flagged_full = flagged[s_full:e_full + 1]
    both_a = flagged_full & a_book
    both_x = flagged_full & x_book

    # tilt contribution: selection changes at rebalance events and the
    # forward 20-trading-day excess (close-to-close vs TOPIX on the
    # panel calendar) of swapped-out vs swapped-in names.
    tc = panel["C"].ffill()
    txc = topix["C"]
    x_map = {(t, k): set(v) for t, k, v in x_events}
    changed_events = 0
    swapped_out: list[float] = []
    swapped_in: list[float] = []
    swapped_in_flagged = 0
    n_swap_pairs = 0
    flag_lookup = flagged
    for t, k, chosen in a_events:
        alt = x_map.get((t, k), set())
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
            if flag_lookup[t - 1, j]:
                swapped_in_flagged += 1
            if t + 20 <= e_full:
                r_s = tc.iloc[t + 20, j] / tc.iloc[t, j] - 1.0
                r_t = txc.iloc[t + 20] / txc.iloc[t] - 1.0
                if np.isfinite(r_s):
                    swapped_in.append(float(r_s - r_t))
    book_diff_days = int((a_book != x_book).sum())

    cap = capturability(cache, flag_events)

    def keyset(fe):
        return set(zip(fe["code"], fe["ptype"], fe["fy_en"]))

    ks, ks_n, ks_c = keyset(flag_events), keyset(flag_events_n), \
        keyset(flag_events_c)
    fy_flag = ev[ev["ptype"] == "FY"]

    diag = {
        "gate_reproduction": {
            "groups_total": int(len(ev)),
            "g_disc_coverage": int(len(evg)),
            "g_disc_codes": int(evg["code"].nunique()),
            "g_disc_coverage_by_q": {
                str(k): int(v) for k, v in
                evg.groupby("ptype").size().items()},
            "n_flag_interim": int(len(flag_events)),
            "n_flag_codes": int(flag_events["code"].nunique()),
            "n_flag_by_q": {
                str(k): int(v) for k, v in
                flag_events.groupby("ptype").size().items()},
            "n_flag_FH": int((flag_events["disc"] <= FH_END).sum()),
            "n_flag_SH": int((flag_events["disc"] >= SH_START).sum()),
            "n_flag_all_quarters": int(ev["flag_all"].sum()),
            "n_flag_FY_only": int(fy_flag["flag_all"].sum()),
            "note": "Gate targets: coverage 8,409 events / 305 codes "
                    "(1Q 2,143 / 2Q 2,098 / 3Q 2,134 / FY 2,034); "
                    "interim flag 1,935 events / 292 codes (1Q 677 / "
                    "2Q 615 / 3Q 643; FH 748 / SH 1,187); all-quarter "
                    "flag 2,552 of which FY 617 "
                    "(mine_discrete_q_results.json + audit/audit2).",
        },
        "variant_np_nonmissing": {
            "construction": "rows restricted to NP-present before the "
                            "last-DiscDate adoption (preregistration "
                            "prose reading); sensitivity only",
            "n_flag": int(len(flag_events_n)),
            "n_flag_codes": int(flag_events_n["code"].nunique()),
            "extra_events_vs_gate_construction":
                [list(x) for x in sorted(ks_n - ks)],
            "missing_events_vs_gate_construction":
                [list(x) for x in sorted(ks - ks_n)],
            "flag_matrix_identical": bool((flagged_n == flagged).all()),
            "verdict_same_criteria": verdict_n,
            **union_info_n,
        },
        "variant_clip_missing": {
            "construction": "g_disc outside [-2, +3] treated as "
                            "missing before flagging (preregistration "
                            "prose reading); sensitivity only",
            "n_flag": int(len(flag_events_c)),
            "n_flag_codes": int(flag_events_c["code"].nunique()),
            "missing_events_vs_gate_construction":
                [list(x) for x in sorted(ks - ks_c)],
            "verdict_same_criteria": verdict_c,
            **union_info_c,
        },
        "flag_state": {
            **union_info,
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
                      "names held long by A on that day; X book = same "
                      "replication on the tilted score",
            "a_book_name_days": int(a_book.sum()),
            "flagged_name_days_in_window": int(flagged_full.sum()),
            "flagged_in_a_book_days": int(both_a.sum()),
            "flagged_in_a_book_share": round(
                float(both_a.sum() / flagged_full.sum()), 4)
            if flagged_full.sum() else None,
            "a_book_flagged_share": round(
                float(both_a.sum() / a_book.sum()), 4)
            if a_book.sum() else None,
            "flagged_in_x_book_days": int(both_x.sum()),
            "flagged_in_x_book_share": round(
                float(both_x.sum() / flagged_full.sum()), 4)
            if flagged_full.sum() else None,
            "flagged_codes_in_a_book_ever": int(len(
                set(codes[j] for j in np.flatnonzero(
                    (flagged_full & a_book).any(axis=0))))),
            "flagged_codes_total": int(flag_events["code"].nunique()),
        },
        "tilt_contribution": {
            "method": "Replicated long selection for A vs A_disc over "
                      "the full window; rebalance events where the "
                      "chosen pair differs; forward 20-trading-day "
                      "excess (panel close-to-close vs TOPIX) of "
                      "swapped-out (A-only) vs swapped-in (X-only) "
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
            "swapped_in_flagged_at_signal_day": int(swapped_in_flagged),
            "note": "swapped_in_flagged_at_signal_day counts X-only "
                    "picks whose flag was active on the signal day "
                    "(t-1), i.e. names pulled in directly by the bonus.",
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
                      "verdict_variant_np_nonmissing": verdict_n,
                      "verdict_variant_clip_missing": verdict_c,
                      "X_FH": res["first_half_X_base"],
                      "X_SH": res["second_half_X_base"],
                      "X_full_base": res["full_X_base"],
                      "X_full_stress": res["full_X_stress"],
                      "XN_FH": res["first_half_XN_base"],
                      "XN_SH": res["second_half_XN_base"],
                      "XN_full_stress": res["full_XN_stress"],
                      "XC_FH": res["first_half_XC_base"],
                      "XC_SH": res["second_half_XC_base"],
                      "XC_full_stress": res["full_XC_stress"],
                      "A_FH": res["first_half_A_base"],
                      "A_SH": res["second_half_A_base"],
                      "A_full_stress": res["full_A_stress"],
                      "diag": diag}, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
