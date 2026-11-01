"""EXP-044: JPY-gate-triggered Nikkei 225 put spread overlay on A.

Preregistration: docs/experiments/EXP-044_PREREGISTRATION.md

The gate is EXP-038's (USD/JPY 20-trading-day change <= -5%,
lagged one day, on for 10 trading days). On the first day of each
gate cluster, if no spread is open, buy one unit of a put spread:
earliest contract month whose SQ is at least 21 calendar days
out; long strike = highest listed strike <= 0.97 x underlying;
short strike = highest listed strike <= long strike - 500.
Purchase price = settlement prices with 10 points adverse
slippage per leg. The spread is marked daily at settlement
prices and realised at the last trading day's settlement.
Combined equity = A's equity + overlay contribution
(-premium paid + current spread value). Judged against A by the
standard three criteria (stress applies the stock-side stress
costs with the same overlay).

Data prepared by the EXP-044 fetch (selection.json + daily leg
settlements) in the run directory passed as argv[2].

Usage:
    python experiments/exp044_put_spread.py <cache_dir> <run_dir>
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

PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
SLIP = 10.0
MULT = 1000.0


def main(cache: Path, run_dir: Path) -> None:
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
    snp = score_a.to_numpy()

    selection = json.loads((run_dir / "selection.json").read_text())
    legs_dir = run_dir / "data" / "legs"

    def leg_settles(code: str, day: pd.Timestamp):
        fp = legs_dir / f"{day.date()}.json"
        if not fp.exists():
            return None
        return json.loads(fp.read_text()).get(code)

    # Build the overlay contribution series over all dates.
    overlay = np.zeros(len(dates))
    episodes = []
    open_until = -1
    for sel in selection:
        buy = pd.Timestamp(sel["buy_date"])
        bi = int(dates.searchsorted(buy))
        if bi <= open_until:
            episodes.append({**sel, "skipped": "already_open"})
            continue
        premium = ((sel["long"]["settle"] + SLIP)
                   - (sel["short"]["settle"] - SLIP)) * MULT
        sqd = pd.Timestamp(sel["sqd"])
        ei = int(dates.searchsorted(sqd, side="right")) - 1
        last_long = sel["long"]["settle"]
        last_short = sel["short"]["settle"]
        realised = None
        for t in range(bi, ei + 1):
            lv = leg_settles(sel["long"]["code"], dates[t])
            sv = leg_settles(sel["short"]["code"], dates[t])
            if lv is not None:
                last_long = lv
            if sv is not None:
                last_short = sv
            overlay[t] += -premium + (last_long - last_short) * MULT
            realised = (last_long - last_short) * MULT
        for t in range(ei + 1, len(dates)):
            overlay[t] += -premium + realised
        open_until = ei
        episodes.append({**sel, "premium_yen": premium,
                         "realised_yen": realised,
                         "net_yen": realised - premium})

    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        s0 = int(dates.searchsorted(pd.Timestamp(a)))
        e0 = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[s0:e0 + 1]
        ov = pd.Series(overlay[s0:e0 + 1], index=idx)
        for cname, (cost, carry) in COSTS.items():
            base_curve = pd.Series(
                E9.simulate(snp, o_np, c_np, s0, e0, cost, carry,
                            1.0, 0.5), index=idx)
            res[f"{pname}_A_{cname}"] = E9.stats(base_curve)
            res[f"{pname}_A_ps_{cname}"] = E9.stats(base_curve
                                                   + ov.to_numpy())

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_ps_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_ps_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_ps_stress"]["profit"] > 0
            and ratio("full_A_ps_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict,
                      "episodes": episodes},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
