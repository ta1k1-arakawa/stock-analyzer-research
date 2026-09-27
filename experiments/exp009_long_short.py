"""EXP-009: long the rule's top names, short its bottom names (2,000,000 yen). Pre-registration: docs/experiments/EXP-009_PREREGISTRATION.md
Usage: python experiments/exp009_long_short.py <cache_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3  # noqa: E402

BUDGET = 2_000_000
PERIODS = {"first_half": ("2017-01-04", "2021-12-30"), "second_half": ("2022-01-04", "2026-09-25"),
           "full": ("2017-01-04", "2026-09-25")}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}  # (one-way trading cost, annual short carry)
NT, PT, HOLD = E3.N_TRANCHES, E3.PER_TRANCHE, E3.HOLD_DAYS


def simulate(score, o, c_ff, start, end, cost, carry, long_frac, short_frac):
    step = HOLD // NT
    longs = [dict() for _ in range(NT)]
    lcash = [BUDGET * long_frac / NT] * NT
    idle = BUDGET * (1 - long_frac)          # cash not used by the long book (neutral variant)
    shorts = [dict() for _ in range(NT)]     # j -> (entry price net of cost, notional)
    realized = 0.0
    values = []

    def short_unreal(t):
        return sum(n * (1 - c_ff[t, j] / p) for s in shorts for j, (p, n) in s.items())

    def equity(t):
        return idle + sum(lcash) + sum(sh * c_ff[t, j] for h in longs for j, sh in h.items()) + realized + short_unreal(t)

    for t in range(start, end + 1):
        i = t - start
        due = range(NT) if i == 0 else ([(i % HOLD) // step] if i % step == 0 else [])
        s = score[t - 1]
        ok = np.flatnonzero(np.isfinite(s))
        order = ok[np.lexsort((ok, -s[ok]))]
        eq_prev = equity(t - 1) if i > 0 else BUDGET
        for k in due:
            # long leg (identical to exp003_rotation.simulate)
            lcash[k] += sum(sh * (o[t, j] if o[t, j] > 0 else c_ff[t - 1, j]) * (1 - cost) for j, sh in longs[k].items())
            held = set().union(*(longs[m] for m in range(NT) if m != k))
            cand = [j for j in order if o[t, j] > 0 and j not in held][:PT]
            longs[k] = {}
            if cand:
                longs[k] = {j: lcash[k] / len(cand) / (o[t, j] * (1 + cost)) for j in cand}
                lcash[k] = 0.0
            # short leg: close (buy back at the open), then short the bottom names
            if short_frac > 0:
                for j, (p, n) in shorts[k].items():
                    px = (o[t, j] if o[t, j] > 0 else c_ff[t - 1, j]) * (1 + cost)
                    realized += n * (1 - px / p)
                held_s = set().union(*(shorts[m] for m in range(NT) if m != k))
                cand_s = [j for j in order[::-1] if o[t, j] > 0 and j not in held_s][:PT]
                notional = eq_prev * short_frac / NT
                shorts[k] = {j: (o[t, j] * (1 - cost), notional / len(cand_s)) for j in cand_s} if cand_s else {}
        realized -= sum(n for sh in shorts for _, n in sh.values()) * carry / 245
        values.append(equity(t))
    # close everything at the last close
    last = end
    final = idle + sum(lcash) + sum(sh * c_ff[last, j] * (1 - cost) for h in longs for j, sh in h.items()) + realized \
        + sum(n * (1 - c_ff[last, j] * (1 + cost) / p) for s in shorts for j, (p, n) in s.items())
    values[-1] = final
    return np.array(values)


def stats(v: pd.Series) -> dict:
    years = (v.index[-1] - v.index[0]).days / 365.25
    ann = (v.iloc[-1] / BUDGET) ** (1 / years) - 1
    dd = float((v / v.cummax() - 1).min())
    return {"profit": round(float(v.iloc[-1] - BUDGET)), "annual_pct": round(ann * 100, 2),
            "max_dd_pct": round(dd * 100, 2), "annual_over_dd": round(ann / abs(dd), 3) if dd < 0 else None}


def main(cache: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    score = E3.signals(panel, fins, dates)["composite"].to_numpy()
    o, c = panel["O"].to_numpy(), panel["C"].ffill().to_numpy()
    res = {}
    for pname, (a, b) in PERIODS.items():
        start, end = int(dates.searchsorted(pd.Timestamp(a))), int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            for name, lf, sf in (("R", 1.0, 0.0), ("LS", 1.0, 0.5), ("N_neutral", 0.5, 0.5)):
                res[f"{pname}_{name}_{cname}"] = stats(pd.Series(simulate(score, o, c, start, end, cost, carry, lf, sf), index=idx))
        tp = topix["C"].iloc[end] / topix["O"].iloc[start] - 1
        res[f"{pname}_TOPIX"] = {"profit": round(float(tp) * BUDGET)}
    g = lambda p, n, c="base": res[f"{p}_{n}_{c}"]  # noqa: E731
    res["verdict"] = {
        "1_LS_profit_positive_both_halves": bool(all(g(p, "LS")["profit"] > 0 for p in ("first_half", "second_half"))),
        "2_LS_ratio_gt_R_both_halves": bool(all(g(p, "LS")["annual_over_dd"] > g(p, "R")["annual_over_dd"] for p in ("first_half", "second_half"))),
        "3_full_stress_positive_and_ratio_gt_R": bool(g("full", "LS", "stress")["profit"] > 0
            and g("full", "LS", "stress")["annual_over_dd"] > g("full", "R", "stress")["annual_over_dd"]),
    }
    res["promising"] = bool(all(res["verdict"].values()))
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
