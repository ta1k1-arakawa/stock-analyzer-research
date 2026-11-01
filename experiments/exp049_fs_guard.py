"""EXP-049: FS-lite guard on A (Piotroski-type end replacement).

Preregistration: docs/experiments/EXP-049_PREREGISTRATION.md

FS8-lite is computed from consecutive FY statements (8 items;
years whose Sales/OP are unusable get no FS). The guard runs on
EXP-013's simulate2 mechanics: a confirmed long pick with
FS <= 2 is replaced by the first lower-ranked name that is not
held, not already picked, and has FS >= 3; a confirmed short
pick with FS >= 7 is replaced symmetrically by the first name
from the bottom with FS <= 6. If no replacement exists the
original pick stands. FS is read at t-1, like the scores.
Identity check: an all-NaN FS matrix must reproduce A exactly.

Usage:
    python experiments/exp049_fs_guard.py <cache_dir>
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

NT, PT, HOLD = E13.NT, E13.PT, E13.HOLD
BUDGET = E9.BUDGET
PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def fs_matrix(fins, dates: pd.DatetimeIndex,
              codes: list[str]) -> np.ndarray:
    fs = pd.DataFrame(np.nan, index=dates, columns=codes)
    for code in codes:
        fy = [r for r in fins.get(code, [])
              if r.get("CurPerType") == "FY"
              and "FinancialStatements" in str(r.get("DocType", ""))]
        fy.sort(key=lambda r: (str(r.get("CurFYEn", "")),
                               str(r.get("DiscDate", ""))))
        pts = []
        for i in range(1, len(fy)):
            r, p = fy[i], fy[i - 1]
            sales, psales = _num(r.get("Sales")), _num(p.get("Sales"))
            op, pop = _num(r.get("OP")), _num(p.get("OP"))
            if not (sales > 0 and psales > 0) \
                    or np.isnan(op) or np.isnan(pop):
                continue
            np_, cfo = _num(r.get("NP")), _num(r.get("CFO"))
            ta, pta = _num(r.get("TA")), _num(p.get("TA"))
            eqar, peqar = _num(r.get("EqAR")), _num(p.get("EqAR"))
            pnp = _num(p.get("NP"))
            sh = _num(r.get("ShOutFY")) - _num(r.get("TrShFY"))
            psh = _num(p.get("ShOutFY")) - _num(p.get("TrShFY"))
            items = [np_ > 0, cfo > 0, cfo >= np_,
                     (np_ / ta) > (pnp / pta)
                     if ta > 0 and pta > 0 else False,
                     eqar > peqar, (op / sales) > (pop / psales),
                     (sales / ta) > (psales / pta)
                     if ta > 0 and pta > 0 else False,
                     sh <= psh]
            pts.append((pd.Timestamp(r["DiscDate"]),
                        float(sum(bool(x) for x in items))))
        if not pts:
            continue
        dd = pd.DatetimeIndex([x[0] for x in pts])
        vv = np.array([x[1] for x in pts])
        idx = np.searchsorted(dd, dates.to_numpy(), side="right") - 1
        fs[code] = np.where(idx >= 0, vv[np.clip(idx, 0, len(vv) - 1)],
                            np.nan)
    return fs.to_numpy()


def simulate_guard(score, fs, o, c_ff, start, end, cost, carry,
                   counter):
    step = HOLD // NT
    longs = [dict() for _ in range(NT)]
    lcash = [BUDGET / NT] * NT
    shorts = [dict() for _ in range(NT)]
    realized = 0.0
    values = []

    def short_unreal(t):
        return sum(n * (1 - c_ff[t, j] / p)
                   for s in shorts for j, (p, n) in s.items())

    def equity(t):
        return sum(lcash) \
            + sum(sh * c_ff[t, j] for h in longs
                  for j, sh in h.items()) \
            + realized + short_unreal(t)

    for t in range(start, end + 1):
        i = t - start
        due = range(NT) if i == 0 else (
            [(i % HOLD) // step] if i % step == 0 else [])
        sl = score[t - 1]
        ok = np.flatnonzero(np.isfinite(sl))
        order = ok[np.lexsort((ok, -sl[ok]))]
        fsr = fs[t - 1]
        eq_prev = equity(t - 1) if i > 0 else BUDGET
        for k in due:
            lcash[k] += sum(
                sh * (o[t, j] if o[t, j] > 0 else c_ff[t - 1, j])
                * (1 - cost) for j, sh in longs[k].items())
            held = set().union(*(longs[m] for m in range(NT)
                                 if m != k))
            cand = [j for j in order
                    if o[t, j] > 0 and j not in held][:PT]
            used = set(cand)
            new_cand = []
            for j in cand:
                if np.isfinite(fsr[j]) and fsr[j] <= 2:
                    rep = next(
                        (x for x in order
                         if o[t, x] > 0 and x not in held
                         and x not in used and np.isfinite(fsr[x])
                         and fsr[x] >= 3), None)
                    if rep is not None:
                        new_cand.append(rep)
                        used.add(rep)
                        counter["long"] += 1
                        continue
                new_cand.append(j)
            cand = new_cand
            longs[k] = {}
            if cand:
                longs[k] = {j: lcash[k] / len(cand)
                            / (o[t, j] * (1 + cost)) for j in cand}
                lcash[k] = 0.0
            for j, (p, n) in shorts[k].items():
                px = (o[t, j] if o[t, j] > 0
                      else c_ff[t - 1, j]) * (1 + cost)
                realized += n * (1 - px / p)
            held_s = set().union(*(shorts[m] for m in range(NT)
                                   if m != k))
            cand_s = [j for j in order[::-1]
                      if o[t, j] > 0 and j not in held_s][:PT]
            used_s = set(cand_s)
            new_s = []
            for j in cand_s:
                if np.isfinite(fsr[j]) and fsr[j] >= 7:
                    rep = next(
                        (x for x in order[::-1]
                         if o[t, x] > 0 and x not in held_s
                         and x not in used_s and np.isfinite(fsr[x])
                         and fsr[x] <= 6), None)
                    if rep is not None:
                        new_s.append(rep)
                        used_s.add(rep)
                        counter["short"] += 1
                        continue
                new_s.append(j)
            cand_s = new_s
            notional = eq_prev * 0.5 / NT
            shorts[k] = {j: (o[t, j] * (1 - cost),
                             notional / len(cand_s))
                         for j in cand_s} if cand_s else {}
        realized -= sum(n for sh in shorts for _, n in sh.values()) \
            * carry / 245
        values.append(equity(t))
    last = end
    final = sum(lcash) \
        + sum(sh * c_ff[last, j] * (1 - cost)
              for h in longs for j, sh in h.items()) \
        + realized \
        + sum(n * (1 - c_ff[last, j] * (1 + cost) / p)
              for s in shorts for j, (p, n) in s.items())
    values[-1] = final
    return np.array(values)


def main(cache: Path) -> None:
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
    fs = fs_matrix(fins, dates, codes)

    # identity check: all-NaN FS must reproduce A exactly
    s0 = int(dates.searchsorted(pd.Timestamp("2017-01-04")))
    e0 = int(dates.searchsorted(pd.Timestamp("2026-09-25"),
                                side="right")) - 1
    nan_fs = np.full_like(fs, np.nan)
    cnt0 = {"long": 0, "short": 0}
    mine = simulate_guard(snp, nan_fs, o_np, c_np, s0, e0,
                          0.0003, 0.03, cnt0)
    ref = E9.simulate(snp, o_np, c_np, s0, e0, 0.0003, 0.03,
                      1.0, 0.5)
    identity = float(np.max(np.abs(mine - ref)))

    res: dict = {"identity_max_diff": identity}
    for pname, (a, b) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a)))
        e = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(snp, o_np, c_np, s, e, cost, carry,
                            1.0, 0.5), index=idx))
            cnt = {"long": 0, "short": 0}
            res[f"{pname}_A_fs_{cname}"] = E9.stats(pd.Series(
                simulate_guard(snp, fs, o_np, c_np, s, e, cost,
                               carry, cnt), index=idx))
            res[f"{pname}_replacements_{cname}"] = cnt

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_fs_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_fs_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_fs_stress"]["profit"] > 0
            and ratio("full_A_fs_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
