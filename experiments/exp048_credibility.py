"""EXP-048: forecast-credibility discount on A's revision leg.

Preregistration: docs/experiments/EXP-048_PREREGISTRATION.md

Bias_f = (initial forecast NxFNp - actual NP) / TA_f for fiscal
year f (initial forecast from the prior year's FY statement,
matched by NxtFYEn; actual and TA from year f's FY statement).
Cred_i(t) = median of the last 3 biases usable at t (usable from
the actual record's DiscDate); fewer than 2 known biases means
neutral. On each day, names whose Cred is at or above the median
Cred among A-valid names with a Cred are the "optimistic group";
for them the revision rank Rev is discounted on the upside only:
RevAdj = Rev - 0.5 * max(0, Rev - 0.5). A_cred = (composite rank
+ RevAdj) / 2 on A's valid set, both sides.

Judgement is the preregistered adapted set (EXP-017 precedent):
the signal cannot exist before ~2019 on this cache, so the
pass/fail rests on the second half plus the full-period stress
condition; first-half figures are reported for the record.

Usage:
    python experiments/exp048_credibility.py <cache_dir>
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


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def cred_matrix(fins, dates: pd.DatetimeIndex,
                codes: list[str]) -> pd.DataFrame:
    cred = pd.DataFrame(np.nan, index=dates, columns=codes)
    for code in codes:
        fy = [r for r in fins.get(code, [])
              if r.get("CurPerType") == "FY"
              and "FinancialStatements" in str(r.get("DocType", ""))]
        init = {}
        for r in fy:
            v = _num(r.get("NxFNp"))
            if r.get("NxtFYEn") and not np.isnan(v):
                init[r["NxtFYEn"]] = v
        obs = []
        for r in fy:
            f = r.get("CurFYEn")
            if f in init:
                act, ta = _num(r.get("NP")), _num(r.get("TA"))
                if not np.isnan(act) and not np.isnan(ta) and ta > 0:
                    obs.append((pd.Timestamp(r["DiscDate"]),
                                (init[f] - act) / ta))
        if not obs:
            continue
        obs.sort()
        od = np.array([o[0] for o in obs])
        bv = np.array([o[1] for o in obs])
        creds = np.array([
            np.median(bv[max(0, m - 3):m]) if m >= 2 else np.nan
            for m in range(1, len(bv) + 1)])
        k = np.searchsorted(od, dates.to_numpy(), side="right")
        vals = np.where(k >= 1, creds[np.clip(k - 1, 0, len(creds) - 1)],
                        np.nan)
        cred[code] = vals
    return cred


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    o_np = panel["O"].to_numpy()
    c_np = panel["C"].ffill().to_numpy()
    comp = E3.signals(panel, fins, dates)["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    mom_v = mom.where(valid)
    score_a = ((comp_r + mom_v) / 2.0).where(valid)

    cred = cred_matrix(fins, dates, codes)
    avail = valid & cred.notna()
    thresh = cred.where(avail).median(axis=1)
    optimistic = avail & cred.ge(thresh, axis=0)
    mom_adj = mom_v.where(~optimistic,
                          mom_v - 0.5 * (mom_v - 0.5).clip(lower=0))
    score_c = ((comp_r + mom_adj) / 2.0).where(valid)

    coverage = {}
    for pname, (a, b) in PERIODS.items():
        m = (dates >= a) & (dates <= b)
        coverage[pname] = {
            "cred_share_of_valid": float(
                (avail[m].sum().sum() / valid[m].sum().sum())),
            "discounted_share_of_valid": float(
                ((optimistic & mom_v.gt(0.5))[m].sum().sum()
                 / valid[m].sum().sum())),
        }

    res: dict = {"coverage": coverage}
    snp_a, snp_c = score_a.to_numpy(), score_c.to_numpy()
    for pname, (a, b) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a)))
        e = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            for nm, snp in (("A", snp_a), ("A_cred", snp_c)):
                res[f"{pname}_{nm}_{cname}"] = E9.stats(pd.Series(
                    E9.simulate(snp, o_np, c_np, s, e, cost, carry,
                                1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_SH_profit_positive":
            bool(res["second_half_A_cred_base"]["profit"] > 0),
        "2_SH_ratio_beats_A":
            bool(ratio("second_half_A_cred_base")
                 > ratio("second_half_A_base")),
        "3_SH_stress_and_full_stress_beat_A": bool(
            ratio("second_half_A_cred_stress")
            > ratio("second_half_A_stress")
            and res["full_A_cred_stress"]["profit"] > 0
            and ratio("full_A_cred_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
