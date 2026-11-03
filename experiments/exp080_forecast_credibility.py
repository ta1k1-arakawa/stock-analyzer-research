"""EXP-080: forecast-credibility haircut on A's forecast-ROE.

Preregistration: docs/experiments/EXP-080_PREREGISTRATION.md
Variant A_fc = A with exactly two changes:
  1. During the initial-forecast window (from the FY results disclosure
     that sets NxFNp until the first later disclosure that changes the
     forecast, or 3 months, whichever first), the forecast used in the
     ROE component is divided by (1 + habit), habit = the firm's mean
     initial-forecast bias over its last 3 completed fiscal years
     (bias = (initial forecast - actual)/|actual|, winsorised +/-2,
     habit clipped to [-0.5, +1.0], >= 2 completed years required).
  2. Loss-avoidance names (prior FY NP < 0, initial forecast > 0 but
     < 1% of prior FY sales) are excluded from the LONG side during
     the same window. Short side unchanged.
Judged vs A by the standard 3 criteria. S and A recomputed in-script.
Usage: python experiments/exp080_forecast_credibility.py <cache_dir>
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

PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}


def num(x):
    try:
        return float(x)
    except Exception:
        return np.nan


def episodes(fins: dict) -> dict:
    """code -> list of (start_disc, end_disc, habit, loss_avoidance)."""
    out = {}
    for code, recs in fins.items():
        rows = []
        for r in recs:
            d = r.get("DiscDate")
            if not d:
                continue
            is_fy = r.get("CurPerType") == "FY" and "FinancialStatements" in str(r.get("DocType"))
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


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    mask = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(mask)) / 2.0).where(mask)

    eq, npf = E3.fundamentals(fins, dates)
    eq = eq.reindex(columns=codes)
    npf = npf.reindex(columns=codes)
    npf_adj = npf.copy()
    la_mask = pd.DataFrame(False, index=dates, columns=codes)
    eps = episodes(fins)
    n_adj_days = 0
    for code, lst in eps.items():
        if code not in codes:
            continue
        for start, end, habit, la in lst:
            rows = (dates >= start) & (dates < end)
            if not rows.any():
                continue
            f = 1.0 + float(np.clip(habit, -0.5, 1.0))
            npf_adj.loc[rows, code] = npf.loc[rows, code] / f
            n_adj_days += int(rows.sum())
            if la:
                la_mask.loc[rows, code] = True
    mcap = panel["MktCap"] * 1e6
    liq = panel["Va"].fillna(0.0).rolling(E3.LIQ_DAYS, min_periods=E3.LIQ_DAYS).mean()
    ok = (liq >= E3.LIQ_MIN) & (mcap > 0) & (eq > 0) & npf_adj.notna() & panel["C"].notna()
    comp_fc = (eq / mcap).where(ok).rank(axis=1, pct=True) + \
        (npf_adj / eq).where(ok).rank(axis=1, pct=True)
    mask_fc = comp_fc.notna()
    score_fc = ((comp_fc.rank(axis=1, pct=True) + mom.where(mask_fc)) / 2.0).where(mask_fc)
    long_fc = score_fc.where(~la_mask)

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()
    s_np = comp.to_numpy()
    a_np = score_a.to_numpy()
    fc_l, fc_s = long_fc.to_numpy(), score_fc.to_numpy()

    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(s_np, o, c, start, end, cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(a_np, o, c, start, end, cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_Afc_{cname}"] = E9.stats(pd.Series(
                np.asarray(E13.simulate2(fc_l, fc_s, o, c, start, end, cost, carry, 1.0, 0.5),
                           dtype=float), index=idx))

    g = lambda p, k: res[f"{p}_Afc_base"][k]  # noqa: E731
    a = lambda p, k: res[f"{p}_A_base"][k]  # noqa: E731
    c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
    c2 = all((g(p, "annual_over_dd") or -9) > (a(p, "annual_over_dd") or -9)
             for p in ("first_half", "second_half"))
    gf, af = res["full_Afc_stress"], res["full_A_stress"]
    c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > (af["annual_over_dd"] or -9)
    verdict = {"1_profit_positive_both_halves": bool(c1),
               "2_ratio_gt_A_both_halves": bool(c2),
               "3_full_stress_positive_and_ratio_gt_A": bool(c3),
               "promising": bool(c1 and c2 and c3)}
    diag = {"episodes": int(sum(len(v) for v in eps.values())),
            "adjusted_code_days": n_adj_days,
            "la_code_days": int(la_mask.to_numpy().sum())}
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
