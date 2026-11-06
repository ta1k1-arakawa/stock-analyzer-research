"""EXP-097: operating-profit-forecast habit discount (see EXP-097_PREREGISTRATION.md).

For each firm, the initial operating-profit forecast for fiscal year t+1 is
NxFOP in the FY-t statement; the actual is OP in the FY-(t+1)
statement. bias = (initial - actual) / |actual|, winsorised to +-2. habit =
mean of the last 3 completed biases (>= 2 required). An episode runs from
the FY results disclosure until the first later disclosure that changes
the coming year's operating-profit forecast (FOP), or 3 months. During an
episode with habit > +0.10 the name's long score gets -0.10; shorts are
plain A. Judged by the standard three criteria vs A.

Usage: exp097_op_habit.py <jquants_cache_dir>"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3      # noqa: E402
import exp009_long_short as E9    # noqa: E402
import exp010_earnings_momentum as E10  # noqa: E402
import exp013_vol_managed as E13  # noqa: E402

PERIODS = {"first_half": ("2017-01-04", "2021-12-30"),
           "second_half": ("2022-01-04", "2026-09-25"),
           "full": ("2017-01-04", "2026-09-25")}
COSTS = E9.COSTS
HABIT_NEED = 0.03


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def episodes(fins: dict) -> dict:
    """code -> [(start, end_exclusive, habit)] for operating-profit episodes."""
    out: dict[str, list] = {}
    for code, recs in fins.items():
        rs = sorted(recs, key=lambda r: (str(r.get("DiscDate", "")), str(r.get("DocType", ""))))
        fy = [r for r in rs if r.get("CurPerType") == "FY"
              and "FinancialStatements" in str(r.get("DocType", ""))]
        if len(fy) < 3:
            continue
        biases: list[float] = []
        eps = []
        for i, r in enumerate(fy):
            if i + 1 >= len(fy):
                break
            actual_next = num(fy[i + 1].get("OP"))
            init_next = num(r.get("NxFOP"))
            start = pd.Timestamp(str(r.get("DiscDate", ""))[:10])
            if not np.isnan(actual_next) and actual_next != 0 and not np.isnan(init_next):
                biases.append(float(np.clip((init_next - actual_next) / abs(actual_next), -2, 2)))
            if len(biases) >= 2 and not np.isnan(init_next):
                habit = float(np.mean(biases[-3:]))
                end = start + pd.DateOffset(months=3)
                for r2 in rs:
                    d2 = pd.Timestamp(str(r2.get("DiscDate", ""))[:10])
                    if d2 <= start:
                        continue
                    f = num(r2.get("FOP"))
                    if not np.isnan(f) and abs(f - init_next) > 1e-9:
                        end = min(end, d2)
                        break
                    if d2 >= end:
                        break
                eps.append((start, end, habit))
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

    pen = pd.DataFrame(0.0, index=dates, columns=codes)
    eps = episodes(fins)
    for code, lst in eps.items():
        if code not in codes:
            continue
        for start, end, habit in lst:
            if habit > HABIT_NEED:
                rows = (dates >= start) & (dates < end)
                pen.loc[rows, code] = -0.10
    concurrent = (pen < 0).sum(axis=1)
    median_flagged = float(concurrent[concurrent > 0].median()) if (concurrent > 0).any() else 0.0
    long_dh = (score_a + pen).where(mask)

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()
    s_np, a_np = comp.to_numpy(), score_a.to_numpy()
    dh_l = long_dh.to_numpy()

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
            res[f"{pname}_Ash_{cname}"] = E9.stats(pd.Series(
                np.asarray(E13.simulate2(dh_l, a_np, o, c, start, end, cost, carry, 1.0, 0.5),
                           dtype=float), index=idx))

    g = lambda p, k: res[f"{p}_Ash_base"][k]  # noqa: E731
    av = lambda p, k: res[f"{p}_A_base"][k]  # noqa: E731
    c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
    c2 = all((g(p, "annual_over_dd") or -9) > (av(p, "annual_over_dd") or -9)
             for p in ("first_half", "second_half"))
    gf, af = res["full_Ash_stress"], res["full_A_stress"]
    c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > (af["annual_over_dd"] or -9)
    verdict = {"1_profit_positive_both_halves": bool(c1),
               "2_ratio_gt_A_both_halves": bool(c2),
               "3_full_stress_positive_and_ratio_gt_A": bool(c3),
               "promising": bool(c1 and c2 and c3),
               "gate_median_flagged_ge5": bool(median_flagged >= 5)}
    print(json.dumps({"res": res, "verdict": verdict,
                      "diag": {"episodes": int(sum(len(v) for v in eps.values())),
                               "median_flagged": median_flagged}},
                     ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
