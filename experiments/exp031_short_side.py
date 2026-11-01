"""EXP-031: short-side redesign of A.

Preregistration: docs/experiments/EXP-031_PREREGISTRATION.md

Long side is A, unchanged; the short side is redesigned two ways,
run through EXP-013's two-sided engine:
  A_s1  squeeze avoidance: A's short score with the top decile of
        short-margin crowding (weekly ShrtVol / shares outstanding,
        +4 calendar day publication lag, EXP-026's mapping and cached
        data) masked out within A's valid set.
  A_s2  downgrade-weighted shorts: short selection score
        (composite rank + 2 * revision-momentum rank) / 3.
Each variant is judged against A (recomputed; S also reported) by
the standard three criteria.

Usage:
    python experiments/exp031_short_side.py <exp002_cache> <margin_dir>
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
LAG_DAYS = 4
TOP_DECILE = 0.90


def short_crowding_frame(margin_dir: Path, dates, codes, panel):
    """Weekly short margin volume / shares outstanding, usable from
    the first trading day >= reference date + LAG_DAYS, forward-filled
    (EXP-026's mapping, ShrtVol instead of LongVol)."""
    shares = (panel["MktCap"] * 1e6) / panel["C"]
    crowd = pd.DataFrame(np.nan, index=dates, columns=codes)
    for code in codes:
        f = margin_dir / f"{code}.json"
        if not f.exists():
            continue
        rows = json.loads(f.read_text())
        if not rows:
            continue
        s = pd.Series({pd.Timestamp(r["Date"]): r.get("ShrtVol")
                       for r in rows}).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        usable = s.copy()
        usable.index = [
            dates[dates.searchsorted(d + pd.Timedelta(days=LAG_DAYS),
                                     side="left")]
            if dates.searchsorted(d + pd.Timedelta(days=LAG_DAYS),
                                  side="left") < len(dates) else pd.NaT
            for d in s.index]
        usable = usable[usable.index.notna()]
        usable = usable[~usable.index.duplicated(keep="last")]
        if len(usable) == 0:
            continue
        daily = usable.reindex(dates, method="ffill")
        so = shares[code].reindex(dates)
        crowd[code] = (daily / so).to_numpy()
    return crowd


def judge(res: dict, variant: str) -> dict:
    def ratio(k):
        return res[k]["annual_over_dd"]
    v = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_{variant}_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_{variant}_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res[f"full_{variant}_stress"]["profit"] > 0
            and ratio(f"full_{variant}_stress") > ratio("full_A_stress")),
    }
    v["promising"] = bool(all(v.values()))
    return v


def main(cache: Path, margin_dir: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)

    valid = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    score_a = ((comp_r + mom.where(valid)) / 2.0).where(valid)

    crowd = short_crowding_frame(margin_dir, dates, codes, panel)
    crowd_rank = crowd.where(valid).rank(axis=1, pct=True)
    short_s1 = score_a.mask(crowd_rank >= TOP_DECILE)
    short_s2 = ((comp_r + 2.0 * mom.where(valid)) / 3.0).where(valid)

    win = (dates >= pd.Timestamp("2017-01-04")) \
        & (dates <= pd.Timestamp("2026-09-25"))
    diag = {
        "crowding_coverage_median": float(
            (crowd.notna() & valid).sum(axis=1)[win].div(
                valid.sum(axis=1)[win]).median()),
        "excluded_share_s1": float(
            ((crowd_rank >= TOP_DECILE) & valid).sum(axis=1)[win].div(
                valid.sum(axis=1)[win]).mean()),
    }

    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    a_np = score_a.to_numpy()
    variants = {"A_s1": short_s1.to_numpy(), "A_s2": short_s2.to_numpy()}
    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(comp.to_numpy(), o, c_ff, start, end, cost,
                            carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(a_np, o, c_ff, start, end, cost, carry,
                            1.0, 0.5), index=idx))
            for vname, s_np in variants.items():
                res[f"{pname}_{vname}_{cname}"] = E9.stats(pd.Series(
                    E13.simulate2(a_np, s_np, o, c_ff, start, end, cost,
                                  carry, 1.0, 0.5), index=idx))

    verdicts = {v: judge(res, v) for v in variants}
    print(json.dumps({"res": res, "verdicts": verdicts, "diag": diag},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
