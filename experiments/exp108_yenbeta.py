"""EXP-108 book test: fundamental yen-beta (overseas sales share) tilt.

Preregistration: docs/experiments/EXP-108_PREREGISTRATION.md (pushed before
running, commit 7d72de75).

Signal (frozen): ovs = overseas sales share from annual securities reports
(EDINET docTypeCode 120), usable from the filing date (inclusive), carried
forward indefinitely; names/periods never available = neutral 0.5 in the
leg. leg_r = percentile rank of domestic share (1 - ovs) within A's valid
set (names without a value get 0.5). A_yb = (comp_r + mom_r + leg_r) / 3,
standard simulate, short fraction 0.5.

Order of operations (registered): faithfulness of the frame (S/A must
reproduce the current-cache references) -> stage-0 kill checks
(a) full-period usable coverage >= 70%, (b) on the worst-TOPIX-decile days
of 2017-2026 the high-overseas quintile must fall MORE than the low-overseas
quintile (spread high - low < 0) -> only then the book test, judged by the
standard 3 criteria vs A.

Usage: python exp108_yenbeta.py <cache_dir> <overseas_share.csv>
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
A_REF = {"first_half": (970_644, 0.348), "second_half": (4_133_557, 1.584),
         "full_stress_ratio": 0.428}
USABLE = ("numeric", "censored", "zero")


def build_ovs_panel(ovs_csv: Path, dates, codes):
    df = pd.read_csv(ovs_csv, dtype={"code": str})
    df = df[df["status"].isin(USABLE)].copy()
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["ovs"] = pd.to_numeric(df["overseas_share"], errors="coerce")
    df = df.dropna(subset=["ovs"])
    panel = pd.DataFrame(np.nan, index=dates, columns=codes)
    for code, g in df.groupby("code"):
        if code not in panel.columns:
            continue
        g = g.sort_values("filing_date")
        s = pd.Series(g["ovs"].to_numpy(),
                      index=g["filing_date"]).groupby(level=0).last()
        union = s.index.union(dates)
        panel[code] = s.reindex(union).ffill().reindex(dates)
    return panel


def stage0_coverage(ovs_csv: Path):
    df = pd.read_csv(ovs_csv, dtype={"code": str})
    by_year = {}
    for y, g in df.groupby(df["period_end"].str[:4]):
        by_year[str(y)] = {
            "filings": int(len(g)),
            "usable": int(g["status"].isin(USABLE).sum()),
            "coverage": float(g["status"].isin(USABLE).mean()),
        }
    cov = float(df["status"].isin(USABLE).mean()) if len(df) else 0.0
    return {"overall_coverage": cov,
            "n_filings": int(len(df)), "by_period_year": by_year}


def stage0_spread(topix, panel, ovs_panel):
    dates = topix.index
    lo = dates.searchsorted(pd.Timestamp("2017-01-04"))
    hi = dates.searchsorted(pd.Timestamp("2026-09-25"), side="right")
    win = dates[lo:hi]
    tret = topix["C"].pct_change()
    thr = float(tret.loc[win].quantile(0.10))
    worst = [d for d in win if pd.notna(tret.loc[d]) and tret.loc[d] <= thr]
    rets = panel["C"].ffill().pct_change()
    spreads, n_names = [], []
    for d in worst:
        v = ovs_panel.loc[d]
        r = rets.loc[d]
        m = v.notna() & r.notna()
        if int(m.sum()) < 50:
            continue
        rp = v[m].rank(pct=True)
        rr = r[m]
        top = rr[rp > 0.8].mean()
        bot = rr[rp <= 0.2].mean()
        spreads.append(float(top - bot))
        n_names.append(int(m.sum()))
    return {"n_worst_days": len(worst), "n_days_used": len(spreads),
            "topix_decile_threshold_pct": round(thr * 100, 3),
            "mean_spread_high_minus_low_pct": (
                round(float(np.mean(spreads)) * 100, 4) if spreads else None),
            "median_spread_pct": (
                round(float(np.median(spreads)) * 100, 4) if spreads else None),
            "median_names_per_day": (
                float(np.median(n_names)) if n_names else None),
            "share_days_negative": (
                float(np.mean([s < 0 for s in spreads])) if spreads else None)}


def main(cache: Path, ovs_csv: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    mask = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    score_a = ((comp_r + mom.where(mask)) / 2.0).where(mask)
    score_s = comp

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    def run(score, pname, cname):
        cost, carry = COSTS[cname]
        a_, b_ = PERIODS[pname]
        s = int(dates.searchsorted(pd.Timestamp(a_)))
        e = int(dates.searchsorted(pd.Timestamp(b_), side="right")) - 1
        idx = dates[s:e + 1]
        return E9.stats(pd.Series(
            E9.simulate(score.to_numpy(), o, c, s, e, cost, carry, 1.0, 0.5),
            index=idx))

    # ---- faithfulness gate (frame must reproduce A's references) ----
    a_fh = run(score_a, "first_half", "base")
    a_sh = run(score_a, "second_half", "base")
    a_fs = run(score_a, "full", "stress")
    faith = {
        "FH": bool(a_fh["profit"] == A_REF["first_half"][0]
                   and abs(a_fh["annual_over_dd"]
                           - A_REF["first_half"][1]) < 0.0015),
        "SH": bool(a_sh["profit"] == A_REF["second_half"][0]
                   and abs(a_sh["annual_over_dd"]
                           - A_REF["second_half"][1]) < 0.0015),
        "full_stress": bool(abs(a_fs["annual_over_dd"]
                                - A_REF["full_stress_ratio"]) < 0.0015),
    }
    out = {"faithfulness": faith,
           "A_recomputed": {"FH": a_fh, "SH": a_sh, "full_stress": a_fs}}
    if not all(faith.values()):
        out["verdict"] = "FRAME_MISMATCH_STOP"
        print(json.dumps(out, ensure_ascii=False))
        return

    # ---- stage 0 ----
    cov = stage0_coverage(ovs_csv)
    ovs_panel = build_ovs_panel(ovs_csv, dates, codes)
    spr = stage0_spread(topix, panel, ovs_panel)
    out["stage0"] = {"coverage": cov, "spread": spr}
    kill_a = cov["overall_coverage"] < 0.70
    kill_b = (spr["mean_spread_high_minus_low_pct"] is None
              or spr["mean_spread_high_minus_low_pct"] >= 0)
    out["stage0"]["kill_coverage"] = bool(kill_a)
    out["stage0"]["kill_spread"] = bool(kill_b)
    if kill_a or kill_b:
        out["verdict"] = "STAGE0_KILL"
        print(json.dumps(out, ensure_ascii=False))
        return

    # ---- book test ----
    domestic = 1.0 - ovs_panel
    leg_r = pd.DataFrame(0.5, index=dates, columns=codes)
    ranked = domestic.where(mask).rank(axis=1, pct=True)
    leg_r = leg_r.where(domestic.isna() | ~mask, ranked)
    leg_r = leg_r.where(mask)
    score_yb = ((comp_r + mom.where(mask) + leg_r) / 3.0).where(mask)

    res = {}
    for pname in PERIODS:
        for cname in COSTS:
            res[f"{pname}_A_{cname}"] = run(score_a, pname, cname)
            res[f"{pname}_YB_{cname}"] = run(score_yb, pname, cname)
            res[f"{pname}_S_{cname}"] = run(score_s, pname, cname)
    out["res"] = res

    def std_verdict(v, base="A"):
        g = lambda p, k: res[f"{p}_{v}_base"][k]
        bb = lambda p, k: res[f"{p}_{base}_base"][k]
        c1 = all(g(p, "profit") > 0
                 for p in ("first_half", "second_half"))
        c2 = all((g(p, "annual_over_dd") or -9)
                 > (bb(p, "annual_over_dd") or -9)
                 for p in ("first_half", "second_half"))
        gf, bf = res[f"full_{v}_stress"], res[f"full_{base}_stress"]
        c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) \
            > (bf["annual_over_dd"] or -9)
        return {"1_profit_positive_both_halves": bool(c1),
                "2_ratio_gt_A_both_halves": bool(c2),
                "3_full_stress_positive_and_ratio_gt_A": bool(c3),
                "promising": bool(c1 and c2 and c3)}

    out["verdict_std_vs_A"] = std_verdict("YB")
    # diagnostics: how many valid names carry an ovs value, by era
    sh = (dates >= "2022-01-04") & (dates <= "2026-09-25")
    fh = (dates >= "2017-01-04") & (dates <= "2021-12-30")
    covmask = ovs_panel.notna() & mask
    out["diag"] = {
        "ovs_names_median_per_day_FH": float(covmask[fh].sum(axis=1).median()),
        "ovs_names_median_per_day_SH": float(covmask[sh].sum(axis=1).median()),
        "valid_names_median_per_day_SH": float(mask[sh].sum(axis=1).median()),
    }
    out["verdict"] = "PROMISING" if out["verdict_std_vs_A"]["promising"] \
        else "NOT_PROMISING"
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
