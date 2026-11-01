"""EXP-050: downside-beta asymmetry tilt on A's long side.

Preregistration: docs/experiments/EXP-050_PREREGISTRATION.md

For each name and day, semi-betas vs TOPIX over the trailing
250 return days ending 5 days before the signal day:
beta- on down-market days, beta+ on up-market days (each side
needs >= 60 days, >= 200 valid pairs overall, else missing).
Asym = beta- - beta+, percentile-ranked within A's valid set.
Long score = A score - 0.25 * rank_pct(Asym); the short score
is A's, unchanged. Simulated with EXP-013's simulate2.

Usage:
    python experiments/exp050_downside_beta.py <cache_dir>
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
WIN, LAG, MIN_SIDE = 250, 5, 60


def asym_matrix(panel, topix) -> np.ndarray:
    rm = topix["C"].pct_change().to_numpy()
    ri = panel["C"].pct_change().to_numpy()
    T, N = ri.shape

    def cs(a):
        return np.concatenate(([0.0], np.cumsum(a)))

    out = np.full((T, N), np.nan)
    dn_all = np.isfinite(rm) & (rm < 0)
    up_all = np.isfinite(rm) & (rm > 0)
    Dn, Up = cs(dn_all), cs(up_all)
    Md = cs(np.where(dn_all, rm, 0.0))
    MMd = cs(np.where(dn_all, rm * rm, 0.0))
    Mu = cs(np.where(up_all, rm, 0.0))
    MMu = cs(np.where(up_all, rm * rm, 0.0))
    tt = np.arange(T)
    b = tt - LAG + 1
    a = b - WIN
    valid_t = a >= 0
    nd = np.where(valid_t, Dn[np.clip(b, 0, T)] - Dn[np.clip(a, 0, T)], 0)
    nu = np.where(valid_t, Up[np.clip(b, 0, T)] - Up[np.clip(a, 0, T)], 0)
    ok_t = valid_t & (nd >= MIN_SIDE) & (nu >= MIN_SIDE)
    sm_d = np.where(ok_t, (MMd[np.clip(b, 0, T)] - MMd[np.clip(a, 0, T)]) / np.maximum(nd, 1) - ((Md[np.clip(b, 0, T)] - Md[np.clip(a, 0, T)]) / np.maximum(nd, 1)) ** 2, np.nan)
    sm_u = np.where(ok_t, (MMu[np.clip(b, 0, T)] - MMu[np.clip(a, 0, T)]) / np.maximum(nu, 1) - ((Mu[np.clip(b, 0, T)] - Mu[np.clip(a, 0, T)]) / np.maximum(nu, 1)) ** 2, np.nan)
    md_mean = np.where(ok_t, (Md[np.clip(b, 0, T)] - Md[np.clip(a, 0, T)]) / np.maximum(nd, 1), np.nan)
    mu_mean = np.where(ok_t, (Mu[np.clip(b, 0, T)] - Mu[np.clip(a, 0, T)]) / np.maximum(nu, 1), np.nan)
    for j in range(N):
        x = ri[:, j]
        ok = np.isfinite(x) & np.isfinite(rm)
        x0 = np.where(ok, x, 0.0)
        XMd = cs(np.where(dn_all & ok, x0 * rm, 0.0))
        Xd = cs(np.where(dn_all & ok, x0, 0.0))
        XMu = cs(np.where(up_all & ok, x0 * rm, 0.0))
        Xu = cs(np.where(up_all & ok, x0, 0.0))
        with np.errstate(invalid="ignore", divide="ignore"):
            cov_d = (XMd[np.clip(b, 0, T)] - XMd[np.clip(a, 0, T)]) / np.maximum(nd, 1) - ((Xd[np.clip(b, 0, T)] - Xd[np.clip(a, 0, T)]) / np.maximum(nd, 1)) * md_mean
            cov_u = (XMu[np.clip(b, 0, T)] - XMu[np.clip(a, 0, T)]) / np.maximum(nu, 1) - ((Xu[np.clip(b, 0, T)] - Xu[np.clip(a, 0, T)]) / np.maximum(nu, 1)) * mu_mean
            beta_d = np.where(ok_t & (sm_d > 0), cov_d / sm_d, np.nan)
            beta_u = np.where(ok_t & (sm_u > 0), cov_u / sm_u, np.nan)
        out[:, j] = beta_d - beta_u
    return out


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    o_np = panel["O"].to_numpy()
    c_np = panel["C"].ffill().to_numpy()
    comp = E3.signals(panel, fins, dates)["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid))
               / 2.0).where(valid)
    asym = pd.DataFrame(asym_matrix(panel, topix), index=dates,
                        columns=codes)
    asym_r = asym.where(valid).rank(axis=1, pct=True)
    long_score = (score_a - 0.25 * asym_r.fillna(0.0)).where(valid)
    snp = score_a.to_numpy()
    lnp = long_score.to_numpy()

    coverage = {}
    for pname, (a, b) in PERIODS.items():
        m = (dates >= a) & (dates <= b)
        coverage[pname] = float(
            (asym[m].notna() & valid[m]).sum().sum()
            / valid[m].sum().sum())

    res: dict = {"coverage": coverage}
    for pname, (a, b) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a)))
        e = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(snp, o_np, c_np, s, e, cost, carry,
                            1.0, 0.5), index=idx))
            res[f"{pname}_A_db_{cname}"] = E9.stats(pd.Series(
                E13.simulate2(lnp, snp, o_np, c_np, s, e, cost,
                              carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_db_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_db_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_db_stress"]["profit"] > 0
            and ratio("full_A_db_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
