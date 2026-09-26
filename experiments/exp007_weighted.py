"""EXP-007: rank-weighted variant (W) of the EXP-003 rotation. Pre-registration: docs/experiments/EXP-007_PREREGISTRATION.md
Usage: python experiments/exp007_weighted.py <cache_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3  # noqa: E402

PERIODS = {"dev_2017_2024": ("2017-01-04", "2024-01-31"), "wf_2019_2026": ("2019-01-04", "2026-09-25")}
COSTS = {"base": 0.0003, "stress": 0.0010}


def multiplier(rank: float) -> float:
    return float(np.clip(2.0 - rank / 20.0, 0.5, 1.5))


def simulate_weighted(score, o, c_ff, start, end, cost, weighted: bool):
    """Same as exp003_rotation.simulate, but each tranche splits its cash by the rank multiplier."""
    step = E3.HOLD_DAYS // E3.N_TRANCHES
    holdings = [dict() for _ in range(E3.N_TRANCHES)]
    cash = [E3.BUDGET / E3.N_TRANCHES] * E3.N_TRANCHES
    values = []
    for t in range(start, end + 1):
        i = t - start
        due = range(E3.N_TRANCHES) if i == 0 else ([(i % E3.HOLD_DAYS) // step] if i % step == 0 else [])
        for k in due:
            cash[k] += sum(sh * (o[t, j] if o[t, j] > 0 else c_ff[t - 1, j]) * (1 - cost) for j, sh in holdings[k].items())
            others = set().union(*(holdings[m] for m in range(E3.N_TRANCHES) if m != k))
            s = score[t - 1]
            ok = np.isfinite(s)
            rank = np.full(len(s), np.nan)
            order_all = np.flatnonzero(ok)[np.lexsort((np.flatnonzero(ok), -s[ok]))]
            rank[order_all] = np.arange(1, len(order_all) + 1)
            cand = [j for j in order_all if o[t, j] > 0 and j not in others][:E3.PER_TRANCHE]
            holdings[k] = {}
            if cand:
                w = np.array([multiplier(rank[j]) if weighted else 1.0 for j in cand])
                w = w / w.sum()
                holdings[k] = {j: cash[k] * wj / (o[t, j] * (1 + cost)) for j, wj in zip(cand, w)}
                cash[k] = 0.0
        values.append(sum(cash) + sum(sh * c_ff[t, j] for h in holdings for j, sh in h.items()))
    values[-1] = sum(cash) + sum(sh * c_ff[end, j] * (1 - cost) for h in holdings for j, sh in h.items())
    return np.array(values)


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    score = E3.signals(panel, fins, dates)["composite"].to_numpy()
    o, c = panel["O"].to_numpy(), panel["C"].ffill().to_numpy()
    res, verdict = {}, {}
    for pname, (a, b) in PERIODS.items():
        start, end = int(dates.searchsorted(pd.Timestamp(a))), int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        for cname, cost in COSTS.items():
            for name, weighted in (("R", False), ("W", True)):
                v = pd.Series(simulate_weighted(score, o, c, start, end, cost, weighted), index=dates[start:end + 1])
                res[f"{pname}_{name}_{cname}"] = {"profit": round(float(v.iloc[-1] - E3.BUDGET)),
                                                  "max_dd_pct": round(float((v / v.cummax() - 1).min()) * 100, 2)}
        g = lambda n, cst: res[f"{pname}_{n}_{cst}"]  # noqa: E731
        verdict[pname] = {
            "1_base_W_ge_R": g("W", "base")["profit"] >= g("R", "base")["profit"],
            "2_stress_W_ge_R": g("W", "stress")["profit"] >= g("R", "stress")["profit"],
            "3_dd_not_5pt_worse": g("W", "base")["max_dd_pct"] >= g("R", "base")["max_dd_pct"] - 5,
        }
    res["verdict"] = verdict
    res["adopt_W_for_real_money"] = all(all(v.values()) for v in verdict.values())
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
