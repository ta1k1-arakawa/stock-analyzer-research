"""EXP-008: inverse-volatility split inside each tranche (V) vs equal split (R).
Pre-registration: docs/experiments/EXP-008_PREREGISTRATION.md. Usage: python experiments/exp008_vol_weight.py <cache_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3  # noqa: E402

PERIODS = {"first_half_2017_2021": ("2017-01-04", "2021-12-30"), "second_half_2022_2026": ("2022-01-04", "2026-09-25")}
COSTS = {"base": 0.0003, "stress": 0.0010}


def simulate(score, vol, o, c_ff, start, end, cost, inv_vol: bool):
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
            ok = np.flatnonzero(np.isfinite(s))
            order = ok[np.lexsort((ok, -s[ok]))]
            cand = [j for j in order if o[t, j] > 0 and j not in others][:E3.PER_TRANCHE]
            holdings[k] = {}
            if cand:
                w = np.ones(len(cand))
                if inv_vol:
                    v = np.array([vol[t - 1, j] for j in cand])
                    if np.all(np.isfinite(v) & (v > 0)):
                        w = 1.0 / v
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
    vol = panel["C"].pct_change(fill_method=None).rolling(60, min_periods=40).std().to_numpy()
    o, c = panel["O"].to_numpy(), panel["C"].ffill().to_numpy()
    res = {}
    for pname, (a, b) in PERIODS.items():
        start, end = int(dates.searchsorted(pd.Timestamp(a))), int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        for cname, cost in COSTS.items():
            for name, iv in (("R", False), ("V", True)):
                v = pd.Series(simulate(score, vol, o, c, start, end, cost, iv), index=dates[start:end + 1])
                res[f"{pname}_{name}_{cname}"] = {"profit": round(float(v.iloc[-1] - E3.BUDGET)),
                                                  "max_dd_pct": round(float((v / v.cummax() - 1).min()) * 100, 2)}
    g = lambda n, c: res[f"second_half_2022_2026_{n}_{c}"]  # noqa: E731
    res["verdict_second_half"] = {
        "1_base_V_ge_97pct_R": g("V", "base")["profit"] >= 0.97 * g("R", "base")["profit"],
        "2_dd_V_smaller": g("V", "base")["max_dd_pct"] > g("R", "base")["max_dd_pct"],
        "3_stress_V_ge_97pct_R": g("V", "stress")["profit"] >= 0.97 * g("R", "stress")["profit"],
    }
    res["adopt_V"] = all(res["verdict_second_half"].values())
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
