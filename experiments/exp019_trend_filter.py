"""EXP-019: TOPIX trend filter on the EXP-010 A book.

Preregistration: docs/experiments/EXP-019_PREREGISTRATION.md (committed
before this code was run).  When TOPIX closes below its 200-day moving
average, A's score rows are masked to NaN so the EXP-009 engine opens
no new positions (existing positions still exit on schedule); judged
against A by the standard 3 criteria.

Run:  python experiments/exp019_trend_filter.py [cache_dir]
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
PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
MA_DAYS = 200


def main(cache: Path) -> None:
    if not (cache / "topix.json").exists():
        raise SystemExit(f"cache not found: {cache}")
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)
    mask = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(mask)) / 2.0).where(mask)

    ma = topix["C"].rolling(MA_DAYS).mean()
    on = (topix["C"] >= ma).where(ma.notna(), True)
    score_f = score_a.where(on)

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()
    a_np = score_a.to_numpy()
    f_np = score_f.to_numpy()

    res: dict = {}
    off_share: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        off_share[pname] = float((~on.iloc[start:end + 1]).mean())
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(a_np, o, c, start, end, cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_F_{cname}"] = E9.stats(pd.Series(
                E9.simulate(f_np, o, c, start, end, cost, carry, 1.0, 0.5), index=idx))

    g = lambda p, k: res[f"{p}_F_base"][k]  # noqa: E731
    s = lambda p, k: res[f"{p}_A_base"][k]  # noqa: E731
    c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
    c2 = all((g(p, "annual_over_dd") or -9) > (s(p, "annual_over_dd") or -9)
             for p in ("first_half", "second_half"))
    gf, sf = res["full_F_stress"], res["full_A_stress"]
    c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > (sf["annual_over_dd"] or -9)
    verdict = {"F": {
        "1_profit_positive_both_halves": bool(c1),
        "2_ratio_gt_A_both_halves": bool(c2),
        "3_full_stress_positive_and_ratio_gt_A": bool(c3),
        "promising": bool(c1 and c2 and c3),
    }}
    print(json.dumps({"res": res, "verdict": verdict,
                      "off_share": off_share}, ensure_ascii=False))


if __name__ == "__main__":
    main(CACHE)
