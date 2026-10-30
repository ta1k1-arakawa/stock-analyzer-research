"""EXP-016: exclude TOPIX phased-deletion names from the long book.

Pre-registration: docs/experiments/EXP-016_PREREGISTRATION.md
  - Filter (2022-25 round, JPX-published lists in exp016_topix_lists.json,
    extracted from JPX PDFs and count-verified against the announcements):
    the 40 designated names inside the 306-name universe are removed from
    the LONG score only, for score dates 2022-10-07..2025-01-31; the 5
    names reprieved at the Oct-2023 re-evaluation are removed only until
    2023-10-06. Short scores are unchanged.
  - Variants: S+F vs S and A+F vs A (A = EXP-010's earnings-momentum tilt,
    rebuilt exactly as in exp010's main), judged separately with the
    adapted criteria in the pre-registration (designations exist only in
    the second half, so the first half is identical by construction).
  - simulate2() is EXP-013's two-score generalisation of EXP-009's
    simulate(); the self-check (identical scores -> identical output)
    is printed in the diagnostics.

Usage:
    python experiments/exp016_deletion_avoidance.py <cache_dir>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3  # noqa: E402
import exp009_long_short as E9  # noqa: E402
import exp010_earnings_momentum as E10  # noqa: E402

BUDGET = 2_000_000
PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
NT, PT, HOLD = E3.N_TRANCHES, E3.PER_TRANCHE, E3.HOLD_DAYS

DESIGNATED_FROM = "2022-10-07"
DESIGNATED_TO = "2025-01-31"
REPRIEVED_TO = "2023-10-06"


def simulate2(long_score, short_score, o, c_ff, start, end, cost, carry,
              long_frac, short_frac):
    step = HOLD // NT
    longs = [dict() for _ in range(NT)]
    lcash = [BUDGET * long_frac / NT] * NT
    idle = BUDGET * (1 - long_frac)
    shorts = [dict() for _ in range(NT)]
    realized = 0.0
    values = []

    def short_unreal(t):
        return sum(n * (1 - c_ff[t, j] / p) for s in shorts for j, (p, n) in s.items())

    def equity(t):
        return idle + sum(lcash) + sum(sh * c_ff[t, j] for h in longs for j, sh in h.items()) + realized + short_unreal(t)

    for t in range(start, end + 1):
        i = t - start
        due = range(NT) if i == 0 else ([(i % HOLD) // step] if i % step == 0 else [])
        sl = long_score[t - 1]
        ok_l = np.flatnonzero(np.isfinite(sl))
        order_l = ok_l[np.lexsort((ok_l, -sl[ok_l]))]
        ss = short_score[t - 1]
        ok_s = np.flatnonzero(np.isfinite(ss))
        order_s = ok_s[np.lexsort((ok_s, -ss[ok_s]))]
        eq_prev = equity(t - 1) if i > 0 else BUDGET
        for k in due:
            lcash[k] += sum(sh * (o[t, j] if o[t, j] > 0 else c_ff[t - 1, j]) * (1 - cost) for j, sh in longs[k].items())
            held = set().union(*(longs[m] for m in range(NT) if m != k))
            cand = [j for j in order_l if o[t, j] > 0 and j not in held][:PT]
            longs[k] = {}
            if cand:
                longs[k] = {j: lcash[k] / len(cand) / (o[t, j] * (1 + cost)) for j in cand}
                lcash[k] = 0.0
            if short_frac > 0:
                for j, (p, n) in shorts[k].items():
                    px = (o[t, j] if o[t, j] > 0 else c_ff[t - 1, j]) * (1 + cost)
                    realized += n * (1 - px / p)
                held_s = set().union(*(shorts[m] for m in range(NT) if m != k))
                cand_s = [j for j in order_s[::-1] if o[t, j] > 0 and j not in held_s][:PT]
                notional = eq_prev * short_frac / NT
                shorts[k] = {j: (o[t, j] * (1 - cost), notional / len(cand_s)) for j in cand_s} if cand_s else {}
        realized -= sum(n for sh in shorts for _, n in sh.values()) * carry / 245
        values.append(equity(t))
    last = end
    final = idle + sum(lcash) + sum(sh * c_ff[last, j] * (1 - cost) for h in longs for j, sh in h.items()) + realized \
        + sum(n * (1 - c_ff[last, j] * (1 + cost) / p) for s in shorts for j, (p, n) in s.items())
    values[-1] = final
    return np.array(values)


def apply_filter(score_df: pd.DataFrame, lists: dict) -> tuple[pd.DataFrame, dict]:
    """Mask designated names in the long score during their windows."""
    out = score_df.copy()
    designated = [c for c in lists["designated_2022"] if c in out.columns]
    reprieved = set(lists["reprieved_2023"])
    d0, d1 = pd.Timestamp(DESIGNATED_FROM), pd.Timestamp(DESIGNATED_TO)
    r1 = pd.Timestamp(REPRIEVED_TO)
    masked_cells = 0
    eligible_cells = 0
    for code in designated:
        end = r1 if code in reprieved else d1
        win = (out.index >= d0) & (out.index <= end)
        eligible_cells += int(out.loc[win, code].notna().sum())
        out.loc[win, code] = np.nan
        masked_cells += int(win.sum())
    diag = {"designated_in_universe": len(designated),
            "reprieved_in_universe": sum(1 for c in designated if c in reprieved),
            "masked_eligible_cells": eligible_cells}
    return out, diag


def main(cache: Path) -> None:
    if not (cache / "topix.json").exists():
        raise SystemExit(f"cache not found: {cache} (expected topix.json inside)")
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)
    mask = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(mask)) / 2.0).where(mask)

    lists = json.loads((Path(__file__).resolve().parent / "exp016_topix_lists.json").read_text())
    long_s, diag_f = apply_filter(comp, lists)
    long_a, _ = apply_filter(score_a, lists)

    mats = {
        "S": (comp.to_numpy(), comp.to_numpy()),
        "SF": (long_s.to_numpy(), comp.to_numpy()),
        "A": (score_a.to_numpy(), score_a.to_numpy()),
        "AF": (long_a.to_numpy(), score_a.to_numpy()),
    }
    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    f0 = int(dates.searchsorted(pd.Timestamp(PERIODS["full"][0])))
    f1 = int(dates.searchsorted(pd.Timestamp(PERIODS["full"][1]), side="right")) - 1
    chk_a = E9.simulate(mats["S"][0], o, c, f0, f1, *COSTS["base"], 1.0, 0.5)
    chk_b = simulate2(mats["S"][0], mats["S"][1], o, c, f0, f1, *COSTS["base"], 1.0, 0.5)
    self_check = float(np.max(np.abs(chk_a - chk_b)))

    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start : end + 1]
        for cname, (cost, carry) in COSTS.items():
            for vname, (ls, ss) in mats.items():
                vals = simulate2(ls, ss, o, c, start, end, cost, carry, 1.0, 0.5)
                res[f"{pname}_{vname}_{cname}"] = E9.stats(pd.Series(vals, index=idx))

    def verdict_for(variant: str, base: str) -> dict:
        g = lambda p, k, cn="base": res[f"{p}_{variant}_{cn}"][k]  # noqa: E731
        s = lambda p, k, cn="base": res[f"{p}_{base}_{cn}"][k]  # noqa: E731
        c1 = all(g(p, "profit") > 0 for p in ("second_half", "full"))
        c2 = (g("second_half", "annual_over_dd") or -9) > (s("second_half", "annual_over_dd") or -9)
        c3 = g("full", "profit", "stress") > 0 and \
            (g("full", "annual_over_dd", "stress") or -9) > (s("full", "annual_over_dd", "stress") or -9)
        return {"1_profit_positive_SH_and_full": bool(c1),
                "2_SH_ratio_gt_unfiltered": bool(c2),
                "3_full_stress_positive_and_ratio_gt_unfiltered": bool(c3),
                "promising": bool(c1 and c2 and c3)}

    diag = {"self_check_max_abs_diff": self_check, **diag_f,
            "first_half_identical_SF": res["first_half_SF_base"] == res["first_half_S_base"],
            "first_half_identical_AF": res["first_half_AF_base"] == res["first_half_A_base"]}
    print(json.dumps({"res": res, "verdict": {"SF": verdict_for("SF", "S"), "AF": verdict_for("AF", "A")},
                      "diag": diag}, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
