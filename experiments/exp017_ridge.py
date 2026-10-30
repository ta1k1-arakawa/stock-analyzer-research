"""EXP-017: ridge regression on ~19 rank-transformed characteristics.

Preregistration: docs/experiments/EXP-017_PREREGISTRATION.md (committed
before this code was run).  Training era = monthly samples 2017-2021
(target: next-20-trading-day return, cross-sectionally demeaned); the
ridge penalty is chosen ONCE by purged 5-fold time-series CV inside the
training era; the final model is fitted once on the whole era and
frozen.  Evaluation is fully out-of-sample on the second half
2022-01-04..2026-09-25 with EXP-009's yardstick, plus the strict final
block 2024-01-04..2026-09-25 reported separately.  The first half is
the training era itself and is NOT judged.

Run:  python experiments/exp017_ridge.py [cache_dir]
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

CACHE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/jquants_exp002")
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
SECOND_HALF = ("2022-01-04", "2026-09-25")
FINAL_BLOCK = ("2024-01-04", "2026-09-25")
TRAIN_END = pd.Timestamp("2021-12-30")
HORIZON = 20
ALPHAS = [0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0]

FEATURES = ["b_p", "f_roe", "op_ta", "rev_mom", "sales_yoy", "np_yoy",
            "accrual", "lev", "cfo_ta", "div_yield", "size", "mom_6_1",
            "rev_5", "vol_60", "beta_120", "liq", "hi_120", "e_p", "roe"]


def fl(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def fundamental_panels(fins, dates, codes):
    """Per-field point-in-time panels from the raw summary records.

    A disclosure dated D becomes usable at the first trading day >= D
    (the project's convention, cf. exp003.known_from).  General fields
    take the latest record carrying a parseable value.  FY-statement
    quantities (growth, accruals, cash profitability, E/P numerator,
    ROE) are computed at FY record dates from that FY's own statement.
    """
    cols = ["eq", "ta", "op", "f_np", "f_div", "sales_yoy", "np_yoy",
            "accrual", "cfo_ta", "fy_np", "fy_roe"]
    per_col = {c: {} for c in cols}
    for code, recs in fins.items():
        recs = sorted(recs, key=lambda r: (r["DiscDate"],
                                           str(r.get("DiscNo", ""))))
        rows = {}
        fy = {}  # CurFYEn -> (disc_ts, sales, np, cfo, eq, ta)
        for r in recs:
            d = pd.Timestamp(r["DiscDate"])
            row = rows.setdefault(d, {})
            is_fy = str(r.get("CurPerType", "")).endswith("FY")
            for src, dst in (("Eq", "eq"), ("TA", "ta"), ("OP", "op")):
                v = fl(r.get(src))
                if v is not None:
                    row[dst] = v
            v = fl(r.get("NxFNp") if is_fy else r.get("FNP"))
            if v is not None:
                row["f_np"] = v
            v = fl(r.get("NxFDivAnn") if is_fy else r.get("FDivAnn"))
            if v is not None:
                row["f_div"] = v
            if is_fy:
                vals = tuple(fl(r.get(k)) for k in
                             ("Sales", "NP", "CFO", "Eq", "TA"))
                if any(v is not None for v in vals):
                    fy[r.get("CurFYEn", "")] = (d,) + vals
        for en, (d, sales, np_, cfo, eq, ta) in fy.items():
            row = rows.setdefault(d, {})
            try:
                prev_en = "%04d%s" % (int(str(en)[:4]) - 1, str(en)[4:])
            except (TypeError, ValueError):
                prev_en = None
            prev = fy.get(prev_en) if prev_en else None
            if prev is not None:
                if sales is not None and prev[1]:
                    row["sales_yoy"] = sales / prev[1] - 1.0
                if np_ is not None and prev[2]:
                    row["np_yoy"] = np_ / prev[2] - 1.0
            if np_ is not None and cfo is not None and ta:
                row["accrual"] = (np_ - cfo) / ta
            if cfo is not None and ta:
                row["cfo_ta"] = cfo / ta
            if np_ is not None:
                row["fy_np"] = np_
            if np_ is not None and eq:
                row["fy_roe"] = np_ / eq
        if not rows:
            continue
        df = pd.DataFrame.from_dict(rows, orient="index").sort_index()
        idx = dates.union(df.index)
        df = df.reindex(idx).ffill().reindex(dates)
        for c in cols:
            if c in df.columns:
                per_col[c][code] = df[c]
    return {c: pd.DataFrame(d).reindex(columns=codes)
            for c, d in per_col.items()}


def ridge_fit(X, y, alpha):
    k = X.shape[1]
    return np.linalg.solve(X.T @ X + alpha * np.eye(k), X.T @ y)


def main():
    if not (CACHE / "topix.json").exists():
        raise SystemExit(f"cache not found: {CACHE}")
    topix, panel, fins = E3.load(CACHE)
    dates = topix.index
    codes = list(panel["C"].columns)
    c_df = panel["C"]
    c_ff = c_df.ffill()
    o_np = panel["O"].to_numpy()
    c_np = c_ff.to_numpy()
    mktcap = panel["MktCap"] * 1e6  # panel is in millions of yen
    va = panel["Va"]
    fund = fundamental_panels(fins, dates, codes)

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
        "beta_120": logret.rolling(120, min_periods=60).cov(mkt_ret).div(
            mkt_ret.rolling(120, min_periods=60).var(), axis=0),
        "liq": np.log(va.rolling(20, min_periods=10).mean()),
        "hi_120": c_ff / c_ff.rolling(120, min_periods=60).max() - 1.0,
        "e_p": fund["fy_np"] / mktcap,
        "roe": fund["fy_roe"],
    }
    X = {}
    for name in FEATURES:
        if name == "rev_mom":
            r = rev_mom - 0.5
        else:
            r = raw[name].rank(axis=1, pct=True) - 0.5
        X[name] = r.reindex(index=dates, columns=codes).fillna(0.0)
    Xstack = np.stack([X[n].to_numpy() for n in FEATURES])  # (K, T, N)

    # ---- training samples: month-ends 2017-2021 whose 20-day target
    # ends inside the training era
    last_train = int(dates.searchsorted(TRAIN_END, side="right")) - 1
    months = {}
    for i, d in enumerate(dates):
        if d <= TRAIN_END:
            months[(d.year, d.month)] = i
    sample_idx = [months[k] for k in sorted(months)
                  if k >= (2017, 1)]
    sample_idx = [ti for ti in sample_idx if ti + HORIZON <= last_train]
    c_raw = c_df.to_numpy()
    Xs, ys, sidx = [], [], []
    cover = {n: [] for n in FEATURES}
    for ti in sample_idx:
        fwd = c_np[ti + HORIZON] / c_np[ti] - 1.0
        valid = np.isfinite(c_raw[ti]) & np.isfinite(c_raw[ti + HORIZON]) \
            & np.isfinite(fwd)
        y = np.where(valid, fwd, np.nan)
        y = y - np.nanmean(y)
        Xs.append(Xstack[:, ti, :][:, valid].T)
        ys.append(y[valid])
        sidx += [ti] * int(valid.sum())
        for n in FEATURES:
            src = rev_mom if n == "rev_mom" else raw[n]
            cover[n].append(float(src.iloc[ti].notna().mean()))
    Xall = np.vstack(Xs)
    yall = np.concatenate(ys)
    sidx = np.array(sidx)
    uniq = sorted(set(sidx.tolist()))
    blocks = np.array_split(np.array(uniq), 5)
    block_of = {t: k for k, b in enumerate(blocks) for t in b.tolist()}

    cv = {}
    for alpha in ALPHAS:
        r2s = []
        for k, b in enumerate(blocks):
            lo, hi = int(b.min()), int(b.max()) + HORIZON
            val = np.array([block_of[t] == k for t in sidx])
            purge = (sidx <= hi) & (sidx + HORIZON >= lo)
            tr = ~val & ~purge
            beta = ridge_fit(Xall[tr], yall[tr], alpha)
            pred = Xall[val] @ beta
            r2s.append(1.0 - float(((yall[val] - pred) ** 2).sum()
                                   / (yall[val] ** 2).sum()))
        cv[alpha] = float(np.mean(r2s))
    alpha_star = max(cv, key=cv.get)
    beta = ridge_fit(Xall, yall, alpha_star)

    pred_all = np.einsum("k,ktn->tn", beta, Xstack)
    sig = E3.signals(panel, fins, dates)
    comp_np = sig["composite"].to_numpy()

    def run(score_np, period, ck):
        cost, carry = COSTS[ck]
        start = int(dates.searchsorted(pd.Timestamp(period[0])))
        end = int(dates.searchsorted(pd.Timestamp(period[1]),
                                      side="right")) - 1
        curve = E9.simulate(score_np, o_np, c_np, start, end, cost,
                            carry, 1.0, 0.5)
        return E9.stats(pd.Series(curve, index=dates[start:end + 1]))

    out = {"chosen_alpha": alpha_star,
           "cv_r2": {str(k): v for k, v in cv.items()},
           "n_samples": int(len(yall)),
           "n_sample_dates": len(sample_idx),
           "coef": {n: float(b) for n, b in zip(FEATURES, beta)},
           "coverage_train_monthends": {n: float(np.mean(v))
                                        for n, v in cover.items()}}
    fwd20 = np.full_like(c_np, np.nan)
    fwd20[:-HORIZON] = c_np[HORIZON:] / c_np[:-HORIZON] - 1.0
    for label, period in (("second_half", SECOND_HALF),
                          ("final_block", FINAL_BLOCK)):
        out[label] = {
            "ridge": {ck: run(pred_all, period, ck) for ck in COSTS},
            "S": {ck: run(comp_np, period, ck) for ck in COSTS},
        }
        start = int(dates.searchsorted(pd.Timestamp(period[0])))
        end = int(dates.searchsorted(pd.Timestamp(period[1]),
                                      side="right")) - 1
        ics = []
        for t in range(start, end + 1):
            if t + HORIZON >= len(dates):
                break
            a = pd.Series(pred_all[t])
            b = pd.Series(fwd20[t])
            m = np.isfinite(a) & np.isfinite(b) & np.isfinite(c_raw[t])
            if m.sum() >= 30:
                ics.append(a[m].corr(b[m], method="spearman"))
        out[label]["ic_mean"] = float(np.mean(ics)) if ics else None
        out[label]["ic_days"] = len(ics)
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
