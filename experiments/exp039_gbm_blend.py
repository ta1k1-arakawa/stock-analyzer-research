"""EXP-039: LightGBM nonlinear model blended with A.

Preregistration: docs/experiments/EXP-039_PREREGISTRATION.md

Features, sample construction and target are EXP-017's, unchanged
(19 rank characteristics; monthly samples 2017-2021; target =
demeaned next-20-trading-day return). The ridge pipeline is
replicated in-run as a faithfulness gate: the CV-chosen alpha and
the second-half ridge statistics must match EXP-017's published
values before the GBM numbers are read. The GBM uses the single
preregistered hyperparameter set (no search), is fit once on all
training samples, frozen, and applied to daily features.
A_blend = (rank of A's score + rank of GBM prediction) / 2 on
A's valid set. Judged against A by the standard three criteria.

Usage:
    python experiments/exp039_gbm_blend.py <cache_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3
import exp009_long_short as E9
import exp010_earnings_momentum as E10
import exp017_ridge as E17

PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
GBM_PARAMS = {"objective": "regression", "learning_rate": 0.05,
              "max_depth": 3, "min_data_in_leaf": 50,
              "bagging_fraction": 0.8, "bagging_freq": 1,
              "feature_fraction": 0.8, "lambda_l2": 1.0,
              "seed": 0, "verbose": -1}
GBM_ROUNDS = 300
EXP017_SH = {"profit": 2_679_405, "annual_over_dd": 0.944}


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    c_df = panel["C"]
    c_ff = c_df.ffill()
    o_np = panel["O"].to_numpy()
    c_np = c_ff.to_numpy()
    mktcap = panel["MktCap"] * 1e6
    va = panel["Va"]
    fund = E17.fundamental_panels(fins, dates, codes)
    logret = np.log(c_ff / c_ff.shift(1))
    mkt_ret = np.log(topix["C"] / topix["C"].shift(1))
    rev_mom = E10.revision_momentum_scores(fins, dates, codes)
    raw = {
        "b_p": fund["eq"] / mktcap,
        "f_roe": fund["f_np"] / fund["eq"],
        "op_ta": fund["op"] / fund["ta"],
        "sales_yoy": fund["sales_yoy"],
        "np_yoy": fund["np_yoy"],
        "accrual": fund["accrual"],
        "lev": fund["ta"] / fund["eq"],
        "cfo_ta": fund["cfo_ta"],
        "div_yield": fund["f_div"] / c_ff,
        "size": np.log(mktcap),
        "mom_6_1": c_ff.shift(21) / c_ff.shift(126) - 1.0,
        "rev_5": -(c_ff / c_ff.shift(5) - 1.0),
        "vol_60": logret.rolling(60, min_periods=40).std(),
        "beta_120": logret.rolling(120, min_periods=60).cov(mkt_ret)
        .div(mkt_ret.rolling(120, min_periods=60).var(), axis=0),
        "liq": np.log(va.rolling(20, min_periods=10).mean()),
        "hi_120": c_ff / c_ff.rolling(120, min_periods=60).max() - 1.0,
        "e_p": fund["fy_np"] / mktcap,
        "roe": fund["fy_roe"],
    }
    X = {}
    for name in E17.FEATURES:
        if name == "rev_mom":
            r = rev_mom - 0.5
        else:
            r = raw[name].rank(axis=1, pct=True) - 0.5
        X[name] = r.reindex(index=dates, columns=codes).fillna(0.0)
    Xstack = np.stack([X[n].to_numpy() for n in E17.FEATURES])

    last_train = int(dates.searchsorted(E17.TRAIN_END,
                                        side="right")) - 1
    months = {}
    for i, d in enumerate(dates):
        if d <= E17.TRAIN_END:
            months[(d.year, d.month)] = i
    sample_idx = [months[k] for k in sorted(months) if k >= (2017, 1)]
    sample_idx = [ti for ti in sample_idx
                  if ti + E17.HORIZON <= last_train]
    c_raw = c_df.to_numpy()
    Xs, ys = [], []
    for ti in sample_idx:
        fwd = c_np[ti + E17.HORIZON] / c_np[ti] - 1.0
        valid = np.isfinite(c_raw[ti]) \
            & np.isfinite(c_raw[ti + E17.HORIZON]) & np.isfinite(fwd)
        y = np.where(valid, fwd, np.nan)
        y = y - np.nanmean(y)
        Xs.append(Xstack[:, ti, :][:, valid].T)
        ys.append(y[valid])
    Xall = np.vstack(Xs)
    yall = np.concatenate(ys)

    # --- faithfulness gate: EXP-017 ridge with fixed alpha=1000
    beta = E17.ridge_fit(Xall, yall, 1000.0)
    pred_ridge = np.einsum("k,ktn->tn", beta, Xstack)
    st = int(dates.searchsorted(pd.Timestamp("2022-01-04")))
    en = int(dates.searchsorted(pd.Timestamp("2026-09-25"),
                                side="right")) - 1
    ridge_sh = E9.stats(pd.Series(
        E9.simulate(pred_ridge, o_np, c_np, st, en, 0.0003, 0.03,
                    1.0, 0.5), index=dates[st:en + 1]))
    gate = {"n_samples": int(len(yall)),
            "ridge_sh_profit": ridge_sh["profit"],
            "ridge_sh_ratio": ridge_sh["annual_over_dd"],
            "matches_exp017": bool(
                ridge_sh["profit"] == EXP017_SH["profit"]
                and ridge_sh["annual_over_dd"]
                == EXP017_SH["annual_over_dd"])}

    # --- GBM: one frozen fit (native API; the registered
    # hyperparameters map 1:1: n_estimators -> num_boost_round,
    # min_child_samples -> min_data_in_leaf, subsample ->
    # bagging_fraction with freq 1, colsample_bytree ->
    # feature_fraction, reg_lambda -> lambda_l2)
    dtrain = lgb.Dataset(Xall, label=yall,
                         feature_name=list(E17.FEATURES))
    model = lgb.train(GBM_PARAMS, dtrain, num_boost_round=GBM_ROUNDS)
    pred_gbm = model.predict(
        Xstack.transpose(1, 2, 0).reshape(-1, Xstack.shape[0])
    ).reshape(Xstack.shape[1], Xstack.shape[2])
    imp = sorted(zip(E17.FEATURES,
                     model.feature_importance(
                         importance_type="gain").tolist()),
                 key=lambda kv: -kv[1])[:5]
    gate["gbm_top_features"] = imp

    comp = E3.signals(panel, fins, dates)["composite"]
    mom = rev_mom
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid)) / 2.0) \
        .where(valid)
    gbm_df = pd.DataFrame(pred_gbm, index=dates, columns=codes)
    a_rank = score_a.rank(axis=1, pct=True)
    g_rank = gbm_df.where(valid).rank(axis=1, pct=True)
    score_b = ((a_rank + g_rank) / 2.0).where(valid)

    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        s0 = int(dates.searchsorted(pd.Timestamp(a)))
        e0 = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[s0:e0 + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(comp.to_numpy(), o_np, c_np, s0, e0, cost,
                            carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_a.to_numpy(), o_np, c_np, s0, e0,
                            cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_gbm_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_b.to_numpy(), o_np, c_np, s0, e0,
                            cost, carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_gbm_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_gbm_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_gbm_stress"]["profit"] > 0
            and ratio("full_A_gbm_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict, "gate": gate},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
