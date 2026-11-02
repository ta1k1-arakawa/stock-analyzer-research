"""EXP-054: voluntary-disclosure thickness increase tilt.

Preregistration: docs/experiments/EXP-054_PREREGISTRATION.md

From the archived TDnet title corpus, a disclosure is
"voluntary" when its title contains one of the registered
patterns. dVolA_i(t) = voluntary count in (t-365d, t] minus the
count in (t-730d, t-365d]. Names with dVolA >= 2 get +0.10 on
A's long score while the condition holds; shorts are A's.
Simulated with EXP-013's simulate2.

Usage:
    python experiments/exp054_voluntary_disclosure.py <cache_dir> <tdnet_dir>
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
PATS = ("決算説明", "説明会", "個人投資家", "中期経営計画")


def bonus_matrix(tdnet_dir: Path, dates: pd.DatetimeIndex,
                 codes: list[str]) -> pd.DataFrame:
    vol: dict[str, list] = {}
    for f in glob.glob(str(tdnet_dir / "*.json")):
        try:
            d = json.loads(Path(f).read_text())
        except Exception:
            continue
        items = d if isinstance(d, list) else d.get("items", [])
        if isinstance(items, dict):
            items = items.get("items", [])
        for it in items or []:
            title = str(it.get("title", ""))
            if any(p in title for p in PATS):
                vol.setdefault(str(it.get("code")), []).append(
                    pd.Timestamp(str(it.get("pubdate"))[:10]))
    bonus = pd.DataFrame(False, index=dates, columns=codes)
    dv = dates.to_numpy()
    for code, ds in vol.items():
        if code not in bonus.columns:
            continue
        a = np.sort(np.array(ds, dtype="datetime64[ns]"))
        hi = np.searchsorted(a, dv, side="right")
        mid = np.searchsorted(a, dv - np.timedelta64(365, "D"),
                              side="right")
        lo = np.searchsorted(a, dv - np.timedelta64(730, "D"),
                             side="right")
        bonus[code] = (hi - mid) - (mid - lo) >= 2
    return bonus


def main(cache: Path, tdnet_dir: Path) -> None:
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
    bonus = bonus_matrix(tdnet_dir, dates, codes)
    long_score = (score_a + 0.10 * bonus.where(valid, False)
                  .fillna(False).astype(float)).where(valid)
    snp = score_a.to_numpy()
    lnp = long_score.to_numpy()

    diag = {}
    for pname, (a, b) in PERIODS.items():
        m = (dates >= a) & (dates <= b)
        diag[pname] = {
            "bonus_names_median": float(bonus[m].sum(axis=1).median()),
        }

    res: dict = {"diagnostics": diag}
    for pname, (a, b) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a)))
        e = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(snp, o_np, c_np, s, e, cost, carry,
                            1.0, 0.5), index=idx))
            res[f"{pname}_A_vd_{cname}"] = E9.stats(pd.Series(
                E13.simulate2(lnp, snp, o_np, c_np, s, e, cost,
                              carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_vd_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_vd_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_vd_stress"]["profit"] > 0
            and ratio("full_A_vd_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
