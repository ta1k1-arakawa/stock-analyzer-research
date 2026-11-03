"""EXP-076: post-ex-date avoidance on A's long side.

Events and yields follow EXP-070's derivation. High-yield events
(yield >= same-year event median) exclude the name from A's long
book for [ex, ex+19] business days. Short side unchanged. Judged by
the standard 3 criteria vs A.
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
import exp013_vol_managed as E13

BUDGET = E9.BUDGET
PERIODS = {"first_half": ("2017-01-04", "2021-12-30"),
           "second_half": ("2022-01-04", "2026-09-25"),
           "full": ("2017-01-04", "2026-09-25")}


def num(x) -> float:
    try:
        return float(x)
    except Exception:
        return np.nan


def exclusion_panel(fins, dates, close: pd.DataFrame) -> pd.DataFrame:
    events = []
    for code, recs in fins.items():
        fy_ends, q2_ends = set(), set()
        annual_div, interim_div = {}, {}
        for r in recs:
            if "FinancialStatements" not in str(r.get("DocType")):
                continue
            dd = r.get("DiscDate")
            if r.get("CurPerType") == "FY" and r.get("CurFYEn"):
                fy_ends.add(r["CurFYEn"])
                if num(r.get("DivAnn")) > 0:
                    annual_div[dd] = num(r["DivAnn"])
                if num(r.get("Div2Q")) > 0:
                    interim_div[dd] = num(r["Div2Q"])
            if r.get("CurPerType") == "2Q" and r.get("CurPerEn"):
                q2_ends.add(r["CurPerEn"])
        for rd in fy_ends:
            events.append((code, rd, annual_div))
        for rd in q2_ends:
            events.append((code, rd, interim_div))
    ev_rows = []
    for code, rd, divmap in events:
        R = pd.Timestamp(rd)
        i = int(dates.searchsorted(R, side="right")) - 1
        if i < 25:
            continue
        ex_i = i - 1
        elig = [d for d in divmap if pd.Timestamp(d) <= dates[ex_i - 11]]
        if not elig:
            continue
        amt = divmap[max(elig)]
        px = close[code].iloc[ex_i - 11]
        if not np.isfinite(px) or px <= 0:
            continue
        ev_rows.append({"code": code, "ex_i": ex_i, "year": R.year,
                        "yld": amt / px})
    ev = pd.DataFrame(ev_rows)
    ev["high"] = ev["yld"] >= ev.groupby("year")["yld"].transform("median")
    arr = np.zeros((len(dates), close.shape[1]), dtype=bool)
    col_idx = {c: j for j, c in enumerate(close.columns)}
    for _, r in ev[ev["high"]].iterrows():
        j = col_idx[r["code"]]
        arr[r["ex_i"]: r["ex_i"] + 20, j] = True
    return pd.DataFrame(arr, index=dates, columns=close.columns)


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
    o_np = panel["O"].to_numpy()
    c_np = panel["C"].ffill().to_numpy()
    comp = E3.signals(panel, fins, dates)["composite"]
    mom = E10.revision_momentum_scores(fins, dates, list(panel["C"].columns))
    valid = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    score_s = comp_r.where(valid)
    score_a = ((comp_r + mom.where(valid)) / 2.0).where(valid)
    excl = exclusion_panel(fins, dates, panel["C"])
    score_long = score_a.mask(excl & valid)
    snp_s, snp_a = score_s.to_numpy(), score_a.to_numpy()
    lnp, snp_x = score_long.to_numpy(), score_a.to_numpy()

    out: dict = {}
    for label, fn in (("S", "s"), ("A", "s"), ("A_exa", "x")):
        for cname, (cost, carry) in E9.COSTS.items():
            res = {}
            for pname, (a, b) in PERIODS.items():
                s = int(dates.searchsorted(pd.Timestamp(a)))
                e = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
                if fn == "s":
                    sc = snp_s if label == "S" else snp_a
                    eq = E9.simulate(sc, o_np, c_np, s, e, cost, carry, 1.0, 0.5)
                else:
                    eq = E13.simulate2(lnp, snp_x, o_np, c_np, s, e,
                                       cost, carry, 1.0, 0.5)
                res[pname] = stats(eq, (dates[e] - dates[s]).days)
            out[f"{label}_{cname}"] = res

    a_b, a_s = out["A_base"], out["A_stress"]
    t_b, t_s = out["A_exa_base"], out["A_exa_stress"]
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


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/home/hatch/workspace/cache/jquants_exp002"))
