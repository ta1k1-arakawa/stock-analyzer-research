"""EXP-038: JPY-shock gate on A.

Preregistration: docs/experiments/EXP-038_PREREGISTRATION.md

Gate: when USD/JPY (FRED DEXJPUS, forward-filled onto TSE dates
and lagged one trading day) has fallen >= 5% over 20 trading days,
the gate is ON for the next 10 trading days. While ON, each
tranche's scheduled rebalance invests only half of its long cash
(the rest stays parked as cash inside the tranche and is
reinvested when the gate is off again); shorts are unchanged.
This is the engine-consistent reading of "long 0.5": in
exp009's accounting long_frac acts through tranche cash at
rebalance. Engine identity (gate never on == exp009 simulate at
1.0 / 0.5) is verified in-run and printed.

Usage:
    python experiments/exp038_jpy_gate.py <cache_dir> <usdjpy_csv>
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

BUDGET = E9.BUDGET
NT, PT, HOLD = E9.NT, E9.PT, E9.HOLD
PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
THRESH, WINDOW = -0.05, 10


def simulate_gate(score, o, c_ff, start, end, cost, carry, gate_on):
    step = HOLD // NT
    longs = [dict() for _ in range(NT)]
    lcash = [BUDGET * 1.0 / NT] * NT
    idle = 0.0
    shorts = [dict() for _ in range(NT)]
    realized = 0.0
    values = []

    def short_unreal(t):
        return sum(n * (1 - c_ff[t, j] / p)
                   for s in shorts for j, (p, n) in s.items())

    def equity(t):
        return idle + sum(lcash) + sum(
            sh * c_ff[t, j] for h in longs for j, sh in h.items()) \
            + realized + short_unreal(t)

    for t in range(start, end + 1):
        i = t - start
        due = range(NT) if i == 0 else (
            [(i % HOLD) // step] if i % step == 0 else [])
        s = score[t - 1]
        ok = np.flatnonzero(np.isfinite(s))
        order = ok[np.lexsort((ok, -s[ok]))]
        eq_prev = equity(t - 1) if i > 0 else BUDGET
        for k in due:
            lcash[k] += sum(
                sh * (o[t, j] if o[t, j] > 0 else c_ff[t - 1, j])
                * (1 - cost) for j, sh in longs[k].items())
            held = set().union(*(longs[m] for m in range(NT)
                                 if m != k))
            cand = [j for j in order
                    if o[t, j] > 0 and j not in held][:PT]
            longs[k] = {}
            if cand:
                f = 0.5 if gate_on[t] else 1.0
                total = lcash[k]
                longs[k] = {j: total * f / len(cand)
                            / (o[t, j] * (1 + cost)) for j in cand}
                lcash[k] = total * (1.0 - f)
            else:
                lcash[k] = lcash[k]
            for j, (p, n) in shorts[k].items():
                px = (o[t, j] if o[t, j] > 0 else c_ff[t - 1, j]) \
                    * (1 + cost)
                realized += n * (1 - px / p)
            held_s = set().union(*(shorts[m] for m in range(NT)
                                   if m != k))
            cand_s = [j for j in order[::-1]
                      if o[t, j] > 0 and j not in held_s][:PT]
            notional = eq_prev * 0.5 / NT
            shorts[k] = {j: (o[t, j] * (1 - cost),
                             notional / len(cand_s))
                         for j in cand_s} if cand_s else {}
        realized -= sum(n for sh in shorts
                        for _, n in sh.values()) * carry / 245
        values.append(equity(t))
    last = end
    final = idle + sum(lcash) + sum(
        sh * c_ff[last, j] * (1 - cost)
        for h in longs for j, sh in h.items()) + realized + sum(
        n * (1 - c_ff[last, j] * (1 + cost) / p)
        for s in shorts for j, (p, n) in s.items())
    values[-1] = final
    return np.array(values)


def gate_schedule(dates: pd.DatetimeIndex, fx_csv: Path) -> np.ndarray:
    fx = pd.read_csv(fx_csv, parse_dates=["observation_date"])
    fx = fx[fx["DEXJPUS"] != "."]
    fx["DEXJPUS"] = fx["DEXJPUS"].astype(float)
    s = fx.set_index("observation_date")["DEXJPUS"] \
        .reindex(dates, method="ffill")
    s = s.shift(1)  # 1-trading-day lag (registered)
    chg = s / s.shift(20) - 1.0
    trig = (chg <= THRESH).to_numpy()
    gate = np.zeros(len(dates), dtype=bool)
    for t in np.flatnonzero(trig):
        gate[t + 1: t + 1 + WINDOW] = True
    return gate


def main(cache: Path, fx_csv: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid)) / 2.0) \
        .where(valid)
    gate = gate_schedule(dates, fx_csv)

    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    snp = score_a.to_numpy()

    # identity check: gate forced off must reproduce exp009 simulate
    start = int(dates.searchsorted(pd.Timestamp("2017-01-04")))
    end = int(dates.searchsorted(pd.Timestamp("2026-09-25"),
                                  side="right")) - 1
    ref = E9.simulate(snp, o, c_ff, start, end, 0.0003, 0.03, 1.0, 0.5)
    mine = simulate_gate(snp, o, c_ff, start, end, 0.0003, 0.03,
                         np.zeros(len(dates), dtype=bool))
    ident = float(np.abs(ref - mine).max())

    diag = {"engine_identity_max_diff": ident,
            "gate_days_full": int(gate[start:end + 1].sum()),
            "gate_triggers": [str(dates[t].date())
                                for t in range(21, len(dates))
                                if gate[t] and not gate[t - 1]]}

    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        st = int(dates.searchsorted(pd.Timestamp(a)))
        en = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[st:en + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(comp.to_numpy(), o, c_ff, st, en, cost,
                            carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(snp, o, c_ff, st, en, cost, carry,
                            1.0, 0.5), index=idx))
            res[f"{pname}_A_gate_{cname}"] = E9.stats(pd.Series(
                simulate_gate(snp, o, c_ff, st, en, cost, carry,
                              gate), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_gate_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_gate_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_gate_stress"]["profit"] > 0
            and ratio("full_A_gate_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
