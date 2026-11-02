"""EXP-069: revision-momentum leg built from after-close disclosures only.

Events and signs follow EXP-010 exactly, filtered to disclosures whose
DiscTime is at/after the close (15:00 before 2024-11-05, 15:30 from
2024-11-05). A_disc = (composite rank + after-close momentum rank)/2.
Standard 3 criteria vs A.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import exp003_rotation as E3
import exp009_long_short as E9
import exp010_earnings_momentum as E10

BUDGET = E9.BUDGET
PERIODS = {"first_half": ("2017-01-04", "2021-12-30"),
           "second_half": ("2022-01-04", "2026-09-25"),
           "full": ("2017-01-04", "2026-09-25")}


def after_close_momentum(fins, dates, codes) -> pd.DataFrame:
    rec = E10._as_records(fins)
    rec["rev_sign"] = np.sign(
        rec.groupby("code")["np_forecast"].diff().fillna(0.0))
    rev = rec[rec["rev_sign"] != 0].copy()

    def is_after(row) -> bool:
        t = str(row["disc_time"])[:5]
        if not t or t == "nan":
            return False
        cutoff = "15:30" if row["disc_date"] >= pd.Timestamp("2024-11-05") else "15:00"
        return t >= cutoff

    rev = rev[rev.apply(is_after, axis=1)]
    dates = pd.DatetimeIndex(dates)
    mom = pd.DataFrame(0.0, index=dates, columns=list(codes))
    if rev.empty:
        return mom.rank(axis=1, pct=True)
    dvals = dates.to_numpy()
    lo_vals = dvals - np.timedelta64(E10.MOM_WINDOW_DAYS, "D")
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


def stats(equity, days: int) -> dict:
    equity = pd.Series(np.asarray(equity, dtype=float))
    total = float(equity.iloc[-1] / BUDGET - 1.0)
    dd = float((equity / equity.cummax() - 1.0).min())
    return {"profit": int(round(BUDGET * total)),
            "return_pct": round(100 * total, 2),
            "max_dd_pct": round(100 * dd, 2),
            "ann_return_over_dd": round(
                ((1.0 + total) ** (365.25 / days) - 1.0) / abs(dd), 3) if dd < 0 else None}


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    o_np = panel["O"].to_numpy()
    c_np = panel["C"].ffill().to_numpy()
    comp = E3.signals(panel, fins, dates)["composite"]
    mom_all = E10.revision_momentum_scores(fins, dates, codes)
    mom_after = after_close_momentum(fins, dates, codes)
    valid = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    score_s = comp_r.where(valid)
    score_a = ((comp_r + mom_all.where(valid)) / 2.0).where(valid)
    score_d = ((comp_r + mom_after.where(valid)) / 2.0).where(valid)

    out: dict = {}
    curves = {}
    for label, score in (("S", score_s), ("A", score_a), ("A_disc", score_d)):
        snp = score.to_numpy()
        for cname, (cost, carry) in E9.COSTS.items():
            res = {}
            for pname, (a, b) in PERIODS.items():
                s = int(dates.searchsorted(pd.Timestamp(a)))
                e = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
                eq = E9.simulate(snp, o_np, c_np, s, e, cost, carry, 1.0, 0.5)
                res[pname] = stats(eq, (dates[e] - dates[s]).days)
                if label == "A_disc" and cname == "base":
                    curves[pname] = eq
            out[f"{label}_{cname}"] = res

    a_b, a_s = out["A_base"], out["A_stress"]
    t_b, t_s = out["A_disc_base"], out["A_disc_stress"]
    crit = {
        "1_profit_both_halves": bool(t_b["first_half"]["profit"] > 0 and t_b["second_half"]["profit"] > 0),
        "2_ratio_beats_A_both": bool(
            t_b["first_half"]["ann_return_over_dd"] > a_b["first_half"]["ann_return_over_dd"]
            and t_b["second_half"]["ann_return_over_dd"] > a_b["second_half"]["ann_return_over_dd"]),
        "3_full_stress": bool(t_s["full"]["profit"] > 0
                              and t_s["full"]["ann_return_over_dd"] > a_s["full"]["ann_return_over_dd"]),
    }
    out["criteria_vs_A"] = crit
    out["verdict"] = "PROMISING" if all(crit.values()) else "NOT promising"
    print(json.dumps(out, ensure_ascii=False, indent=1))
    for pname, eq in curves.items():
        np.savetxt(f"/home/hatch/workspace/exp069_run/A_disc_{pname}.csv",
                   np.asarray(eq, dtype=float).ravel())


if __name__ == "__main__":
    Path("/home/hatch/workspace/exp069_run").mkdir(exist_ok=True)
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/home/hatch/workspace/cache/jquants_exp002"))
