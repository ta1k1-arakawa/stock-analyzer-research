"""EXP-026: exclude margin-crowded names from A's long side.

Preregistration: docs/experiments/EXP-026_PREREGISTRATION.md

Crowding = weekly long margin volume (shares) / shares outstanding
(market cap / close), made usable from the first trading day at least
4 calendar days after the weekly reference date and forward-filled.
Names whose crowding ranks in the top decile of A's valid set that day
are masked from the LONG side only; the short side keeps A's score
(EXP-013's two-sided engine). Judged against A (recomputed; S also
reported) by the standard three criteria.

Usage:
    python experiments/exp026_margin.py <exp002_cache> <margin_dir>
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


def crowding_frame(margin_dir: Path, dates, codes, panel) -> pd.DataFrame:
    shares = (panel["MktCap"] * 1e6) / panel["C"]
    crowd = pd.DataFrame(np.nan, index=dates, columns=codes)
    for code in codes:
        f = margin_dir / f"{code}.json"
        if not f.exists():
            continue
        rows = json.loads(f.read_text())
        if not rows:
            continue
        s = pd.Series({pd.Timestamp(r["Date"]): r.get("LongVol")
                       for r in rows}).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        usable = s.copy()
        usable.index = [dates[dates.searchsorted(d + pd.Timedelta(
            days=LAG_DAYS), side="left")] if (dates.searchsorted(
                d + pd.Timedelta(days=LAG_DAYS), side="left") < len(dates))
            else pd.NaT for d in s.index]
        usable = usable[usable.index.notna()]
        # Recent rows can be near-daily; several may map to the same
        # usable day (all after the evaluation window) — keep the last.
        usable = usable[~usable.index.duplicated(keep="last")]
        if len(usable) == 0:
            continue
        daily = usable.reindex(dates, method="ffill")
        so = shares[code].reindex(dates)
        crowd[code] = (daily / so).to_numpy()
    return crowd


def main(cache: Path, margin_dir: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)

    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid)) / 2.0) \
        .where(valid)

    crowd = crowding_frame(margin_dir, dates, codes, panel)
    crowd_rank = crowd.where(valid).rank(axis=1, pct=True)
    excluded = crowd_rank >= TOP_DECILE
    long_mgn = score_a.mask(excluded)

    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    short_a = score_a.to_numpy()

    res: dict = {}
    diag: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        ex = excluded.to_numpy()[start:end + 1]
        va = valid.to_numpy()[start:end + 1]
        diag[pname] = {
            "excluded_share_of_valid": float((ex & va).sum()
                                             / max(va.sum(), 1)),
            "crowding_coverage_of_valid": float(
                (crowd.notna().to_numpy()[start:end + 1] & va).sum()
                / max(va.sum(), 1)),
        }
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(comp.to_numpy(), o, c_ff, start, end, cost,
                            carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(short_a, o, c_ff, start, end, cost, carry,
                            1.0, 0.5), index=idx))
            res[f"{pname}_A_mgn_{cname}"] = E9.stats(pd.Series(
                E13.simulate2(long_mgn.to_numpy(), short_a, o, c_ff, start,
                              end, cost, carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_mgn_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_mgn_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_mgn_stress"]["profit"] > 0
            and ratio("full_A_mgn_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
