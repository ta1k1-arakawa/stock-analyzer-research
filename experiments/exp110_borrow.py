"""EXP-110 book test (preregistration pushed first, commit 1cc540c2).

EXP-110 (A_brw): A with long-side exclusion of names flagged by a
borrowed-share (BrwList) entry in a large-holding CHANGE report
(DocTypeCode "350"). Correction reports (360) excluded. Flag effective
from the first trading day AFTER SubDate, for 60 trading days; a newer
qualifying filing restarts the 60-trading-day window (union of
[eff, eff+60bd) intervals). Short side unchanged (EXP-013 simulate2).

S and A are recomputed in-script; A must reproduce the current-cache
reference (FH +970,644 / 0.348 / DD -23.76%; SH +4,133,557 / 1.584;
full stress ratio 0.428) or the run is invalid.

Overlap quantification (preregistration requirement):
- borrow flag vs EXP-100D decrease flag (type-2, TotalShsRatio
  decrease >= 0.01, 120 calendar days from the trading day after
  SubDate) -- filing-level and flag-day-level;
- borrow flag vs EXP-052 activist flag (type-1, or type-2 with
  >= 1pt increase, holder ImpProp present per the EXP-052 rule,
  120 calendar days) -- flag-day-level.

Usage: python exp110_borrow.py <cache_dir> <archive_dir> <out_dir>
Archive dir is ~/workspace/cache/edinet_archive (contains large/).
"""
from __future__ import annotations

import json
import re
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

NONE_PAT = re.compile(r"(該当|記載)(事項)?(なし|無し|はありません|ございません)")


def impprop_present(h) -> bool:
    v = h.get("ImpProp")
    return isinstance(v, str) and bool(v.strip()) \
        and not NONE_PAT.search(v)


def load_archive(archive: Path, codes: list[str]):
    """Return per-code lists of filings (dicts) restricted to universe codes."""
    code_set = set(codes)
    filings: dict[str, list] = {}
    n_files = 0
    for fp in sorted((archive / "large").glob("*.json")):
        code = fp.stem
        if code not in code_set:
            continue
        n_files += 1
        filings[code] = json.loads(fp.read_text())
    return filings, n_files


def borrow_events(filings: dict) -> dict[str, list]:
    """code -> sorted SubDates of DocTypeCode '350' filings with at least
    one holder whose BrwList is non-empty."""
    out: dict[str, list] = {}
    for code, recs in filings.items():
        subs = []
        for d in recs:
            if str(d.get("DocTypeCode")) != "350":
                continue
            if any((h.get("BrwList") or []) for h in (d.get("Hldrs") or [])):
                subs.append(pd.Timestamp(d["SubDate"]))
        if subs:
            out[code] = sorted(subs)
    return out


def flag_matrix_60bd(dates: pd.DatetimeIndex, codes: list[str],
                     events: dict[str, list]) -> np.ndarray:
    """bool (T, N): True from the first trading day after SubDate for
    60 trading days (union over events; a newer event restarts)."""
    T, N = len(dates), len(codes)
    flagged = np.zeros((T, N), dtype=bool)
    for j, code in enumerate(codes):
        for sub in events.get(code, []):
            eff = int(dates.searchsorted(sub, side="right"))
            if eff < T:
                flagged[eff:min(eff + 60, T), j] = True
    return flagged


def flag_matrix_120cal(dates: pd.DatetimeIndex, codes: list[str],
                       events: dict[str, list]) -> np.ndarray:
    """bool (T, N): True from the first trading day after SubDate for
    120 calendar days (EXP-052 / EXP-100D convention)."""
    T, N = len(dates), len(codes)
    flagged = np.zeros((T, N), dtype=bool)
    dv = dates.to_numpy()
    for j, code in enumerate(codes):
        for sub in events.get(code, []):
            lo = int(np.searchsorted(dv, np.datetime64(sub), side="right"))
            hi = int(np.searchsorted(
                dv, np.datetime64(sub + pd.Timedelta(days=120)),
                side="right"))
            if hi > lo:
                flagged[lo:hi, j] = True
    return flagged


def decrease_events(filings: dict) -> dict[str, list]:
    """EXP-100D: type-2 filings (LargeHldgTypeCode '2') with
    TotalShsRatio - TotalShsRatioLast <= -0.01."""
    out: dict[str, list] = {}
    for code, recs in filings.items():
        subs = []
        for d in recs:
            if str(d.get("LargeHldgTypeCode")) != "2":
                continue
            try:
                inc = float(d.get("TotalShsRatio")) - \
                    float(d.get("TotalShsRatioLast"))
            except (TypeError, ValueError):
                continue
            if inc <= -0.01:
                subs.append(pd.Timestamp(d["SubDate"]))
        if subs:
            out[code] = sorted(subs)
    return out


def activist_events(filings: dict) -> dict[str, list]:
    """EXP-052: type-1, or type-2 with >= 1pt increase, with at least
    one holder whose ImpProp is present per the EXP-052 rule."""
    out: dict[str, list] = {}
    for code, recs in filings.items():
        subs = []
        for d in recs:
            t = str(d.get("LargeHldgTypeCode"))
            if t not in ("1", "2"):
                continue
            if not any(impprop_present(h) for h in (d.get("Hldrs") or [])):
                continue
            if t == "2":
                try:
                    if float(d.get("TotalShsRatio")) - \
                            float(d.get("TotalShsRatioLast")) < 0.01:
                        continue
                except (TypeError, ValueError):
                    continue
            subs.append(pd.Timestamp(d["SubDate"]))
        if subs:
            out[code] = sorted(subs)
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

    filings, n_files = load_archive(archive, codes)
    brw_ev = borrow_events(filings)
    flagged = flag_matrix_60bd(dates, codes, brw_ev)

    # --- overlap flags (EXP-100D decrease, EXP-052 activist) ---
    dec_ev = decrease_events(filings)
    act_ev = activist_events(filings)
    dec_flag = flag_matrix_120cal(dates, codes, dec_ev)
    act_flag = flag_matrix_120cal(dates, codes, act_ev)

    long_a = score_a.to_numpy()
    long_brw = long_a.copy()
    long_brw[flagged] = np.nan

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    res: dict = {}
    for pname, (a_, b_) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a_)))
        e = int(dates.searchsorted(pd.Timestamp(b_), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            for vname, (ls, ss) in {"A": (long_a, long_a),
                                    "BRW": (long_brw, long_a)}.items():
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

    verdict = std_verdict("BRW") if faithful else None

    # ---- diagnostics ----
    n_brw_events = sum(len(v) for v in brw_ev.values())
    fh_ev = sum(1 for v in brw_ev.values() for d in v
                if d <= pd.Timestamp("2021-12-30"))
    sh_ev = sum(1 for v in brw_ev.values() for d in v
                if d >= pd.Timestamp("2022-01-04"))
    # filing-level overlap: borrow-350 events that are also decrease events
    dec_set = {(code, d) for code, vs in dec_ev.items() for d in vs}
    brw_set = {(code, d) for code, vs in brw_ev.items() for d in vs}
    brw_and_dec = brw_set & dec_set
    # all-filings BrwList counts (any DocTypeCode) for the prereg note
    n_brw_all = 0
    n_brw_all_dec = 0
    for code, recs in filings.items():
        for d in recs:
            if any((h.get("BrwList") or []) for h in (d.get("Hldrs") or [])):
                n_brw_all += 1
                try:
                    inc = float(d.get("TotalShsRatio")) - \
                        float(d.get("TotalShsRatioLast"))
                except (TypeError, ValueError):
                    inc = None
                if inc is not None and inc <= -0.01:
                    n_brw_all_dec += 1
    # 360 correction filings with BrwList (excluded by registration)
    n_brw_360 = sum(
        1 for recs in filings.values() for d in recs
        if str(d.get("DocTypeCode")) == "360"
        and any((h.get("BrwList") or []) for h in (d.get("Hldrs") or [])))
    # flag-day overlaps (all days + within A-valid name-days)
    valid_np = mask.to_numpy()
    def overlap(a_flag, b_flag, label):
        both = (a_flag & b_flag)
        return {
            label + "_flag_days": int(a_flag.sum()),
            label + "_overlap_days": int(both.sum()),
            label + "_overlap_share_of_a": round(
                float(both.sum() / a_flag.sum()), 4) if a_flag.sum() else None,
            label + "_jaccard": round(
                float(both.sum() / (a_flag | b_flag).sum()), 4)
            if (a_flag | b_flag).sum() else None,
            label + "_overlap_valid_days": int((both & valid_np).sum()),
            label + "_flag_valid_days": int((a_flag & valid_np).sum()),
            label + "_overlap_share_of_a_valid": round(
                float((both & valid_np).sum() / (a_flag & valid_np).sum()), 4)
            if (a_flag & valid_np).sum() else None,
        }
    ov = {}
    ov.update(overlap(flagged, dec_flag, "borrow_vs_decrease"))
    ov.update(overlap(flagged, act_flag, "borrow_vs_activist"))
    # name-level overlap
    brw_codes = set(brw_ev)
    dec_codes = set(dec_ev)
    act_codes = set(act_ev)
    diag = {
        "archive_files_universe": n_files,
        "n_borrow_350_events": n_brw_events,
        "n_borrow_350_events_FH": fh_ev,
        "n_borrow_350_events_SH": sh_ev,
        "n_borrow_350_codes": len(brw_codes),
        "n_borrow_all_doctypes": n_brw_all,
        "n_borrow_all_doctypes_and_decrease": n_brw_all_dec,
        "n_borrow_360_excluded": n_brw_360,
        "n_borrow_350_events_also_decrease": len(brw_and_dec),
        "borrow_350_decrease_share": round(len(brw_and_dec) / n_brw_events, 4)
        if n_brw_events else None,
        "n_decrease_events": sum(len(v) for v in dec_ev.values()),
        "n_decrease_codes": len(dec_codes),
        "n_activist_events": sum(len(v) for v in act_ev.values()),
        "n_activist_codes": len(act_codes),
        "flagged_name_days_total": int(flagged.sum()),
        "flagged_name_days_FH": int(flagged[
            (dates >= "2017-01-04") & (dates <= "2021-12-30")].sum()),
        "flagged_name_days_SH": int(flagged[
            (dates >= "2022-01-04") & (dates <= "2026-09-25")].sum()),
        "flagged_names_median_per_day": float(np.median(flagged.sum(axis=1))),
        "flagged_names_max_per_day": int(flagged.sum(axis=1).max()),
        "codes_borrow_and_decrease": len(brw_codes & dec_codes),
        "codes_borrow_and_activist": len(brw_codes & act_codes),
        "codes_borrow_only": len(brw_codes - dec_codes - act_codes),
        "overlap": ov,
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
                      "BRW_FH": res["first_half_BRW_base"],
                      "BRW_SH": res["second_half_BRW_base"],
                      "BRW_full_base": res["full_BRW_base"],
                      "BRW_full_stress": res["full_BRW_stress"],
                      "A_FH": res["first_half_A_base"],
                      "A_SH": res["second_half_A_base"],
                      "A_full_stress": res["full_A_stress"],
                      "diag": diag}, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
