"""EXP-067: failed-ingredient trio stack (round-6 #7).

Composite leg = mean of the pct ranks (within A's valid set) of
EXP-030's TSY, EXP-025's payout-upgrade decay score, and -Cred from
EXP-048 (registered definitions reused unchanged; missing = neutral
0.5). A_trio = (composite + revision momentum + trio leg) / 3.
Criteria: the standard three vs A plus the preregistered extra
condition 4 (stress ratios >= A in BOTH halves).
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
import exp025_payout_tilt as E25
import exp030_shareholder_yield as E30
import exp048_credibility as E48

BUDGET = E9.BUDGET
COST_BASE, CARRY_BASE = E9.COSTS["base"]
COST_STRESS, CARRY_STRESS = E9.COSTS["stress"]
PERIODS = {"first_half": ("2017-01-04", "2021-12-30"),
           "second_half": ("2022-01-04", "2026-09-25"),
           "full": ("2017-01-04", "2026-09-25")}


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
    o, c = panel["O"], panel["C"]
    c_ff = c.ffill()
    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    mom_r = mom.where(valid)

    tsy, _, _ = E30.tsy_frame(fins, dates, codes, c)
    events = E25.detect_events(fins)
    raw = pd.DataFrame(E25.policy_raw(events, dates, codes),
                       index=dates, columns=codes)
    cred = E48.cred_matrix(fins, dates, codes)

    def prank(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.where(valid).rank(axis=1, pct=True)

    trio_leg = (prank(tsy).fillna(0.5) + prank(raw).fillna(0.5)
                + prank(-cred).fillna(0.5)) / 3.0
    trio_leg = trio_leg.where(valid)

    score_s = comp_r.where(valid)
    score_a = ((comp_r + mom_r) / 2.0).where(valid)
    score_trio = ((comp_r + mom_r + trio_leg) / 3.0).where(valid)

    o_np, c_np = o.to_numpy(), c_ff.to_numpy()
    out: dict = {}
    curves = {}
    for label, score in (("S", score_s), ("A", score_a), ("A_trio", score_trio)):
        snp = score.to_numpy()
        for cost, carry, tag in ((COST_BASE, CARRY_BASE, "base"),
                                 (COST_STRESS, CARRY_STRESS, "stress")):
            res = {}
            for pname, (a, b) in PERIODS.items():
                s = int(dates.searchsorted(pd.Timestamp(a)))
                e = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
                eq = E9.simulate(snp, o_np, c_np, s, e, cost, carry, 1.0, 0.5)
                res[pname] = stats(eq, (dates[e] - dates[s]).days)
                if label == "A_trio" and tag == "base":
                    curves[pname] = eq
            out[f"{label}_{tag}"] = res

    a_b, a_s = out["A_base"], out["A_stress"]
    t_b, t_s = out["A_trio_base"], out["A_trio_stress"]
    crit = {
        "1_profit_both_halves": bool(t_b["first_half"]["profit"] > 0 and t_b["second_half"]["profit"] > 0),
        "2_ratio_beats_A_both": bool(
            t_b["first_half"]["ann_return_over_dd"] > a_b["first_half"]["ann_return_over_dd"]
            and t_b["second_half"]["ann_return_over_dd"] > a_b["second_half"]["ann_return_over_dd"]),
        "3_full_stress": bool(t_s["full"]["profit"] > 0
                              and t_s["full"]["ann_return_over_dd"] > a_s["full"]["ann_return_over_dd"]),
        "4_stress_ratio_both_halves": bool(
            t_s["first_half"]["ann_return_over_dd"] >= a_s["first_half"]["ann_return_over_dd"]
            and t_s["second_half"]["ann_return_over_dd"] >= a_s["second_half"]["ann_return_over_dd"]),
    }
    out["criteria_vs_A"] = crit
    out["verdict"] = "PROMISING" if all(crit.values()) else "NOT promising"
    print(json.dumps(out, ensure_ascii=False, indent=1))
    for pname, eq in curves.items():
        np.savetxt(f"/home/hatch/workspace/exp067_run/A_trio_{pname}.csv",
                   np.asarray(eq, dtype=float).ravel())


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/home/hatch/workspace/cache/jquants_exp002"))
