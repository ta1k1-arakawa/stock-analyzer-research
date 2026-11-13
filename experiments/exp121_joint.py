"""EXP-121 book test (preregistration pushed first, commit 5f8a5cdf).

EXP-121 (ABD-conditioned challenger, "X"): ABD's large-holding
decrease penalty (EXP-100D: change report, TotalShsRatio -
TotalShsRatioLast <= -0.01, long -0.10 for 120 calendar days from the
trading day after SubDate) RESTRICTED to decrease events accompanied
by on-market disposals, per the AcqDisp descriptive lens
(~/workspace/round12_run/mine_large_acqdisp.py):

  disp_on(filing) := over all Hldrs[].AcqDisp[] entries of the filing,
    disp_r     = sum of Ratio over disposal entries
                 (TxnType "処分" or TxnTypeCode "2"),
    disp_off_r = same restricted to off-market entries
                 (Mkt "市場外" or MktCode "2"),
    disp_on holds iff disp_r >= 0.003 (0.3pt) and
    disp_off_r / disp_r <= 0.2.
  Filings with no AcqDisp entries, or disp_r == 0, fail the condition.
  Decrease events failing the condition get NO penalty (the only
  difference from ABD). Dose -0.10, window 120 calendar days, union
  over events -- all inherited from the EXP-100 implementation
  (exp100_seeds.large_flags window arithmetic verbatim).

Comparator is ABD (base-comparison, round-10 design rule); A is
recorded for reference only.

Faithfulness gates (run invalid unless all match):
- A recomputed in-script must reproduce the current-cache reference
  (FH +970,644 / 0.348 / DD -23.76%; SH +4,133,557 / 1.584 /
  DD -16.91%; full base +6,095,904; full stress +4,357,329 / 0.428);
- ABD recomputed in-script must reproduce the EXP-102 current-cache
  recomputation (FH base +1,041,076 / 0.369 / DD -23.76%; SH base
  +4,586,899 / 1.654 / DD -17.36%; full base +6,941,366 / 0.701;
  full stress +5,047,074 / 0.469).

Flag reconciliation targets (descriptive lens, mine_large_acqdisp):
- disp_on & chg <= -1pt population: 102 events / 29 codes
  (DocType 350 filings WITH AcqDisp entries, any LargeHldgTypeCode);
  its 20d TOPIX-excess mean -7.78% / median -5.51%.

Usage: python exp121_joint.py <cache_dir> <archive_dir> <out_dir>
"""
from __future__ import annotations

import bisect
import glob
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
ABD_REFERENCE = {
    "first_half_ABD_base": {"profit": 1041076, "annual_over_dd": 0.369,
                            "max_dd_pct": -23.76},
    "second_half_ABD_base": {"profit": 4586899, "annual_over_dd": 1.654,
                              "max_dd_pct": -17.36},
    "full_ABD_base": {"profit": 6941366, "annual_over_dd": 0.701},
    "full_ABD_stress": {"profit": 5047074, "annual_over_dd": 0.469},
}

NT, PT, HOLD = E3.N_TRANCHES, E3.PER_TRANCHE, E3.HOLD_DAYS
FH_END, SH_START = "2021-12-30", "2022-01-04"
DOSE = 0.10
WINDOW_DAYS = 120
MINR = 0.003
OFF_SHARE_MAX = 0.2


def disp_on_of(rec: dict) -> tuple[bool, int, float]:
    """Descriptive disp_on definition (mine_large_acqdisp.py verbatim
    aggregation). Returns (disp_on, n_acqdisp_entries, disp_r)."""
    disp_r = 0.0
    disp_off_r = 0.0
    n_entries = 0
    for h in rec.get("Hldrs") or []:
        for e in h.get("AcqDisp") or []:
            n_entries += 1
            try:
                er = float(e.get("Ratio") or 0)
            except (TypeError, ValueError):
                er = 0.0
            off = str(e.get("Mkt") or "") == "市場外" or \
                str(e.get("MktCode") or "") == "2"
            is_disp = str(e.get("TxnType") or "") == "処分" or \
                str(e.get("TxnTypeCode") or "") == "2"
            if is_disp:
                disp_r += er
                if off:
                    disp_off_r += er
    on = disp_r >= MINR and (disp_off_r / disp_r) <= OFF_SHARE_MAX
    return bool(on), n_entries, disp_r


def build_flags(archive: Path, dates, codes):
    """Iterate the large-holding archive once; return flag matrices
    (dec, cond) as float DataFrames over (dates, codes), the event
    ledger, and reconciliation counters. Window arithmetic mirrors
    exp100_seeds.large_flags exactly: trading days d with
    SubDate < d <= SubDate + 120 calendar days."""
    dec = pd.DataFrame(False, index=dates, columns=codes)
    cond = pd.DataFrame(False, index=dates, columns=codes)
    dv = dates.to_numpy()
    code_set = set(codes)
    events: list[dict] = []
    cnt = {"records_total": 0, "records_type2": 0,
           "type2_ratio_missing": 0,
           "decrease_events_archive": 0,
           "decrease_events_universe": 0,
           "conditioned_events_archive": 0,
           "conditioned_events_universe": 0,
           "decrease_with_acqdisp_entries": 0}
    replica_cond: list[dict] = []  # descriptive-population replica
    for f in sorted(glob.glob(str(archive / "large" / "*.json"))):
        fcode = Path(f).stem[:4]
        for d in json.loads(Path(f).read_text()):
            cnt["records_total"] += 1
            code = str(d.get("Code") or fcode)[:4]
            # descriptive replica: DocType 350, AcqDisp entries present,
            # chg computable and <= -0.01, disp_on (any type code)
            if str(d.get("DocTypeCode")) == "350":
                on_r, n_ent, _dr = disp_on_of(d)
                try:
                    chg_r = float(d["TotalShsRatio"]) - \
                        float(d["TotalShsRatioLast"])
                except (TypeError, ValueError, KeyError):
                    chg_r = np.nan
                if n_ent > 0 and np.isfinite(chg_r) and chg_r <= -0.01 \
                        and on_r:
                    replica_cond.append(
                        {"code": code, "sub": d.get("SubDate", ""),
                         "type": str(d.get("LargeHldgTypeCode"))})
            # book construction: ABD events (type 2) + conditioning
            if str(d.get("LargeHldgTypeCode")) != "2":
                continue
            cnt["records_type2"] += 1
            try:
                ratio = float(d.get("TotalShsRatio"))
                chg = ratio - float(d.get("TotalShsRatioLast"))
            except (TypeError, ValueError):
                cnt["type2_ratio_missing"] += 1
                continue
            if not (chg <= -0.01):
                continue
            on, n_ent, dr = disp_on_of(d)
            if n_ent > 0:
                cnt["decrease_with_acqdisp_entries"] += 1
            sub = pd.Timestamp(d["SubDate"])
            in_univ = code in code_set
            cnt["decrease_events_archive"] += 1
            if in_univ:
                cnt["decrease_events_universe"] += 1
            if on:
                cnt["conditioned_events_archive"] += 1
                if in_univ:
                    cnt["conditioned_events_universe"] += 1
            events.append({"code": code, "sub": sub, "chg": chg,
                           "disp_on": bool(on), "n_entries": n_ent,
                           "disp_r": dr, "in_universe": in_univ})
            if not in_univ:
                continue
            ci = dec.columns.get_loc(code)
            lo = np.searchsorted(dv, np.datetime64(sub), side="right")
            hi = np.searchsorted(
                dv, np.datetime64(sub + pd.Timedelta(days=WINDOW_DAYS)),
                side="right")
            if hi > lo:
                dec.iloc[lo:hi, ci] = True
                if on:
                    cond.iloc[lo:hi, ci] = True
    return dec, cond, events, cnt, replica_cond


def long_selection(score: np.ndarray, o: np.ndarray,
                   start: int, end: int):
    """Replicate E9.simulate's long-leg tranche selection (diagnostics
    only; identical to exp119_joint.long_selection)."""
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


def gate_event_study(cache: Path, ev: list[dict], label: str) -> dict:
    """Descriptive-method forward excess (close-to-close from the
    first trading day >= SubDate on per-code AdjC bars vs TOPIX),
    horizons 5/20/60. Reconciliation diagnostic only."""
    bars = {}
    want = {e["code"] for e in ev}
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

    def fwd(code, sub, horizon):
        df = bars.get(code)
        if df is None or len(df) < horizon + 2:
            return np.nan
        dlist = list(df["date"])
        i0 = bisect.bisect_left(dlist, sub)
        if i0 >= len(dlist) or i0 + horizon >= len(dlist):
            return np.nan
        base_d, end_d = dlist[i0], dlist[i0 + horizon]
        if base_d not in t_idx or end_d not in t_idx:
            return np.nan
        return (df["adjc"].iloc[i0 + horizon] / df["adjc"].iloc[i0] - 1.0
                - (tclose[end_d] / tclose[base_d] - 1.0))

    out = {"label": label, "n_events": len(ev)}
    for h in (5, 20, 60):
        vals = pd.Series([fwd(e["code"], e["sub"].strftime("%Y-%m-%d"), h)
                          for e in ev]).dropna()
        out[f"ex{h}"] = {"n": int(len(vals)),
                         "mean_pct": round(float(vals.mean() * 100), 2)
                         if len(vals) else None,
                         "median_pct": round(float(vals.median() * 100), 2)
                         if len(vals) else None}
    return out


def main(cache: Path, archive: Path, out_dir: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    mask = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    score_a = ((comp_r + mom.where(mask)) / 2.0).where(mask)

    dec_df, cond_df, events, cnt, replica_cond = build_flags(
        archive, dates, codes)
    a_np = score_a.to_numpy()
    abd_long = (score_a - DOSE * dec_df.astype(float)).where(mask) \
        .to_numpy()
    x_long = (score_a - DOSE * cond_df.astype(float)).where(mask) \
        .to_numpy()

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    res: dict = {}
    for pname, (a_, b_) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a_)))
        e = int(dates.searchsorted(pd.Timestamp(b_), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(a_np, o, c, s, e, cost, carry, 1.0, 0.5),
                index=idx))
            for vname, ls in (("ABD", abd_long), ("X", x_long)):
                sim = E13.simulate2(ls, a_np, o, c, s, e, cost, carry,
                                    1.0, 0.5)
                res[f"{pname}_{vname}_{cname}"] = E9.stats(
                    pd.Series(np.asarray(sim, dtype=float), index=idx))

    # ---- faithfulness gates ----
    faith_checks = {}
    faithful = True
    for ref_name, ref in (("A", A_REFERENCE), ("ABD", ABD_REFERENCE)):
        for key, rv in ref.items():
            for k, v in rv.items():
                got = res[key][k]
                okk = (got == v)
                faith_checks[f"{key}.{k}"] = {"expected": v, "got": got,
                                              "match": bool(okk)}
                faithful = faithful and okk

    def std_verdict(v, base):
        g = lambda p, k: res[f"{p}_{v}_base"][k]
        bb = lambda p, k: res[f"{p}_{base}_base"][k]
        c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
        c2 = all((g(p, "annual_over_dd") or -9) >
                 (bb(p, "annual_over_dd") or -9)
                 for p in ("first_half", "second_half"))
        gf, bf = res[f"full_{v}_stress"], res[f"full_{base}_stress"]
        c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > \
            (bf["annual_over_dd"] or -9)
        return {"1_profit_positive_both_halves": bool(c1),
                "2_ratio_gt_base_both_halves": bool(c2),
                "3_full_stress_positive_and_ratio_gt_base": bool(c3),
                "promising": bool(c1 and c2 and c3)}

    verdict = std_verdict("X", "ABD") if faithful else None
    verdict_vs_a = std_verdict("X", "A") if faithful else None

    # ---- flag reconciliation ----
    ev_df = pd.DataFrame(events)
    cond_ev = ev_df[ev_df["disp_on"]] if len(ev_df) else ev_df
    dec_ev_in = ev_df[ev_df["in_universe"]] if len(ev_df) else ev_df
    cond_ev_in = cond_ev[cond_ev["in_universe"]] if len(cond_ev) \
        else cond_ev

    def half_counts(df):
        if not len(df):
            return {"FH": 0, "SH": 0, "gap": 0}
        subs = df["sub"].dt.strftime("%Y-%m-%d")
        return {"FH": int((subs <= FH_END).sum()),
                "SH": int((subs >= SH_START).sum()),
                "gap": int(((subs > FH_END) & (subs < SH_START)).sum())}

    replica_by_type = {}
    for t, gcount in pd.DataFrame(replica_cond).groupby("type").size() \
            .items() if replica_cond else []:
        replica_by_type[str(t)] = int(gcount)
    book_cond_keys = {(e["code"], e["sub"].strftime("%Y-%m-%d"))
                      for e in events if e["disp_on"]}
    replica_keys = {(r["code"], r["sub"]) for r in replica_cond}
    recon = {
        "counters": cnt,
        "decrease_events_by_half_archive": half_counts(ev_df),
        "decrease_events_by_half_universe": half_counts(dec_ev_in),
        "conditioned_events_by_half_archive": half_counts(cond_ev),
        "conditioned_events_by_half_universe": half_counts(cond_ev_in),
        "conditioned_codes_universe": int(cond_ev_in["code"].nunique())
        if len(cond_ev_in) else 0,
        "decrease_codes_universe": int(dec_ev_in["code"].nunique())
        if len(dec_ev_in) else 0,
        "descriptive_replica": {
            "definition": "DocType 350 filings with >=1 AcqDisp entry, "
                          "chg computable and <= -0.01, disp_on; any "
                          "LargeHldgTypeCode (mine_large_acqdisp "
                          "population)",
            "n_events": len(replica_cond),
            "n_codes": int(pd.DataFrame(replica_cond)["code"].nunique())
            if replica_cond else 0,
            "by_type_code": replica_by_type,
            "registered_target": "102 events / 29 codes",
            "book_minus_replica_keys": sorted(
                book_cond_keys - replica_keys),
            "replica_minus_book_keys": sorted(
                replica_keys - book_cond_keys),
        },
    }

    # ---- flag state + book diagnostics ----
    dec_np = dec_df.to_numpy()
    cond_np = cond_df.to_numpy()
    per_day_dec = dec_np.sum(axis=1)
    per_day_cond = cond_np.sum(axis=1)
    fh_mask = (dates >= "2017-01-04") & (dates <= FH_END)
    sh_mask = (dates >= SH_START) & (dates <= "2026-09-25")
    s_full = int(dates.searchsorted(pd.Timestamp("2017-01-04")))
    e_full = int(dates.searchsorted(pd.Timestamp("2026-09-25"),
                                    side="right")) - 1
    abd_book, abd_events = long_selection(abd_long, o, s_full, e_full)
    x_book, x_events = long_selection(x_long, o, s_full, e_full)
    cond_full = cond_np[s_full:e_full + 1]
    dec_full = dec_np[s_full:e_full + 1]

    tc = panel["C"].ffill()
    txc = topix["C"]
    x_map = {(t, k): set(v) for t, k, v in x_events}
    changed_events = 0
    swapped_out: list[float] = []   # ABD-only picks (displaced in X)
    swapped_in: list[float] = []    # X-only picks (penalty removed etc.)
    n_swap_pairs = 0
    for t, k, chosen in abd_events:
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
            if t + 20 <= e_full:
                r_s = tc.iloc[t + 20, j] / tc.iloc[t, j] - 1.0
                r_t = txc.iloc[t + 20] / txc.iloc[t] - 1.0
                if np.isfinite(r_s):
                    swapped_in.append(float(r_s - r_t))

    diag = {
        "flag_reconciliation": recon,
        "flag_state": {
            "dec_flagged_name_days": int(dec_np.sum()),
            "cond_flagged_name_days": int(cond_np.sum()),
            "dec_names_median_per_day_all": float(np.median(per_day_dec)),
            "cond_names_median_per_day_all": float(
                np.median(per_day_cond)),
            "cond_names_median_per_day_FH": float(
                np.median(per_day_cond[fh_mask])),
            "cond_names_median_per_day_SH": float(
                np.median(per_day_cond[sh_mask])),
            "cond_names_max_per_day": int(per_day_cond.max()),
        },
        "book_overlap": {
            "cond_flagged_name_days_in_window": int(cond_full.sum()),
            "cond_flagged_in_ABD_book_days": int(
                (cond_full & abd_book).sum()),
            "cond_flagged_in_X_book_days": int(
                (cond_full & x_book).sum()),
            "dec_flagged_in_ABD_book_days": int(
                (dec_full & abd_book).sum()),
            "dec_flagged_in_X_book_days": int((dec_full & x_book).sum()),
        },
        "swap_diagnostics": {
            "method": "Replicated long selection for ABD vs X over the "
                      "full window; rebalance events where the chosen "
                      "pair differs; forward 20-trading-day excess "
                      "(panel close-to-close vs TOPIX) of swapped-out "
                      "(ABD-only) vs swapped-in (X-only) names. "
                      "Descriptive attribution only.",
            "rebalance_events_total": int(len(abd_events)),
            "rebalance_events_changed": int(changed_events),
            "book_name_days_differing": int((abd_book != x_book).sum()),
            "swap_pairs": int(n_swap_pairs),
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
        "gate_event_study_replication": {
            "conditioned_book_events": gate_event_study(
                cache, [e for e in events if e["disp_on"]],
                "book conditioned events (type-2, disp_on)"),
            "all_decrease_book_events": gate_event_study(
                cache, events, "all ABD decrease events (type-2)"),
            "descriptive_reference_conditioned": {
                "n": 102, "ex20_mean_pct": -7.78,
                "ex20_median_pct": -5.51, "ex60_mean_pct": -7.29},
        },
        "ABD_FH": res["first_half_ABD_base"],
        "ABD_SH": res["second_half_ABD_base"],
        "ABD_full_stress": res["full_ABD_stress"],
        "X_FH": res["first_half_X_base"],
        "X_SH": res["second_half_X_base"],
        "X_full_stress": res["full_X_stress"],
        "A_FH": res["first_half_A_base"],
        "A_SH": res["second_half_A_base"],
        "A_full_stress": res["full_A_stress"],
    }

    out = {"faithful": bool(faithful), "faith_checks": faith_checks,
           "res": res, "verdict_vs_ABD": verdict,
           "verdict_vs_A_reference_only": verdict_vs_a, "diag": diag}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({"faithful": bool(faithful),
                      "faith_checks": faith_checks,
                      "verdict_vs_ABD": verdict,
                      "verdict_vs_A_reference_only": verdict_vs_a,
                      "ABD_FH": res["first_half_ABD_base"],
                      "ABD_SH": res["second_half_ABD_base"],
                      "ABD_full_base": res["full_ABD_base"],
                      "ABD_full_stress": res["full_ABD_stress"],
                      "X_FH": res["first_half_X_base"],
                      "X_SH": res["second_half_X_base"],
                      "X_full_base": res["full_X_base"],
                      "X_full_stress": res["full_X_stress"],
                      "A_FH": res["first_half_A_base"],
                      "A_SH": res["second_half_A_base"],
                      "counters": cnt,
                      "diag": diag}, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
