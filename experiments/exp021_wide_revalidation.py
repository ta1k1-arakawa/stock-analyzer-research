"""EXP-021: re-validate S and A on the wide (Prime ~1,550 code) cache.

Preregistration: docs/experiments/EXP-021_PREREGISTRATION.md.  Runs the
EXP-009/010 machinery unchanged on the wide cache fetched by
exp021_fetch.py, judges A against S with the preregistered criteria,
and sanity-checks the wide cache by re-running S/A restricted to the
original 306 codes for comparison with the EXP-002 cache figures.

Run:  python experiments/exp021_wide_revalidation.py [wide_cache] [orig_cache]
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

WIDE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/jquants_wide")
ORIG = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/jquants_exp002")
PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}


def evaluate(cache: Path, keep_codes: set | None) -> dict:
    topix, panel, fins = E3.load(cache)
    if keep_codes is not None:
        cols = [c for c in panel["C"].columns if c in keep_codes]
        panel = {k: v[cols] for k, v in panel.items()}
        fins = {c: r for c, r in fins.items() if c in keep_codes}
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)
    mask = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(mask)) / 2.0).where(mask)
    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()
    s_np, a_np = comp.to_numpy(), score_a.to_numpy()
    res = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(s_np, o, c, start, end, cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(a_np, o, c, start, end, cost, carry, 1.0, 0.5), index=idx))
    elig = comp.notna().sum(axis=1)
    diag = {"codes_in_cache": len(codes),
            "eligible_mean_second_half": float(
                elig.loc["2022-01-04":"2026-09-25"].mean()),
            "eligible_max": int(elig.max())}
    return {"res": res, "diag": diag}


def main() -> None:
    orig_codes = {f.stem for f in (ORIG / "bars").glob("*.json")}
    wide = evaluate(WIDE, None)
    check = evaluate(WIDE, orig_codes)

    res = wide["res"]
    g = lambda p, k: res[f"{p}_A_base"][k]  # noqa: E731
    s = lambda p, k: res[f"{p}_S_base"][k]  # noqa: E731
    c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
    c2 = all((g(p, "annual_over_dd") or -9) > (s(p, "annual_over_dd") or -9)
             for p in ("first_half", "second_half"))
    gf, sf = res["full_A_stress"], res["full_S_stress"]
    c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > (sf["annual_over_dd"] or -9)
    verdict = {"A_advantage_holds_on_wide": bool(c1 and c2 and c3),
               "1_A_profit_positive_both_halves": bool(c1),
               "2_A_ratio_gt_S_both_halves": bool(c2),
               "3_full_stress_positive_and_ratio_gt_S": bool(c3)}
    print(json.dumps({"wide": wide, "sanity_306_on_wide": check,
                      "verdict": verdict}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
