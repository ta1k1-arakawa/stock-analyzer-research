"""EXP-116 book test (preregistration pushed first, commit
96f446e3f2b5825584122b35d937bdbd82276cf1).

EXP-116 (A_gn2): base AGN (= EXP-114's A_pn: A with a -0.10 long-side
penalty on the NP downbeat-guidance flag) with the guidance flag
extended to the union flag (NP flag OR OP flag):

- NP flag: NxFNp <= 0.90 * NP (both positive and non-missing)
- OP flag: NxFOP <= 0.90 * OP (both positive and non-missing)
- union flag: NP flag OR OP flag; a name under both flags still gets
  only -0.10 (no double dose).

FY disclosure identification follows EXP-114 exactly: per
(code, CurFYEn), the last DiscDate row carrying an actual NP defines
the disclosure; NxFNp and NxFOP each fall back to the latest non-null
row in the same group when the adopted row lacks them (the fallback
procedure fixed by EXP-114's run, applied to the OP line as well).
Flag effective from the first trading day AFTER DiscDate for 60
trading days; at the next FY disclosure the flag is re-judged:
qualifying extends it (fresh 60 trading days), non-qualifying expires
it at that disclosure (registered rule; implemented as truncation,
counted in diagnostics). Short side unchanged (EXP-013 simulate2).

Because AGN already applies -0.10 to the NP flag and the union flag
carries a single -0.10, the EXP-116 long score is simply
A score - 0.10 * union_flag. The incremental change vs AGN is exactly
the OP-only flagged names.

Faithfulness: AGN recomputed in-script must reproduce EXP-114's fixed
values (FH +1,016,904 / 0.374 / DD -22.98%; SH +4,104,036 / 1.599;
full stress +4,884,260 / 0.472) or the run is invalid. A is also
recomputed and recorded for reference; the verdict uses the standard
3 criteria vs AGN only.

Diagnostics:
- gate reproduction (NP flag 671; OP flag 428; both 352; OP-only 76;
  NP-only 319; union 747 events / 244 codes, per the preregistration's
  descriptive gate);
- union flag state name counts (median / max per day, 60-day window),
  plus OP-only state counts;
- AGN long-book overlap and the incremental effect of the OP-only
  extension on AGN's selection (changed rebalance events, swapped
  names, forward excess);
- NxFOP fallback impact: disclosures judged via the fallback value
  and flag events that exist only because of it.
- capturability of union-flag events (day 1/5/20/60 forward excess).

Usage: python exp116_joint.py <cache_dir> <out_dir>
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

AGN_REFERENCE = {
    "first_half_AGN_base": {"profit": 1016904, "annual_over_dd": 0.374,
                            "max_dd_pct": -22.98},
    "second_half_AGN_base": {"profit": 4104036, "annual_over_dd": 1.599},
    "full_AGN_stress": {"profit": 4884260, "annual_over_dd": 0.472},
}
A_REFERENCE = {
    "first_half_A_base": {"profit": 970644, "annual_over_dd": 0.348,
                          "max_dd_pct": -23.76},
    "second_half_A_base": {"profit": 4133557, "annual_over_dd": 1.584},
    "full_A_stress": {"annual_over_dd": 0.428},
}
GATE_EXPECT = {
    "np_flag_events": 671, "op_flag_events": 428, "both_events": 352,
    "op_only_events": 76, "np_only_events": 319,
    "union_events": 747, "union_codes": 244, "op_flag_codes": 180,
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


def _growth(nx, cur):
    g = nx / cur.replace(0, np.nan) - 1.0
    return g.where(cur > 0).where(nx > 0)


def build_fy_frame(fins: dict) -> pd.DataFrame:
    """FY disclosures, EXP-114 construction extended to the OP line:
    per (code, CurFYEn) the last DiscDate row with NP present defines
    the disclosure; NxFNp and NxFOP each fall back to the latest
    non-null row in the group when the adopted row lacks them."""
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
                "OP": fnum(r.get("OP")),
                "NxFOP": fnum(r.get("NxFOP")),
            })
    raw = pd.DataFrame(rows)
    n_raw = len(raw)
    d = raw[raw["disc"] != ""].copy().sort_values(["code", "fy_en", "disc"])
    base = d[d["NP"].notna()].groupby(["code", "fy_en"],
                                      as_index=False).tail(1).copy()
    for col in ("NxFNp", "NxFOP"):
        fb = (d[d[col].notna()].groupby(["code", "fy_en"], as_index=False)
              .tail(1)[["code", "fy_en", col]]
              .rename(columns={col: f"{col}_fb"}))
        base = base.merge(fb, on=["code", "fy_en"], how="left")
        base[f"{col}_strict"] = base[col]
        base[f"{col}_via_fb"] = base[col].isna() & base[f"{col}_fb"].notna()
        base[col] = base[col].fillna(base[f"{col}_fb"])
    base = base.sort_values(["code", "disc"]).reset_index(drop=True)
    base["nx_growth"] = _growth(base["NxFNp"], base["NP"])
    base["nx_growth_strict"] = _growth(base["NxFNp_strict"], base["NP"])
    base["op_growth"] = _growth(base["NxFOP"], base["OP"])
    base["op_growth_strict"] = _growth(base["NxFOP_strict"], base["OP"])
    base["np_flag"] = base["nx_growth"] <= -0.10
    base["np_flag_strict"] = base["nx_growth_strict"] <= -0.10
    # OP leg uses the preregistration's literal inequality
    # (NxFOP <= 0.90 * OP, both positive). The ratio-minus-1 form used
    # in the first run misclassifies one exact-boundary event
    # (4240, NxFOP/OP = 0.90 exactly) through float representation;
    # that event is NP-flagged anyway, so the union flag and all P&L
    # are unchanged -- disclosed in EXP-116_RESULTS.md.
    base["op_flag"] = (base["OP"] > 0) & (base["NxFOP"] > 0) \
        & (base["NxFOP"] <= 0.90 * base["OP"])
    base["op_flag_strict"] = (base["OP"] > 0) \
        & (base["NxFOP_strict"] > 0) \
        & (base["NxFOP_strict"] <= 0.90 * base["OP"])
    base["flag"] = base["np_flag"] | base["op_flag"]
    base["flag_strict"] = base["np_flag_strict"] | base["op_flag_strict"]
    base.attrs["n_raw"] = n_raw
    return base


def flag_matrix_registered(dates: pd.DatetimeIndex, codes: list[str],
                           fy: pd.DataFrame,
                           flag_col: str = "flag") -> tuple[np.ndarray, dict]:
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
        for disc, fl in zip(grp["disc"], grp[flag_col]):
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
    out["gate_reference_union"] = {
        "cum_mean_pct": {"h20": -3.91, "h60": -3.45},
        "source": "EXP-116 preregistration descriptive gate "
                  "(mine_nx_guidance2.py)"}
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
    np_flagged, _ = flag_matrix_registered(dates, codes, fy, "np_flag")
    union_flagged, trunc_info = flag_matrix_registered(dates, codes, fy,
                                                       "flag")
    flag_events = fy[fy["flag"]].copy()

    long_a = score_a.to_numpy()
    fin = np.isfinite(long_a)
    long_agn = np.where(np_flagged & fin, long_a - 0.10, long_a)
    long_x = np.where(union_flagged & fin, long_a - 0.10, long_a)

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    res: dict = {}
    for pname, (a_, b_) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a_)))
        e = int(dates.searchsorted(pd.Timestamp(b_), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            for vname, ls in {"A": long_a, "AGN": long_agn,
                              "X": long_x}.items():
                sim = E9.simulate(ls, o, c, s, e, cost, carry, 1.0, 0.5) \
                    if vname == "A" else \
                    E13.simulate2(ls, long_a, o, c, s, e, cost, carry,
                                  1.0, 0.5)
                res[f"{pname}_{vname}_{cname}"] = E9.stats(
                    pd.Series(sim, index=idx))

    # ---- faithfulness gate (vs AGN; A recorded as reference) ----
    def check(reference, label):
        checks, ok_all = {}, True
        for key, ref in reference.items():
            for k, v in ref.items():
                got = res[key][k]
                okk = (got == v)
                checks[f"{key}.{k}"] = {"expected": v, "got": got,
                                        "match": bool(okk)}
                ok_all = ok_all and okk
        return ok_all, checks

    faithful, faith_checks = check(AGN_REFERENCE, "AGN")
    a_faithful, a_faith_checks = check(A_REFERENCE, "A")

    def std_verdict(v, base):
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

    verdict = std_verdict("X", "AGN") if faithful else None
    verdict_vs_a = std_verdict("X", "A") if faithful else None

    # ---- diagnostics ----
    valid_np = mask.to_numpy()
    fh_mask = (dates >= "2017-01-04") & (dates <= FH_END)
    sh_mask = (dates >= SH_START) & (dates <= "2026-09-25")
    s_full = int(dates.searchsorted(pd.Timestamp("2017-01-04")))
    e_full = int(dates.searchsorted(pd.Timestamp("2026-09-25"),
                                    side="right")) - 1

    per_day_u = union_flagged.sum(axis=1)
    per_day_n = np_flagged.sum(axis=1)
    op_only_state = union_flagged & ~np_flagged
    per_day_o = op_only_state.sum(axis=1)

    agn_book, agn_events = long_selection(long_agn, o, s_full, e_full)
    x_book, x_events = long_selection(long_x, o, s_full, e_full)
    union_full = union_flagged[s_full:e_full + 1]
    op_only_full = op_only_state[s_full:e_full + 1]
    both_agn = union_full & agn_book
    both_agn_op = op_only_full & agn_book

    # incremental effect: AGN vs X selection changes; swapped names'
    # forward 20-day excess; involvement of OP-only flagged names
    # (flag state at t-1, the day whose score drives selection at t).
    tc = panel["C"].ffill()
    txc = topix["C"]
    x_map = {(t, k): set(v) for t, k, v in x_events}
    changed_events = 0
    changed_with_op_only = 0
    swapped_out: list[float] = []
    swapped_in: list[float] = []
    swapped_out_op_only: list[float] = []
    n_swap_pairs = 0
    for t, k, chosen in agn_events:
        alt = x_map.get((t, k), set())
        base_set = set(chosen)
        if alt == base_set:
            continue
        changed_events += 1
        diff = base_set ^ alt
        if any(op_only_state[t - 1, j] for j in diff):
            changed_with_op_only += 1
        for j in base_set - alt:
            n_swap_pairs += 1
            ex = np.nan
            if t + 20 <= e_full:
                r_s = tc.iloc[t + 20, j] / tc.iloc[t, j] - 1.0
                r_t = txc.iloc[t + 20] / txc.iloc[t] - 1.0
                if np.isfinite(r_s):
                    ex = float(r_s - r_t)
                    swapped_out.append(ex)
            if op_only_state[t - 1, j]:
                swapped_out_op_only.append((codes[j], str(dates[t].date()),
                                            None if not np.isfinite(ex)
                                            else round(ex * 100, 2)))
        for j in alt - base_set:
            if t + 20 <= e_full:
                r_s = tc.iloc[t + 20, j] / tc.iloc[t, j] - 1.0
                r_t = txc.iloc[t + 20] / txc.iloc[t] - 1.0
                if np.isfinite(r_s):
                    swapped_in.append(float(r_s - r_t))
    book_diff_days = int((agn_book != x_book).sum())

    cap = capturability(cache, flag_events)

    ev = fy
    gate_actual = {
        "np_flag_events": int(ev["np_flag"].sum()),
        "np_flag_codes": int(ev.loc[ev["np_flag"], "code"].nunique()),
        "op_flag_events": int(ev["op_flag"].sum()),
        "op_flag_codes": int(ev.loc[ev["op_flag"], "code"].nunique()),
        "both_events": int((ev["np_flag"] & ev["op_flag"]).sum()),
        "op_only_events": int((ev["op_flag"] & ~ev["np_flag"]).sum()),
        "np_only_events": int((ev["np_flag"] & ~ev["op_flag"]).sum()),
        "union_events": int(ev["flag"].sum()),
        "union_codes": int(ev.loc[ev["flag"], "code"].nunique()),
        "union_FH": int((flag_events["disc"] <= FH_END).sum()),
        "union_SH": int((flag_events["disc"] >= SH_START).sum()),
        "op_only_FH": int(((ev["op_flag"] & ~ev["np_flag"])
                           & (ev["disc"] <= FH_END)).sum()),
        "op_only_SH": int(((ev["op_flag"] & ~ev["np_flag"])
                           & (ev["disc"] >= SH_START)).sum()),
    }

    fb_impact = {
        "nxfop_fallback_used_in_judgement": int(
            (ev["NxFOP_via_fb"] & ev["op_growth"].notna()).sum()),
        "nxfop_fallback_rows_total": int(ev["NxFOP_via_fb"].sum()),
        "op_flag_events_only_via_fallback": int(
            (ev["op_flag"] & ~ev["op_flag_strict"]).sum()),
        "op_flag_events_lost_via_fallback": int(
            (~ev["op_flag"] & ev["op_flag_strict"]).sum()),
        "union_events_only_via_nxfop_fallback": int(
            (ev["flag"] & ~ev["np_flag"] & ~ev["op_flag_strict"]).sum()),
        "union_events_strict_samerow": int(ev["flag_strict"].sum()),
        "union_events_delta_vs_strict": int(
            ev["flag"].sum() - ev["flag_strict"].sum()),
        "nxfnp_fallback_reference": {
            "np_flag_events_gate_construction": int(ev["np_flag"].sum()),
            "np_flag_events_strict_samerow": int(
                ev["np_flag_strict"].sum()),
        },
        "note": "Fallback = adopted FY row lacks NxFOP; the latest "
                "non-null NxFOP row within the same (code, CurFYEn) "
                "group supplies the value (EXP-114 procedure). "
                "'only_via_nxfop_fallback' counts union-flag events "
                "whose OP leg turns on solely because of the filled "
                "value (NP leg off, strict OP leg off).",
    }

    diag = {
        "gate_reproduction": {
            "fy_rows_raw": int(fy.attrs["n_raw"]),
            "fy_dedup_disclosures_with_np": int(len(fy)),
            "codes": int(fy["code"].nunique()),
            "expected_from_preregistration_gate": GATE_EXPECT,
            "actual": gate_actual,
        },
        "nxfop_fallback_impact": fb_impact,
        "flag_state": {
            **trunc_info,
            "union_flagged_name_days_total": int(union_flagged.sum()),
            "union_names_median_per_day": float(np.median(per_day_u)),
            "union_names_mean_per_day": round(float(per_day_u.mean()), 2),
            "union_names_max_per_day": int(per_day_u.max()),
            "union_names_median_per_day_FH": float(
                np.median(per_day_u[fh_mask])),
            "union_names_median_per_day_SH": float(
                np.median(per_day_u[sh_mask])),
            "np_flagged_name_days_total": int(np_flagged.sum()),
            "np_names_median_per_day": float(np.median(per_day_n)),
            "np_names_mean_per_day": round(float(per_day_n.mean()), 2),
            "np_names_max_per_day": int(per_day_n.max()),
            "op_only_name_days_total": int(op_only_state.sum()),
            "op_only_names_median_per_day": float(np.median(per_day_o)),
            "op_only_names_mean_per_day": round(float(per_day_o.mean()), 2),
            "op_only_names_max_per_day": int(per_day_o.max()),
            "union_flagged_valid_name_days": int(
                (union_flagged & valid_np).sum()),
            "union_flagged_share_of_valid_days": round(
                float((union_flagged & valid_np).sum()
                       / valid_np.sum()), 4),
        },
        "agn_long_book_overlap": {
            "method": "tranche selection replicated from E9.simulate "
                      "(full-window phasing from 2017-01-04); AGN book "
                      "= names held long by AGN on that day",
            "agn_book_name_days": int(agn_book.sum()),
            "union_flagged_name_days_in_window": int(union_full.sum()),
            "union_flagged_in_agn_book_days": int(both_agn.sum()),
            "union_flagged_in_agn_book_share": round(
                float(both_agn.sum() / union_full.sum()), 4)
            if union_full.sum() else None,
            "agn_book_union_flagged_share": round(
                float(both_agn.sum() / agn_book.sum()), 4)
            if agn_book.sum() else None,
            "op_only_flagged_in_agn_book_days": int(both_agn_op.sum()),
            "op_only_flagged_in_agn_book_share": round(
                float(both_agn_op.sum() / op_only_full.sum()), 4)
            if op_only_full.sum() else None,
        },
        "incremental_effect_vs_agn": {
            "method": "Replicated long selection for AGN vs EXP-116 "
                      "over the full window; rebalance events where "
                      "the chosen pair differs; forward 20-trading-day "
                      "excess (panel close-to-close vs TOPIX) of "
                      "swapped-out (AGN-only) vs swapped-in (X-only) "
                      "names; OP-only involvement judged by flag state "
                      "at t-1. Descriptive attribution only.",
            "rebalance_events_total": int(len(agn_events)),
            "rebalance_events_changed": int(changed_events),
            "rebalance_events_changed_involving_op_only": int(
                changed_with_op_only),
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
            "swapped_out_op_only_names": swapped_out_op_only,
        },
        "flag_event_distributions": {
            "op_only_op_growth": quantiles(
                ev.loc[ev["op_flag"] & ~ev["np_flag"], "op_growth"]),
            "both_op_growth": quantiles(
                ev.loc[ev["op_flag"] & ev["np_flag"], "op_growth"]),
            "union_nx_growth": quantiles(flag_events["nx_growth"]),
            "union_op_growth": quantiles(flag_events["op_growth"]),
        },
        "capturability": cap,
        "AGN_FH": res["first_half_AGN_base"],
        "AGN_SH": res["second_half_AGN_base"],
        "AGN_full_stress": res["full_AGN_stress"],
        "A_FH": res["first_half_A_base"],
        "A_SH": res["second_half_A_base"],
        "A_full_stress": res["full_A_stress"],
    }

    out = {"faithful": bool(faithful), "faith_checks": faith_checks,
           "a_faithful": bool(a_faithful), "a_faith_checks": a_faith_checks,
           "res": res, "verdict": verdict, "verdict_vs_a_reference": verdict_vs_a,
           "diag": diag}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({"faithful": bool(faithful),
                      "faith_checks": faith_checks,
                      "a_faithful": bool(a_faithful),
                      "verdict_vs_agn": verdict,
                      "verdict_vs_a_reference": verdict_vs_a,
                      "X_FH": res["first_half_X_base"],
                      "X_SH": res["second_half_X_base"],
                      "X_full_base": res["full_X_base"],
                      "X_full_stress": res["full_X_stress"],
                      "AGN_FH": res["first_half_AGN_base"],
                      "AGN_SH": res["second_half_AGN_base"],
                      "AGN_full_stress": res["full_AGN_stress"],
                      "A_FH": res["first_half_A_base"],
                      "A_SH": res["second_half_A_base"],
                      "A_full_stress": res["full_A_stress"],
                      "diag": diag}, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
