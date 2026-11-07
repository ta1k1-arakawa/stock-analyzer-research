"""EXP-098: tiered broad large-holding increase follow (AB tiering).

Preregistration: docs/experiments/EXP-098_PREREGISTRATION.md

Events are EXP-088's (type 1 new, or type 2 with
TotalShsRatio - TotalShsRatioLast >= 0.01). Each event is tiered by the
size of the new buying before any return is looked at:
  strong: type 2 increase >= 0.03, or type 1 TotalShsRatio >= 0.10
  weak:   all other EXP-088 events
Flag from the first trading day after SubDate for 120 calendar days;
when strong and weak overlap on the same name-day, strong wins.
  098A: weak +0.05, strong +0.10 (long only, short = A)
  098B: weak +0.10, strong +0.20 (long only, short = A)
Simulated with EXP-013's simulate2. Judgement is the preregistered
second-half set (archive starts 2021-07).

Usage:
    python experiments/exp098_tiered_ab.py <cache_dir> <archive_dir>
"""
from __future__ import annotations

import glob
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


def tier_flags(archive: Path, dates: pd.DatetimeIndex,
               codes: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return (strong_flag, weak_flag, diagnostics).

    Strong and weak are disjoint: a name-day is strong iff any strong
    event covers it, else weak iff any weak event covers it.
    """
    strong = pd.DataFrame(False, index=dates, columns=codes)
    weak = pd.DataFrame(False, index=dates, columns=codes)
    dv = dates.to_numpy()
    n_events = n_strong = n_weak = 0
    for f in glob.glob(str(archive / "large" / "*.json")):
        code = Path(f).stem
        if code not in strong.columns:
            continue
        for d in json.loads(Path(f).read_text()):
            t = str(d.get("LargeHldgTypeCode"))
            if t not in ("1", "2"):
                continue
            try:
                ratio = float(d.get("TotalShsRatio"))
            except (TypeError, ValueError):
                continue
            if t == "2":
                try:
                    inc = ratio - float(d.get("TotalShsRatioLast"))
                except (TypeError, ValueError):
                    continue
                if inc < 0.01:
                    continue
                is_strong = inc >= 0.03
            else:
                is_strong = ratio >= 0.10
            n_events += 1
            n_strong += int(is_strong)
            n_weak += int(not is_strong)
            sub = pd.Timestamp(d["SubDate"])
            lo = np.searchsorted(dv, np.datetime64(sub), side="right")
            hi = np.searchsorted(
                dv, np.datetime64(sub + pd.Timedelta(days=120)),
                side="right")
            if hi > lo:
                target = strong if is_strong else weak
                target.iloc[lo:hi, target.columns.get_loc(code)] = True
    # Strong wins on overlap.
    weak = weak & ~strong
    diag = {"n_events": n_events, "n_strong": n_strong, "n_weak": n_weak}
    return strong, weak, diag


def main(cache: Path, archive: Path) -> None:
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
    strong, weak, diag = tier_flags(archive, dates, codes)
    s_np = strong.to_numpy()
    w_np = weak.to_numpy()
    for pname, (a, b) in PERIODS.items():
        m = (dates >= a) & (dates <= b)
        diag[pname] = {
            "strong_name_days": int(strong[m].sum().sum()),
            "weak_name_days": int(weak[m].sum().sum()),
            "days_with_any_flag": float(
                (strong[m] | weak[m]).any(axis=1).mean()),
        }

    variants = {
        "A": (0.05, 0.10),  # 098A: weak +0.05, strong +0.10
        "B": (0.10, 0.20),  # 098B: weak +0.10, strong +0.20
    }
    res: dict = {"diagnostics": diag}
    for pname, (a, b) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a)))
        e = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_a.to_numpy(), o_np, c_np, s, e, cost,
                            carry, 1.0, 0.5), index=idx))
            for vname, (bw, bs) in variants.items():
                bonus = (bw * w_np + bs * s_np).astype(float)
                lnp = np.where(valid.to_numpy(), score_a.to_numpy() + bonus,
                               np.nan)
                res[f"{pname}_A98{vname}_{cname}"] = E9.stats(pd.Series(
                    E13.simulate2(lnp, score_a.to_numpy(), o_np, c_np, s, e,
                                  cost, carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {}
    for vname in variants:
        verdict[f"098{vname}"] = {
            "1_SH_profit_positive":
                bool(res[f"second_half_A98{vname}_base"]["profit"] > 0),
            "2_SH_ratio_beats_A":
                bool(ratio(f"second_half_A98{vname}_base")
                     > ratio("second_half_A_base")),
            "3_SH_stress_ratio_beats_A":
                bool(res[f"second_half_A98{vname}_stress"]["profit"] > 0
                     and ratio(f"second_half_A98{vname}_stress")
                     > ratio("second_half_A_stress")),
        }
        verdict[f"098{vname}"]["promising"] = bool(
            all(verdict[f"098{vname}"].values()))
    print(json.dumps({"res": res, "verdict": verdict},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
