"""EXP-113 book test (preregistration pushed first, commit f407caaa).

EXP-113 (A_dd): A with the simultaneous downward revision of forecast
annual dividend (FDivAnn) and forecast net profit (FNP) at the same
disclosure EXCLUDED from the long side (EXP-046 shape: the name leaves
the long candidate set and the next-best name takes its place). Flag
effective from the first trading day AFTER DiscDate, for 60 trading
days; a newer qualifying disclosure restarts the 60-trading-day
window (union of [eff, eff+60bd) intervals). Short side unchanged
(EXP-013 simulate2).

Exclusion is implemented by setting the flagged names' long score to
NaN: E13.simulate2 (like E9.simulate) selects longs only from
np.isfinite(long_score), so a flagged name is never picked and the
tranche's cash goes to the next-best names (replacement, EXP-046
handling).

S and A are recomputed in-script; A must reproduce the current-cache
reference (FH +970,644 / 0.348 / DD -23.76%; SH +4,133,557 / 1.584;
full stress ratio 0.428) or the run is invalid.

Diagnostics required by the preregistration:
- flagged state name counts (median / max per day, 60-day window);
- overlap with A's long book (replicated tranche selection);
- per-type results (FY / 2Q / 3Q / 1Q): event counts, flagged
  name-days, flagged-in-A-book share (recorded, NOT used for the
  verdict);
- NP growth distributions: joint-down group vs control group (FNP
  down >=5% & FDivAnn unchanged, audit definition);
- FNP-missing exclusion bias (20 of 92 FDivAnn decreases).

Flag definition cross-check vs the descriptive gate
(mine_div_downside.py): FDivAnn decreases 92, joint-down 65,
control 334. A mismatch would mean the flag construction diverged
and must be investigated before trusting the run.

Usage: python exp113_joint.py <cache_dir> <out_dir>
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

A_REFERENCE = {
    "first_half_A_base": {"profit": 970644, "annual_over_dd": 0.348,
                          "max_dd_pct": -23.76},
    "second_half_A_base": {"profit": 4133557, "annual_over_dd": 1.584},
    "full_A_stress": {"annual_over_dd": 0.428},
}

NT, PT, HOLD = E3.N_TRANCHES, E3.PER_TRANCHE, E3.HOLD_DAYS


def fnum(x):
    try:
        if x is None or x == "":
            return np.nan
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def build_fins_frame(fins: dict) -> pd.DataFrame:
    """Same frame construction as mine_div_downside.py, but built from
    E3.load's fins dict so the book test and the gate share the exact
    same cache."""
    rows = []
    for code, recs in fins.items():
        for r in recs:
            rows.append({
                "code": str(code)[:4],
                "type": r.get("CurPerType", ""),
                "disc": r.get("DiscDate", ""),
                "FDivAnn": fnum(r.get("FDivAnn")),
                "FNP": fnum(r.get("FNP")),
                "NP": fnum(r.get("NP")),
            })
    f = pd.DataFrame(rows)
    f = f[f["disc"] != ""].sort_values(["code", "disc"]).reset_index(drop=True)
    g = f.groupby("code")
    f["prev_fdiv"] = g["FDivAnn"].shift(1)
    f["prev_fnp"] = g["FNP"].shift(1)
    f["d_fdiv"] = f["FDivAnn"] - f["prev_fdiv"]
    f["d_fnp"] = f["FNP"] - f["prev_fnp"]
    f["d_fnp_pct"] = f["d_fnp"] / f["prev_fnp"].abs().replace(0, np.nan)
    # NP growth vs the previous disclosure of the same (code, type):
    # FY vs prior FY, 2Q vs prior 2Q, etc. (year-on-year, same period).
    f["prev_np_same_type"] = f.groupby(["code", "type"])["NP"].shift(1)
    f["np_growth_yoy"] = f["NP"] / f["prev_np_same_type"].replace(0, np.nan) - 1
    return f


def flag_matrix_60bd(dates: pd.DatetimeIndex, codes: list[str],
                     events: dict[str, list]) -> np.ndarray:
    """bool (T, N): True from the first trading day after DiscDate for
    60 trading days (union over events; a newer event restarts)."""
    T, N = len(dates), len(codes)
    flagged = np.zeros((T, N), dtype=bool)
    for j, code in enumerate(codes):
        for sub in events.get(code, []):
            eff = int(dates.searchsorted(sub, side="right"))
            if eff < T:
                flagged[eff:min(eff + 60, T), j] = True
    return flagged


def long_holdings_matrix(score: np.ndarray, o: np.ndarray,
                         start: int, end: int) -> np.ndarray:
    """Replicate E9.simulate's long-leg tranche selection (same due
    rule, same held-exclusion) and return a bool (T, N) matrix of
    names held long by A on each day of the window. Used only for the
    overlap diagnostic; no P&L is computed here."""
    T = end - start + 1
    N = score.shape[1]
    step = HOLD // NT
    longs: list[set] = [set() for _ in range(NT)]
    held_mat = np.zeros((T, N), dtype=bool)
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
        for j in set().union(*longs):
            held_mat[i, j] = True
    return held_mat


def quantiles(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) == 0:
        return {"n": 0}
    return {"n": int(len(s)),
            "mean": round(float(s.mean()), 4),
            "median": round(float(s.median()), 4),
            "p25": round(float(s.quantile(0.25)), 4),
            "p75": round(float(s.quantile(0.75)), 4),
            "p10": round(float(s.quantile(0.10)), 4),
            "p90": round(float(s.quantile(0.90)), 4)}


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
    ff = build_fins_frame(fins)
    joint = ff[(ff["d_fdiv"] < 0) & (ff["d_fnp"] < 0)].copy()
    joint_events: dict[str, list] = {}
    for code, d in zip(joint["code"], joint["disc"]):
        joint_events.setdefault(code, []).append(pd.Timestamp(d))
    for code in joint_events:
        joint_events[code] = sorted(joint_events[code])
    flagged = flag_matrix_60bd(dates, codes, joint_events)

    # control group (audit definition): FNP down >=5% & FDivAnn unchanged
    ctrl = ff[(ff["d_fnp_pct"] <= -0.05) & (ff["d_fdiv"] == 0)].copy()
    fdiv_dec = ff[ff["d_fdiv"] < 0].copy()

    # per-type event dicts for the per-type diagnostics
    type_events: dict[str, dict[str, list]] = {}
    for t in ("FY", "2Q", "3Q", "1Q"):
        sub = joint[joint["type"] == t]
        ev: dict[str, list] = {}
        for code, d in zip(sub["code"], sub["disc"]):
            ev.setdefault(code, []).append(pd.Timestamp(d))
        for code in ev:
            ev[code] = sorted(ev[code])
        type_events[t] = ev

    long_a = score_a.to_numpy()
    # EXCLUSION: flagged names' long score -> NaN (never selected).
    long_ex = np.where(flagged, np.nan, long_a)

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    res: dict = {}
    for pname, (a_, b_) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a_)))
        e = int(dates.searchsorted(pd.Timestamp(b_), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            for vname, (ls, ss) in {"A": (long_a, long_a),
                                    "EX": (long_ex, long_a)}.items():
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

    verdict = std_verdict("EX") if faithful else None

    # ---- diagnostics ----
    n_joint = len(joint)
    fh_ev = int(((joint["disc"] <= "2021-12-30")).sum())
    sh_ev = int(((joint["disc"] >= "2022-01-04")).sum())
    per_day = flagged.sum(axis=1)
    win = (dates >= "2017-01-04") & (dates <= "2026-09-25")
    per_day_win = per_day[win]
    valid_np = mask.to_numpy()
    # A long-book overlap (full-window tranche phasing from 2017-01-04)
    s_full = int(dates.searchsorted(pd.Timestamp("2017-01-04")))
    e_full = int(dates.searchsorted(pd.Timestamp("2026-09-25"),
                                    side="right")) - 1
    a_book = long_holdings_matrix(long_a, o, s_full, e_full)
    flagged_full = flagged[s_full:e_full + 1]
    both = flagged_full & a_book
    # per-type flagged matrices and overlap (recorded, not used for verdict)
    per_type = {}
    for t, ev in type_events.items():
        fm = flag_matrix_60bd(dates, codes, ev)
        fm_full = fm[s_full:e_full + 1]
        both_t = fm_full & a_book
        sub = joint[joint["type"] == t]
        per_type[t] = {
            "n_joint_down_events": int(len(sub)),
            "n_joint_down_codes": int(sub["code"].nunique()),
            "flagged_name_days_total": int(fm.sum()),
            "flagged_name_days_in_window": int(fm_full.sum()),
            "flagged_median_per_day_window": float(
                np.median(fm[win].sum(axis=1))),
            "flagged_max_per_day_window": int(fm[win].sum(axis=1).max()),
            "flagged_in_a_book_days": int(both_t.sum()),
            "flagged_in_a_book_share": round(
                float(both_t.sum() / fm_full.sum()), 4)
            if fm_full.sum() else None,
        }
    # FNP-missing exclusion bias among FDivAnn decreases
    dec_missing_fnp = fdiv_dec[fdiv_dec["d_fnp"].isna()]
    diag = {
        # cross-check vs the descriptive gate (must be 92 / 65 / 334)
        "gate_reproduction": {
            "n_records": int(len(ff)),
            "n_codes": int(ff["code"].nunique()),
            "n_fdiv_decrease": int(len(fdiv_dec)),
            "n_joint_down": int(n_joint),
            "n_joint_down_FH": fh_ev,
            "n_joint_down_SH": sh_ev,
            "n_joint_down_codes": int(joint["code"].nunique()),
            "n_control_fnp_down_ge5pct_fdiv_flat": int(len(ctrl)),
            "n_control_codes": int(ctrl["code"].nunique()),
        },
        "flag_state": {
            "flagged_name_days_total": int(flagged.sum()),
            "flagged_name_days_FH": int(flagged[
                (dates >= "2017-01-04") & (dates <= "2021-12-30")].sum()),
            "flagged_name_days_SH": int(flagged[
                (dates >= "2022-01-04") & (dates <= "2026-09-25")].sum()),
            "flagged_names_median_per_day_all_dates": float(np.median(per_day)),
            "flagged_names_median_per_day_window": float(np.median(per_day_win)),
            "flagged_names_mean_per_day_window": round(float(per_day_win.mean()), 2),
            "flagged_names_max_per_day_window": int(per_day_win.max()),
            "flagged_names_median_per_day_FH": float(np.median(per_day[
                (dates >= "2017-01-04") & (dates <= "2021-12-30")])),
            "flagged_names_median_per_day_SH": float(np.median(per_day[
                (dates >= "2022-01-04") & (dates <= "2026-09-25")])),
            "flagged_days_with_any_flag_window": int((per_day_win > 0).sum()),
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
            "flagged_codes_total": int(len(joint_events)),
        },
        "per_type": per_type,
        "np_growth_distributions": {
            "d_fnp_pct_joint_down": quantiles(joint["d_fnp_pct"]),
            "d_fnp_pct_control": quantiles(ctrl["d_fnp_pct"]),
            "np_growth_yoy_joint_down": quantiles(joint["np_growth_yoy"]),
            "np_growth_yoy_control": quantiles(ctrl["np_growth_yoy"]),
            "note": "d_fnp_pct = (FNP_t - FNP_prev)/|FNP_prev| (audit "
                    "definition). np_growth_yoy = NP_t vs NP of the "
                    "previous disclosure of the same (code, CurPerType) "
                    "(year-on-year, same period type).",
        },
        "fnp_missing_bias": {
            "n_fdiv_decrease": int(len(fdiv_dec)),
            "n_fdiv_decrease_missing_fnp": int(len(dec_missing_fnp)),
            "missing_share": round(float(len(dec_missing_fnp) / len(fdiv_dec)), 4),
            "missing_by_type": dec_missing_fnp["type"].value_counts().to_dict(),
            "joint_down_by_type": joint["type"].value_counts().to_dict(),
            "fdiv_decrease_by_type": fdiv_dec["type"].value_counts().to_dict(),
            "missing_by_era": {
                "FH": int((dec_missing_fnp["disc"] <= "2021-12-30").sum()),
                "SH": int((dec_missing_fnp["disc"] >= "2022-01-04").sum()),
            },
            "joint_down_by_era": {"FH": fh_ev, "SH": sh_ev},
            "missing_reason_split": {
                "fnp_current_missing": int(
                    fdiv_dec["FNP"].isna().sum()),
                "prev_fnp_missing": int(
                    fdiv_dec["prev_fnp"].isna().sum()),
                "prev_fdiv_missing": int(
                    fdiv_dec["prev_fdiv"].isna().sum()),
            },
        },
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
                      "EX_FH": res["first_half_EX_base"],
                      "EX_SH": res["second_half_EX_base"],
                      "EX_full_base": res["full_EX_base"],
                      "EX_full_stress": res["full_EX_stress"],
                      "A_FH": res["first_half_A_base"],
                      "A_SH": res["second_half_A_base"],
                      "A_full_stress": res["full_A_stress"],
                      "diag": diag}, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
