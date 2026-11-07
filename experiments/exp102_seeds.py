"""EXP-102: four new seeds in one run (preregistration pushed first).

102A ABD625:   EXP-100D's ABD score, short fraction 0.625.
               Adapted SH-only criteria vs A.
102B AVF625D:  AVF625 long (EXP-100A construction) + ABD decrease
               penalty -0.10; shorts stay AVF625's (AF15, 0.625).
               Adapted SH-only criteria vs AVF625 (its base); vs A
               recorded as observation only.
102C ABDG:     graded decrease penalty (strong >= 3pt -> -0.20,
               weak 1-3pt -> -0.10, strong wins). Adapted vs A.
102D ASH:      habit-on-shorts. Long = A unchanged. Short score =
               (pct-rank of A score + (1 - pct-rank of EXP-080 habit))
               / 2 within A's valid set; habit = clipped raw habit
               during the EXP-080 episode window, 0 elsewhere.
               Standard criteria vs A.

S and A are recomputed in-script and must reproduce the published
values exactly, else the run is invalid. ABD and AVF625 (= EXP-100A's
AVF15625) are recomputed as internal cross-checks vs EXP-100.

Usage: python experiments/exp102_seeds.py <cache_dir> <tdnet_dir> <archive_dir>
"""
from __future__ import annotations

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
PATS = ("決算説明", "説明会", "個人投資家", "中期経営計画")


# ---- EXP-054/090B: voluntary-disclosure increase bonus ----------------
def bonus_matrix(tdnet_dir: Path, dates, codes) -> pd.DataFrame:
    vol: dict[str, list] = {}
    for f in glob.glob(str(tdnet_dir / "*.json")):
        try:
            d = json.loads(Path(f).read_text())
        except Exception:
            continue
        items = d if isinstance(d, list) else d.get("items", [])
        if isinstance(items, dict):
            items = items.get("items", [])
        for it in items or []:
            title = str(it.get("title", ""))
            if any(pat in title for pat in PATS):
                vol.setdefault(str(it.get("code")), []).append(
                    pd.Timestamp(str(it.get("pubdate"))[:10]))
    bonus = pd.DataFrame(False, index=dates, columns=codes)
    dv = dates.to_numpy()
    for code, ds in vol.items():
        if code not in bonus.columns:
            continue
        a = np.sort(np.array(ds, dtype="datetime64[ns]"))
        hi = np.searchsorted(a, dv, side="right")
        mid = np.searchsorted(a, dv - np.timedelta64(365, "D"), side="right")
        lo = np.searchsorted(a, dv - np.timedelta64(730, "D"), side="right")
        bonus[code] = (hi - mid) - (mid - lo) >= 2
    return bonus


# ---- EXP-080/090B: forecast-habit episodes ----------------------------
def num(x):
    try:
        return float(x)
    except Exception:
        return np.nan


def episodes(fins: dict) -> dict:
    out = {}
    for code, recs in fins.items():
        rows = []
        for r in recs:
            d = r.get("DiscDate")
            if not d:
                continue
            is_fy = r.get("CurPerType") == "FY" and \
                "FinancialStatements" in str(r.get("DocType"))
            fv = num(r.get("NxFNp")) if is_fy else num(r.get("FNP"))
            rows.append({"d": pd.Timestamp(d), "t": str(r.get("DiscTime") or ""),
                         "is_fy": is_fy, "fv": fv,
                         "np": num(r.get("NP")), "sales": num(r.get("Sales")),
                         "nx": num(r.get("NxFNp"))})
        rows.sort(key=lambda x: (x["d"], x["t"]))
        biases: list[float] = []
        pending_init = np.nan
        eps = []
        for i, r in enumerate(rows):
            if not r["is_fy"]:
                continue
            if np.isfinite(pending_init) and np.isfinite(r["np"]) and r["np"] != 0:
                b = (pending_init - r["np"]) / abs(r["np"])
                biases.append(float(np.clip(b, -2, 2)))
            pending_init = r["nx"]
            v0 = r["nx"]
            if not np.isfinite(v0) or len(biases) < 2:
                continue
            habit = float(np.mean(biases[-3:]))
            cap = r["d"] + pd.DateOffset(months=3)
            end = cap
            for r2 in rows[i + 1:]:
                if r2["d"] > cap:
                    break
                if np.isfinite(r2["fv"]) and r2["fv"] != v0:
                    end = r2["d"]
                    break
            la = bool(np.isfinite(r["np"]) and r["np"] < 0 and 0 < v0
                      and np.isfinite(r["sales"]) and r["sales"] > 0
                      and v0 < 0.01 * r["sales"])
            eps.append((r["d"], end, habit, la))
        if eps:
            out[code] = eps
    return out


# ---- EXP-098: tiered increase flags; EXP-100D/102C: decrease flags --
def large_flags(archive: Path, dates, codes):
    """Return (strong, weak, decrease_flag, decrease_events, diag,
    dec_strong, dec_weak).

    strong/weak: EXP-098 classification of EXP-088 increase events.
    decrease: type-2 filings with ratio decrease >= 0.01, flag 120 days.
    dec_strong/dec_weak (EXP-102C): decrease >= 0.03 / 0.01 <= dec < 0.03.
    decrease_events: list of (code, SubDate) for the gate's event study.
    """
    strong = pd.DataFrame(False, index=dates, columns=codes)
    weak = pd.DataFrame(False, index=dates, columns=codes)
    dec = pd.DataFrame(False, index=dates, columns=codes)
    dec_strong = pd.DataFrame(False, index=dates, columns=codes)
    dec_weak = pd.DataFrame(False, index=dates, columns=codes)
    dv = dates.to_numpy()
    dec_events: list[tuple[str, pd.Timestamp]] = []
    n_inc = n_dec = n_dec_strong = 0
    for f in glob.glob(str(archive / "large" / "*.json")):
        code = Path(f).stem
        if code not in strong.columns:
            continue
        ci = strong.columns.get_loc(code)
        for d in json.loads(Path(f).read_text()):
            t = str(d.get("LargeHldgTypeCode"))
            if t not in ("1", "2"):
                continue
            try:
                ratio = float(d.get("TotalShsRatio"))
            except (TypeError, ValueError):
                continue
            sub = pd.Timestamp(d["SubDate"])
            lo = np.searchsorted(dv, np.datetime64(sub), side="right")
            hi = np.searchsorted(
                dv, np.datetime64(sub + pd.Timedelta(days=120)),
                side="right")
            if t == "2":
                try:
                    inc = ratio - float(d.get("TotalShsRatioLast"))
                except (TypeError, ValueError):
                    continue
                if inc >= 0.01:
                    n_inc += 1
                    tgt = strong if inc >= 0.03 else weak
                    if hi > lo:
                        tgt.iloc[lo:hi, ci] = True
                elif inc <= -0.01:
                    n_dec += 1
                    dec_events.append((code, sub))
                    if inc <= -0.03:
                        n_dec_strong += 1
                        tgt_d = dec_strong
                    else:
                        tgt_d = dec_weak
                    if hi > lo:
                        dec.iloc[lo:hi, ci] = True
                        tgt_d.iloc[lo:hi, ci] = True
            else:  # type 1
                n_inc += 1
                tgt = strong if ratio >= 0.10 else weak
                if hi > lo:
                    tgt.iloc[lo:hi, ci] = True
    weak = weak & ~strong
    dec_weak = dec_weak & ~dec_strong
    diag = {"n_increase_events": n_inc, "n_decrease_events": n_dec,
            "n_decrease_strong_events": n_dec_strong,
            "n_decrease_weak_events": n_dec - n_dec_strong}
    return strong, weak, dec, dec_events, diag, dec_strong, dec_weak


def main(cache: Path, tdnet_dir: Path, archive: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    mask = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(mask)) / 2.0).where(mask)

    # AF15 score (EXP-087B/090B construction, factor 1.5)
    eq, npf = E3.fundamentals(fins, dates)
    eq = eq.reindex(columns=codes)
    npf = npf.reindex(columns=codes)
    npf_adj = npf.copy()
    la_mask = pd.DataFrame(False, index=dates, columns=codes)
    eps = episodes(fins)
    for code, lst in eps.items():
        if code not in codes:
            continue
        for start, end, habit, la in lst:
            rows = (dates >= start) & (dates < end)
            if not rows.any():
                continue
            f = 1.0 + 1.5 * float(np.clip(habit, -0.5, 1.0))
            npf_adj.loc[rows, code] = npf.loc[rows, code] / f
            if la:
                la_mask.loc[rows, code] = True
    mcap = panel["MktCap"] * 1e6
    liq = panel["Va"].fillna(0.0).rolling(E3.LIQ_DAYS, min_periods=E3.LIQ_DAYS).mean()
    ok = (liq >= E3.LIQ_MIN) & (mcap > 0) & (eq > 0) & npf_adj.notna() & panel["C"].notna()
    comp_fc = (eq / mcap).where(ok).rank(axis=1, pct=True) + \
        (npf_adj / eq).where(ok).rank(axis=1, pct=True)
    mask_fc = comp_fc.notna()
    score_fc = ((comp_fc.rank(axis=1, pct=True) + mom.where(mask_fc)) / 2.0).where(mask_fc)

    bonus = bonus_matrix(tdnet_dir, dates, codes)
    b_np = bonus.where(mask, False).fillna(False).astype(float).to_numpy()
    bfc_np = bonus.where(mask_fc, False).fillna(False).astype(float).to_numpy()

    strong, weak, dec_flag, dec_events, ldiag, dec_strong, dec_weak = \
        large_flags(archive, dates, codes)

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()
    s_np = comp.to_numpy()
    a_np = score_a.to_numpy()
    fc_s = score_fc.to_numpy()
    avf_long = (score_fc + 0.10 * pd.DataFrame(bfc_np, index=dates, columns=codes)) \
        .where(mask_fc).where(~la_mask)
    dec_long = (score_a - 0.10 * dec_flag.astype(float)).where(mask)
    # 102B: AVF625 long + ABD decrease penalty
    avf_dec_long = avf_long - 0.10 * dec_flag.astype(float)
    # 102C: graded decrease penalty (strong wins)
    dec_pen = np.maximum(0.10 * dec_weak.to_numpy(dtype=float),
                         0.20 * dec_strong.to_numpy(dtype=float))
    decg_long = (score_a - pd.DataFrame(dec_pen, index=dates, columns=codes)).where(mask)

    # 102D: habit panel (EXP-080 episodes; clipped raw habit inside the
    # window, 0 outside) and the blended short score
    habit_panel = pd.DataFrame(0.0, index=dates, columns=codes)
    habit_active = pd.DataFrame(False, index=dates, columns=codes)
    for code, lst in eps.items():
        if code not in codes:
            continue
        for start, end, habit, la in lst:
            rows = (dates >= start) & (dates < end)
            if not rows.any():
                continue
            habit_panel.loc[rows, code] = float(np.clip(habit, -0.5, 1.0))
            habit_active.loc[rows, code] = True
    a_r = score_a.rank(axis=1, pct=True)
    h_r = habit_panel.where(mask).rank(axis=1, pct=True)
    short_ash = ((a_r + (1.0 - h_r)) / 2.0).where(mask)

    variants = {
        # name: (long_np, short_np, long_frac, short_frac)
        "S": None,  # handled by E9.simulate on comp
        "A": None,  # handled by E9.simulate on score_a
        "ABD": (dec_long.to_numpy(), a_np, 1.0, 0.5),
        "ABD625": (dec_long.to_numpy(), a_np, 1.0, 0.625),
        "AVF625": (avf_long.to_numpy(), fc_s, 1.0, 0.625),
        "AVF625D": (avf_dec_long.to_numpy(), fc_s, 1.0, 0.625),
        "ABDG": (decg_long.to_numpy(), a_np, 1.0, 0.5),
        "ASH": (a_np, short_ash.to_numpy(), 1.0, 0.5),
    }

    res: dict = {}
    for pname, (a_, b_) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a_)))
        e = int(dates.searchsorted(pd.Timestamp(b_), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(s_np, o, c, s, e, cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(a_np, o, c, s, e, cost, carry, 1.0, 0.5), index=idx))
            for vname, spec in variants.items():
                if spec is None:
                    continue
                ln, sn, lf, sf = spec
                res[f"{pname}_{vname}_{cname}"] = E9.stats(pd.Series(
                    np.asarray(E13.simulate2(ln, sn, o, c, s, e, cost, carry, lf, sf),
                               dtype=float), index=idx))

    def std_verdict(v, base="A"):
        g = lambda p, k: res[f"{p}_{v}_base"][k]
        bb = lambda p, k: res[f"{p}_{base}_base"][k]
        c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
        c2 = all((g(p, "annual_over_dd") or -9) > (bb(p, "annual_over_dd") or -9)
                 for p in ("first_half", "second_half"))
        gf, bf = res[f"full_{v}_stress"], res[f"full_{base}_stress"]
        c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > (bf["annual_over_dd"] or -9)
        return {"1_profit_positive_both_halves": bool(c1),
                "2_ratio_gt_base_both_halves": bool(c2),
                "3_full_stress_positive_and_ratio_gt_base": bool(c3),
                "promising": bool(c1 and c2 and c3)}

    def adapted_verdict(v, base="A"):
        g = res[f"second_half_{v}_base"]
        bb = res[f"second_half_{base}_base"]
        gs = res[f"second_half_{v}_stress"]
        bs = res[f"second_half_{base}_stress"]
        c1 = g["profit"] > 0
        c2 = (g["annual_over_dd"] or -9) > (bb["annual_over_dd"] or -9)
        c3 = gs["profit"] > 0 and (gs["annual_over_dd"] or -9) > (bs["annual_over_dd"] or -9)
        return {"1_SH_profit_positive": bool(c1),
                "2_SH_ratio_beats_base": bool(c2),
                "3_SH_stress_positive_and_ratio_beats_base": bool(c3),
                "promising": bool(c1 and c2 and c3)}

    verdict = {
        "102A_ABD625_adapted_vs_A": adapted_verdict("ABD625", "A"),
        "102A_ABD625_adapted_vs_ABD_observation": adapted_verdict("ABD625", "ABD"),
        "102B_AVF625D_adapted_vs_AVF625": adapted_verdict("AVF625D", "AVF625"),
        "102B_AVF625D_adapted_vs_A_observation": adapted_verdict("AVF625D", "A"),
        "102C_ABDG_adapted_vs_A": adapted_verdict("ABDG", "A"),
        "102C_ABDG_adapted_vs_ABD_observation": adapted_verdict("ABDG", "ABD"),
        "102D_ASH_standard_vs_A": std_verdict("ASH", "A"),
    }
    sh_rows = (dates >= "2022-01-04") & (dates <= "2026-09-25")
    diag = {"episodes": int(sum(len(v) for v in eps.values())),
            "large_diag": ldiag,
            "dec_flag_median_per_day_SH": float(dec_flag[sh_rows].sum(axis=1).median()),
            "dec_strong_median_per_day_SH": float(dec_strong[sh_rows].sum(axis=1).median()),
            "habit_active_share_of_valid": float(
                (habit_active.to_numpy() & mask.to_numpy()).sum() / mask.to_numpy().sum()),
            "habit_active_names_median_per_day_SH": float(
                (habit_active & mask)[sh_rows].sum(axis=1).median())}
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
