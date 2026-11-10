"""EXP-117 book test (preregistration pushed first, commit
9ed1104d486624f767b4f8cf9a5cc34e56a22463).

EXP-117 (A_gn3): base AGN (= EXP-114's A_pn: A with a -0.10 long-side
penalty on the full-year NP downbeat-guidance flag) with the guidance
flag extended to the union flag (full-year NP flag OR H1 NP flag):

- NP flag (AGN's existing flag): NxFNp <= 0.90 * NP (both positive
  and non-missing), EXP-114 construction unchanged.
- H1 flag: NxFNp2Q <= 0.90 * H1 NP (both positive and non-missing),
  where H1 NP is the cumulative NP on the 2Q disclosure row of the
  same (code, CurFYEn), taking the row with the last DiscDate.
- extended flag: NP flag OR H1 flag; a name under both flags still
  gets only -0.10 (no double dose, registered).

FY disclosure identification follows EXP-114 exactly: per
(code, CurFYEn), the last DiscDate row carrying an actual NP defines
the disclosure; NxFNp and NxFNp2Q each fall back (per column) to the
latest non-null row in the same group when the adopted row lacks
them (the fallback procedure fixed by EXP-114's run). Flag effective
from the first trading day AFTER the FY DiscDate for 60 trading
days; at the next FY disclosure the flag is re-judged: qualifying
extends it (fresh 60 trading days), non-qualifying expires it at
that disclosure (registered rule; implemented as truncation,
counted in diagnostics). Short side unchanged (EXP-013 simulate2).

Because AGN already applies -0.10 to the NP flag and the extended
flag carries a single -0.10, the EXP-117 long score is simply
A score - 0.10 * extended_flag. The incremental change vs AGN is
exactly the H1-only flagged names.

Faithfulness: AGN recomputed in-script must reproduce EXP-114's
fixed values (FH +1,016,904 / 0.374 / DD -22.98%; SH +4,104,036 /
1.599; full stress +4,884,260 / 0.472) or the run is invalid. A is
also recomputed and recorded for reference; the verdict uses the
standard 3 criteria vs AGN only.

Diagnostics:
- gate reproduction vs the preregistration's descriptive gate
  (mine_nx_h1.py): NP flag 671; H1 flag 597 events / 180 codes;
  NP-and-H1 319; H1-only excl. both full-year flags 260 / 134;
  union (NP or H1) 949; H1 growth measurable 1,335; H1 base
  present 2,797; H1 OP flag 453 (reference only). Note: the gate
  script's fallback took all forecast columns from ONE latest row
  (joint-row variant); the registered construction here is the
  EXP-114 per-column fallback. Both variants are computed and the
  delta reported.
- extended flag state name counts (median / max per day, 60-day
  window), plus H1-only state counts;
- AGN long-book overlap and the incremental effect of the H1-only
  extension on AGN's selection (changed rebalance events, swapped
  names, forward excess);
- NxFNp2Q fallback impact on the H1 flag and the extended flag;
- H1 coverage (share of FY disclosures where the H1 leg is
  judgeable);
- capturability of extended-flag and H1-only events (day 1/5/20/60
  forward excess).

Usage: python exp117_joint.py <cache_dir> <out_dir>
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
    "fy_rows_raw": 4910, "fy_dedup_disclosures_with_np": 2925,
    "codes": 306, "np_flag_events": 671, "op_flag_events": 428,
    "h1_flag_events": 597, "h1_flag_codes": 180,
    "np_and_h1_events": 319, "h1_only_excl_both_events": 260,
    "h1_only_excl_both_codes": 134,
    "union_np_h1_events": 949,
    "h1_growth_measurable": 1335, "h1_base_present": 2797,
    "h1_op_flag_events_reference": 453,
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


def _lit_flag(nx, cur):
    """Literal registered inequality: nx <= 0.90 * cur, both > 0 and
    non-missing (NaN comparisons evaluate False)."""
    return (cur > 0) & (nx > 0) & (nx <= 0.90 * cur)


def build_fy_frame(fins: dict) -> pd.DataFrame:
    """FY disclosures, EXP-114 construction extended to the H1 line:
    per (code, CurFYEn) the last DiscDate row with NP present defines
    the disclosure; NxFNp / NxFOP / NxFNp2Q / NxFOP2Q each fall back
    (per column) to the latest non-null row in the group when the
    adopted row lacks them. H1 base = cumulative NP (and OP) on the
    2Q row of the same (code, CurFYEn) with the last DiscDate (2Q
    rows with NP present and a DiscDate only), gate construction.
    Additionally the gate script's joint-row fallback variant for
    NxFNp2Q is computed (NxFNp2Q_gate) purely as a diagnostic."""
    rows = []
    h1_cand: dict[tuple, list] = {}
    n_raw_nxfnp2q = 0
    for code, recs in fins.items():
        c4 = str(code)[:4]
        for r in recs:
            t = r.get("CurPerType")
            if t == "2Q":
                npv = fnum(r.get("NP"))
                disc = r.get("DiscDate", "")
                if not np.isnan(npv) and disc != "":
                    h1_cand.setdefault((c4, r.get("CurFYEn", "")),
                                       []).append(
                        (disc, npv, fnum(r.get("OP"))))
                continue
            if t != "FY":
                continue
            if not np.isnan(fnum(r.get("NxFNp2Q"))):
                n_raw_nxfnp2q += 1
            rows.append({
                "code": c4,
                "fy_en": r.get("CurFYEn", ""),
                "disc": r.get("DiscDate", ""),
                "NP": fnum(r.get("NP")),
                "NxFNp": fnum(r.get("NxFNp")),
                "OP": fnum(r.get("OP")),
                "NxFOP": fnum(r.get("NxFOP")),
                "NxFNp2Q": fnum(r.get("NxFNp2Q")),
                "NxFOP2Q": fnum(r.get("NxFOP2Q")),
            })
    raw = pd.DataFrame(rows)
    n_raw = len(raw)
    d = raw[raw["disc"] != ""].copy().sort_values(["code", "fy_en", "disc"])
    base = d[d["NP"].notna()].groupby(["code", "fy_en"],
                                      as_index=False).tail(1).copy()
    for col in ("NxFNp", "NxFOP", "NxFNp2Q", "NxFOP2Q"):
        fb = (d[d[col].notna()].groupby(["code", "fy_en"], as_index=False)
              .tail(1)[["code", "fy_en", col]]
              .rename(columns={col: f"{col}_fb"}))
        base = base.merge(fb, on=["code", "fy_en"], how="left")
        base[f"{col}_strict"] = base[col]
        base[f"{col}_via_fb"] = base[col].isna() & base[f"{col}_fb"].notna()
        base[col] = base[col].fillna(base[f"{col}_fb"])
    # gate joint-row variant for NxFNp2Q: value taken from the last
    # row (by DiscDate) carrying any of NxFNp2Q / NxFOP2Q / NxFNp
    anyfc = d[d["NxFNp2Q"].notna() | d["NxFOP2Q"].notna()
              | d["NxFNp"].notna()]
    gfb = (anyfc.groupby(["code", "fy_en"], as_index=False)
           .tail(1)[["code", "fy_en", "NxFNp2Q"]]
           .rename(columns={"NxFNp2Q": "NxFNp2Q_gfb"}))
    base = base.merge(gfb, on=["code", "fy_en"], how="left")
    base["NxFNp2Q_gate"] = base["NxFNp2Q_strict"].fillna(
        base["NxFNp2Q_gfb"])
    # H1 base from 2Q rows: last DiscDate row (gate sorted tuples by
    # (disc, NP, OP); NaN OP is kept out of the sort key here by
    # sorting on (disc, NP) with a stable sort -- reference rows only
    # differ in tie cases).
    h1_rows = []
    for (c4, fy), lst in h1_cand.items():
        lst_sorted = sorted(lst, key=lambda x: (x[0], x[1]))
        disc, npv, opv = lst_sorted[-1]
        h1_rows.append({"code": c4, "fy_en": fy, "h1_np": npv,
                        "h1_op": opv})
    h1df = pd.DataFrame(h1_rows)
    base = base.merge(h1df, on=["code", "fy_en"], how="left")
    base = base.sort_values(["code", "disc"]).reset_index(drop=True)
    base["nx_growth"] = _growth(base["NxFNp"], base["NP"])
    base["nx_growth_strict"] = _growth(base["NxFNp_strict"], base["NP"])
    base["op_growth"] = _growth(base["NxFOP"], base["OP"])
    base["h1_growth"] = _growth(base["NxFNp2Q"], base["h1_np"])
    base["h1_growth_strict"] = _growth(base["NxFNp2Q_strict"],
                                       base["h1_np"])
    base["h1_growth_gate"] = _growth(base["NxFNp2Q_gate"], base["h1_np"])
    base["np_flag"] = base["nx_growth"] <= -0.10
    base["np_flag_strict"] = base["nx_growth_strict"] <= -0.10
    # OP leg (diagnostics / gate audit only) uses the literal
    # inequality, as in EXP-116.
    base["op_flag"] = _lit_flag(base["NxFOP"], base["OP"])
    base["h1_flag"] = _lit_flag(base["NxFNp2Q"], base["h1_np"])
    base["h1_flag_strict"] = _lit_flag(base["NxFNp2Q_strict"],
                                       base["h1_np"])
    base["h1_flag_gate"] = _lit_flag(base["NxFNp2Q_gate"], base["h1_np"])
    base["h1_op_flag"] = _lit_flag(base["NxFOP2Q"], base["h1_op"])
    base["flag"] = base["np_flag"] | base["h1_flag"]
    base["flag_strict"] = base["np_flag_strict"] | base["h1_flag_strict"]
    base.attrs["n_raw"] = n_raw
    base.attrs["n_raw_nxfnp2q"] = n_raw_nxfnp2q
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


def capturability(cache: Path, flag_events: pd.DataFrame,
                    gate_ref: dict) -> dict:
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
    out["gate_reference"] = gate_ref
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
    ext_flagged, trunc_info = flag_matrix_registered(dates, codes, fy,
                                                     "flag")
    flag_events = fy[fy["flag"]].copy()
    h1_only_events = fy[fy["h1_flag"] & ~fy["np_flag"]].copy()

    long_a = score_a.to_numpy()
    fin = np.isfinite(long_a)
    long_agn = np.where(np_flagged & fin, long_a - 0.10, long_a)
    long_x = np.where(ext_flagged & fin, long_a - 0.10, long_a)

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

    per_day_e = ext_flagged.sum(axis=1)
    per_day_n = np_flagged.sum(axis=1)
    h1_only_state = ext_flagged & ~np_flagged
    per_day_h = h1_only_state.sum(axis=1)

    agn_book, agn_events = long_selection(long_agn, o, s_full, e_full)
    x_book, x_events = long_selection(long_x, o, s_full, e_full)
    ext_full = ext_flagged[s_full:e_full + 1]
    h1_only_full = h1_only_state[s_full:e_full + 1]
    both_agn = ext_full & agn_book
    both_agn_h1 = h1_only_full & agn_book

    # incremental effect: AGN vs X selection changes; swapped names'
    # forward 20-day excess; involvement of H1-only flagged names
    # (flag state at t-1, the day whose score drives selection at t).
    tc = panel["C"].ffill()
    txc = topix["C"]
    x_map = {(t, k): set(v) for t, k, v in x_events}
    changed_events = 0
    changed_with_h1_only = 0
    swapped_out: list[float] = []
    swapped_in: list[float] = []
    swapped_out_h1_only: list = []
    n_swap_pairs = 0
    for t, k, chosen in agn_events:
        alt = x_map.get((t, k), set())
        base_set = set(chosen)
        if alt == base_set:
            continue
        changed_events += 1
        diff = base_set ^ alt
        if any(h1_only_state[t - 1, j] for j in diff):
            changed_with_h1_only += 1
        for j in base_set - alt:
            n_swap_pairs += 1
            ex = np.nan
            if t + 20 <= e_full:
                r_s = tc.iloc[t + 20, j] / tc.iloc[t, j] - 1.0
                r_t = txc.iloc[t + 20] / txc.iloc[t] - 1.0
                if np.isfinite(r_s):
                    ex = float(r_s - r_t)
                    swapped_out.append(ex)
            if h1_only_state[t - 1, j]:
                swapped_out_h1_only.append((codes[j], str(dates[t].date()),
                                            None if not np.isfinite(ex)
                                            else round(ex * 100, 2)))
        for j in alt - base_set:
            if t + 20 <= e_full:
                r_s = tc.iloc[t + 20, j] / tc.iloc[t, j] - 1.0
                r_t = txc.iloc[t + 20] / txc.iloc[t] - 1.0
                if np.isfinite(r_s):
                    swapped_in.append(float(r_s - r_t))
    book_diff_days = int((agn_book != x_book).sum())

    cap_ext = capturability(
        cache, flag_events,
        {"source": "EXP-117 preregistration descriptive gate "
                   "(mine_nx_h1.py): H1 flag cum_mean_pct h20 -3.44 / "
                   "h60 -3.11; NP flag per EXP-114 gate h20 -3.91 / "
                   "h60 -3.45 (union itself not event-studied at gate)"})
    cap_h1only = capturability(
        cache, h1_only_events,
        {"cum_mean_pct": {"h20": -2.03, "h60": -1.99},
         "source": "EXP-117 preregistration descriptive gate "
                   "(mine_nx_h1.py), H1 flag excluding the full-year "
                   "NP flag (278 events there; the 260-event variant "
                   "excludes the OP flag as well)"})

    ev = fy
    gate_actual = {
        "np_flag_events": int(ev["np_flag"].sum()),
        "np_flag_codes": int(ev.loc[ev["np_flag"], "code"].nunique()),
        "op_flag_events": int(ev["op_flag"].sum()),
        "h1_flag_events": int(ev["h1_flag"].sum()),
        "h1_flag_codes": int(ev.loc[ev["h1_flag"], "code"].nunique()),
        "h1_flag_events_gate_fallback_variant": int(
            ev["h1_flag_gate"].sum()),
        "np_and_h1_events": int((ev["np_flag"] & ev["h1_flag"]).sum()),
        "h1_only_excl_np_events": int(
            (ev["h1_flag"] & ~ev["np_flag"]).sum()),
        "h1_only_excl_both_events": int(
            (ev["h1_flag"] & ~ev["np_flag"] & ~ev["op_flag"]).sum()),
        "h1_only_excl_both_codes": int(ev.loc[
            ev["h1_flag"] & ~ev["np_flag"] & ~ev["op_flag"],
            "code"].nunique()),
        "union_events": int(ev["flag"].sum()),
        "union_codes": int(ev.loc[ev["flag"], "code"].nunique()),
        "union_FH": int((flag_events["disc"] <= FH_END).sum()),
        "union_SH": int((flag_events["disc"] >= SH_START).sum()),
        "h1_only_FH": int(((ev["h1_flag"] & ~ev["np_flag"])
                           & (ev["disc"] <= FH_END)).sum()),
        "h1_only_SH": int(((ev["h1_flag"] & ~ev["np_flag"])
                           & (ev["disc"] >= SH_START)).sum()),
        "h1_op_flag_events_reference": int(ev["h1_op_flag"].sum()),
    }

    fb_impact = {
        "nxfnp2q_fallback_used_in_judgement": int(
            (ev["NxFNp2Q_via_fb"] & ev["h1_growth"].notna()).sum()),
        "nxfnp2q_fallback_rows_total": int(ev["NxFNp2Q_via_fb"].sum()),
        "h1_flag_events_only_via_fallback": int(
            (ev["h1_flag"] & ~ev["h1_flag_strict"]).sum()),
        "h1_flag_events_lost_via_fallback": int(
            (~ev["h1_flag"] & ev["h1_flag_strict"]).sum()),
        "extended_events_only_via_nxfnp2q_fallback": int(
            (ev["flag"] & ~ev["np_flag"] & ~ev["h1_flag_strict"]).sum()),
        "extended_events_strict_samerow": int(ev["flag_strict"].sum()),
        "extended_events_delta_vs_strict": int(
            ev["flag"].sum() - ev["flag_strict"].sum()),
        "h1_flag_events_gate_fallback_variant": int(
            ev["h1_flag_gate"].sum()),
        "h1_flag_delta_registered_vs_gate_variant": int(
            ev["h1_flag"].sum() - ev["h1_flag_gate"].sum()),
        "nxfnp_fallback_reference": {
            "np_flag_events_gate_construction": int(ev["np_flag"].sum()),
            "np_flag_events_strict_samerow": int(
                ev["np_flag_strict"].sum()),
        },
        "note": "Fallback = adopted FY row lacks NxFNp2Q; the latest "
                "non-null NxFNp2Q row within the same (code, CurFYEn) "
                "group supplies the value (EXP-114 per-column "
                "procedure, as registered). 'only_via_fallback' "
                "counts H1-flag events that turn on solely because "
                "of the filled value (strict same-row H1 leg off). "
                "The gate script (mine_nx_h1.py) used a joint-row "
                "fallback variant; its H1 flag count is reproduced "
                "as 'gate_fallback_variant' for comparison.",
    }

    h1_coverage = {
        "fy_disclosures_total": int(len(ev)),
        "fy_raw_rows_total": int(fy.attrs["n_raw"]),
        "fy_raw_rows_with_nxfnp2q": int(fy.attrs["n_raw_nxfnp2q"]),
        "h1_base_present": int(ev["h1_np"].notna().sum()),
        "h1_base_share": round(
            float(ev["h1_np"].notna().mean()), 4),
        "nxfnp2q_present_strict": int(ev["NxFNp2Q_strict"].notna().sum()),
        "nxfnp2q_present_after_fallback": int(
            ev["NxFNp2Q"].notna().sum()),
        "h1_judgeable_growth_measurable": int(
            ev["h1_growth"].notna().sum()),
        "h1_judgeable_share_of_disclosures": round(
            float(ev["h1_growth"].notna().mean()), 4),
        "h1_judgeable_both_positive": int(
            ((ev["h1_np"] > 0) & (ev["NxFNp2Q"] > 0)).sum()),
        "note": "Judgeable = NxFNp2Q and H1 NP both present (growth "
                "measurable); the flag additionally requires both "
                "strictly positive, counted separately. Disclosures "
                "without an H1 judgement mix 'no H1 forecast' and "
                "'no decline'.",
    }

    diag = {
        "gate_reproduction": {
            "fy_rows_raw": int(fy.attrs["n_raw"]),
            "fy_dedup_disclosures_with_np": int(len(fy)),
            "codes": int(fy["code"].nunique()),
            "expected_from_preregistration_gate": GATE_EXPECT,
            "actual": gate_actual,
        },
        "nxfnp2q_fallback_impact": fb_impact,
        "h1_coverage": h1_coverage,
        "flag_state": {
            **trunc_info,
            "extended_flagged_name_days_total": int(ext_flagged.sum()),
            "extended_names_median_per_day": float(np.median(per_day_e)),
            "extended_names_mean_per_day": round(float(per_day_e.mean()), 2),
            "extended_names_max_per_day": int(per_day_e.max()),
            "extended_names_median_per_day_FH": float(
                np.median(per_day_e[fh_mask])),
            "extended_names_median_per_day_SH": float(
                np.median(per_day_e[sh_mask])),
            "np_flagged_name_days_total": int(np_flagged.sum()),
            "np_names_median_per_day": float(np.median(per_day_n)),
            "np_names_mean_per_day": round(float(per_day_n.mean()), 2),
            "np_names_max_per_day": int(per_day_n.max()),
            "h1_only_name_days_total": int(h1_only_state.sum()),
            "h1_only_names_median_per_day": float(np.median(per_day_h)),
            "h1_only_names_mean_per_day": round(float(per_day_h.mean()), 2),
            "h1_only_names_max_per_day": int(per_day_h.max()),
            "extended_flagged_valid_name_days": int(
                (ext_flagged & valid_np).sum()),
            "extended_flagged_share_of_valid_days": round(
                float((ext_flagged & valid_np).sum()
                       / valid_np.sum()), 4),
        },
        "agn_long_book_overlap": {
            "method": "tranche selection replicated from E9.simulate "
                      "(full-window phasing from 2017-01-04); AGN book "
                      "= names held long by AGN on that day",
            "agn_book_name_days": int(agn_book.sum()),
            "extended_flagged_name_days_in_window": int(ext_full.sum()),
            "extended_flagged_in_agn_book_days": int(both_agn.sum()),
            "extended_flagged_in_agn_book_share": round(
                float(both_agn.sum() / ext_full.sum()), 4)
            if ext_full.sum() else None,
            "agn_book_extended_flagged_share": round(
                float(both_agn.sum() / agn_book.sum()), 4)
            if agn_book.sum() else None,
            "h1_only_flagged_in_agn_book_days": int(both_agn_h1.sum()),
            "h1_only_flagged_in_agn_book_share": round(
                float(both_agn_h1.sum() / h1_only_full.sum()), 4)
            if h1_only_full.sum() else None,
        },
        "incremental_effect_vs_agn": {
            "method": "Replicated long selection for AGN vs EXP-117 "
                      "over the full window; rebalance events where "
                      "the chosen pair differs; forward 20-trading-day "
                      "excess (panel close-to-close vs TOPIX) of "
                      "swapped-out (AGN-only) vs swapped-in (X-only) "
                      "names; H1-only involvement judged by flag state "
                      "at t-1. Descriptive attribution only.",
            "rebalance_events_total": int(len(agn_events)),
            "rebalance_events_changed": int(changed_events),
            "rebalance_events_changed_involving_h1_only": int(
                changed_with_h1_only),
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
            "swapped_out_h1_only_names": swapped_out_h1_only,
        },
        "flag_event_distributions": {
            "h1_only_h1_growth": quantiles(
                ev.loc[ev["h1_flag"] & ~ev["np_flag"], "h1_growth"]),
            "both_h1_growth": quantiles(
                ev.loc[ev["h1_flag"] & ev["np_flag"], "h1_growth"]),
            "extended_nx_growth": quantiles(flag_events["nx_growth"]),
            "extended_h1_growth": quantiles(flag_events["h1_growth"]),
        },
        "capturability_extended": cap_ext,
        "capturability_h1_only": cap_h1only,
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
