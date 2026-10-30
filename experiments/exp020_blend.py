"""EXP-020: blend of the EXP-010 A score and the frozen EXP-017 ridge.

Preregistration: docs/experiments/EXP-020_PREREGISTRATION.md (committed
before this code was run).  The ridge is rebuilt with EXP-017's exact
construction and the FIXED alpha=1000 (no re-selection); the fitted
coefficients are checked against EXP-017's published values and the
run aborts if they differ.  Blend = mean of the two percentile ranks
within A's valid universe each day.  Judged on the second half against
A (EXP-017-style adapted criteria); the first half is reference only
because it contains the ridge's training era.

Run:  python experiments/exp020_blend.py [cache_dir]
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import exp003_rotation as E3
import exp009_long_short as E9
import exp010_earnings_momentum as E10
import exp017_ridge as E17

CACHE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/jquants_exp002")
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
SECOND_HALF = ("2022-01-04", "2026-09-25")
FIRST_HALF = ("2017-01-04", "2021-12-30")
ALPHA_FIXED = 1000.0
EXPECTED_COEF = {
    "b_p": 0.0006714950951038921, "f_roe": 0.0046481169944374255,
    "op_ta": 0.0016565538772283725, "rev_mom": 0.005746253776418932,
    "sales_yoy": -0.003269516309829929, "np_yoy": -0.0013493219774525344,
    "accrual": -0.0010581760166085258, "lev": 0.0015866285694633494,
    "cfo_ta": -0.0001029779599006704, "div_yield": 0.005884752501803466,
    "size": -0.005250764356671206, "mom_6_1": -0.0019041006404299516,
    "rev_5": 0.0021596527705934117, "vol_60": 0.0026205279025517266,
    "beta_120": 0.006266304106591773, "liq": -0.00470216295037154,
    "hi_120": 0.00011251664384744128, "e_p": -0.0008045732532368257,
    "roe": 0.0020740188739112177,
}


def main(cache: Path) -> None:
    if not (cache / "topix.json").exists():
        raise SystemExit(f"cache not found: {cache}")
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    c_df = panel["C"]
    c_ff = c_df.ffill()
    mktcap = panel["MktCap"] * 1e6
    va = panel["Va"]
    fund = E17.fundamental_panels(fins, dates, codes)
    logret = np.log(c_ff / c_ff.shift(1))
    mkt_ret = np.log(topix["C"] / topix["C"].shift(1))
    rev_mom = E10.revision_momentum_scores(fins, dates, codes)
    raw = {
        "b_p": fund["eq"] / mktcap, "f_roe": fund["f_np"] / fund["eq"],
        "op_ta": fund["op"] / fund["ta"], "sales_yoy": fund["sales_yoy"],
        "np_yoy": fund["np_yoy"], "accrual": fund["accrual"],
        "lev": fund["ta"] / fund["eq"], "cfo_ta": fund["cfo_ta"],
        "div_yield": fund["f_div"] / c_ff, "size": np.log(mktcap),
        "mom_6_1": c_ff.shift(21) / c_ff.shift(126) - 1.0,
        "rev_5": -(c_ff / c_ff.shift(5) - 1.0),
        "vol_60": logret.rolling(60, min_periods=40).std(),
        "beta_120": logret.rolling(120, min_periods=60).cov(mkt_ret).div(
            mkt_ret.rolling(120, min_periods=60).var(), axis=0),
        "liq": np.log(va.rolling(20, min_periods=10).mean()),
        "hi_120": c_ff / c_ff.rolling(120, min_periods=60).max() - 1.0,
        "e_p": fund["fy_np"] / mktcap, "roe": fund["fy_roe"],
    }
    X = {}
    for name in E17.FEATURES:
        r = (rev_mom - 0.5) if name == "rev_mom" else \
            (raw[name].rank(axis=1, pct=True) - 0.5)
        X[name] = r.reindex(index=dates, columns=codes).fillna(0.0)
    Xstack = np.stack([X[n].to_numpy() for n in E17.FEATURES])

    last_train = int(dates.searchsorted(E17.TRAIN_END, side="right")) - 1
    months = {}
    for i, d in enumerate(dates):
        if d <= E17.TRAIN_END:
            months[(d.year, d.month)] = i
    sample_idx = [months[k] for k in sorted(months) if k >= (2017, 1)]
    sample_idx = [ti for ti in sample_idx if ti + E17.HORIZON <= last_train]
    c_np = c_ff.to_numpy()
    c_raw = c_df.to_numpy()
    Xs, ys = [], []
    for ti in sample_idx:
        fwd = c_np[ti + E17.HORIZON] / c_np[ti] - 1.0
        valid = np.isfinite(c_raw[ti]) & np.isfinite(c_raw[ti + E17.HORIZON]) \
            & np.isfinite(fwd)
        y = np.where(valid, fwd, np.nan)
        y = y - np.nanmean(y)
        Xs.append(Xstack[:, ti, :][:, valid].T)
        ys.append(y[valid])
    beta = E17.ridge_fit(np.vstack(Xs), np.concatenate(ys), ALPHA_FIXED)
    got = {n: float(b) for n, b in zip(E17.FEATURES, beta)}
    for n, exp in EXPECTED_COEF.items():
        if abs(got[n] - exp) > 1e-9:
            raise SystemExit(f"coefficient mismatch for {n}: {got[n]} vs EXP-017 {exp}")
    pred = pd.DataFrame(np.einsum("k,ktn->tn", beta, Xstack),
                        index=dates, columns=codes)

    comp = E3.signals(panel, fins, dates)["composite"]
    mask = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + rev_mom.where(mask)) / 2.0).where(mask)
    blend = ((score_a.rank(axis=1, pct=True)
              + pred.where(mask).rank(axis=1, pct=True)) / 2.0).where(mask)

    o = panel["O"].to_numpy()

    def run(sc, period, ck):
        cost, carry = COSTS[ck]
        start = int(dates.searchsorted(pd.Timestamp(period[0])))
        end = int(dates.searchsorted(pd.Timestamp(period[1]), side="right")) - 1
        curve = E9.simulate(sc.to_numpy(), o, c_np, start, end, cost, carry, 1.0, 0.5)
        return E9.stats(pd.Series(curve, index=dates[start:end + 1]))

    out = {"coef_check": "passed"}
    for label, period in (("second_half", SECOND_HALF), ("first_half", FIRST_HALF)):
        out[label] = {
            "blend": {ck: run(blend, period, ck) for ck in COSTS},
            "A": {ck: run(score_a, period, ck) for ck in COSTS},
            "S": {ck: run(comp, period, ck) for ck in COSTS},
        }
    b, a = out["second_half"]["blend"], out["second_half"]["A"]
    out["verdict"] = {
        "1_sh_base_profit_positive": bool(b["base"]["profit"] > 0),
        "2_sh_base_ratio_gt_A": bool(b["base"]["annual_over_dd"] > a["base"]["annual_over_dd"]),
        "3_sh_stress_positive_and_ratio_gt_A": bool(
            b["stress"]["profit"] > 0 and b["stress"]["annual_over_dd"] > a["stress"]["annual_over_dd"]),
    }
    out["verdict"]["promising"] = all(out["verdict"].values())
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main(CACHE)
