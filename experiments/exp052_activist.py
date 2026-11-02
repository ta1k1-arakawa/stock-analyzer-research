"""EXP-052: activist large-holding follow.

Preregistration: docs/experiments/EXP-052_PREREGISTRATION.md

An event is a large-volume filing of type 1 (new), or type 2
(change) with TotalShsRatio - TotalShsRatioLast >= 0.01, where
at least one holder's ImpProp free text indicates important
proposals (non-empty and not matching the "no applicable
matters" patterns). From the first trading day after SubDate
for 120 calendar days the name is flagged: long score +0.15,
excluded from shorts. Simulated with EXP-013's simulate2.
Judgement is the preregistered second-half set (data starts
2021-07).

Usage:
    python experiments/exp052_activist.py <cache_dir> <archive_dir>
"""
from __future__ import annotations

import glob
import json
import re
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
NONE_PAT = re.compile(r"(該当|記載)(事項)?(なし|無し|はありません|ございません)")


def impprop_present(h) -> bool:
    v = h.get("ImpProp")
    return isinstance(v, str) and bool(v.strip()) \
        and not NONE_PAT.search(v)


def flag_matrix(archive: Path, dates: pd.DatetimeIndex,
                codes: list[str]) -> tuple[pd.DataFrame, int]:
    flag = pd.DataFrame(False, index=dates, columns=codes)
    dv = dates.to_numpy()
    n_events = 0
    for f in glob.glob(str(archive / "large" / "*.json")):
        code = Path(f).stem
        if code not in flag.columns:
            continue
        for d in json.loads(Path(f).read_text()):
            t = str(d.get("LargeHldgTypeCode"))
            if t not in ("1", "2"):
                continue
            if not any(impprop_present(h)
                       for h in (d.get("Hldrs") or [])):
                continue
            if t == "2":
                try:
                    if float(d.get("TotalShsRatio")) \
                            - float(d.get("TotalShsRatioLast")) < 0.01:
                        continue
                except (TypeError, ValueError):
                    continue
            n_events += 1
            sub = pd.Timestamp(d["SubDate"])
            lo = np.searchsorted(dv, np.datetime64(sub), side="right")
            hi = np.searchsorted(
                dv, np.datetime64(sub + pd.Timedelta(days=120)),
                side="right")
            if hi > lo:
                flag.iloc[lo:hi, flag.columns.get_loc(code)] = True
    return flag, n_events


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
    flag, n_events = flag_matrix(archive, dates, codes)
    long_score = (score_a + 0.15 * flag.where(valid, False)
                  .fillna(False).astype(float)).where(valid)
    short_score = score_a.where(~flag)
    snp = score_a.to_numpy()
    lnp = long_score.to_numpy()
    shp = short_score.to_numpy()

    diag = {"n_events": n_events}
    for pname, (a, b) in PERIODS.items():
        m = (dates >= a) & (dates <= b)
        diag[pname] = {
            "flagged_name_days": int(flag[m].sum().sum()),
            "days_with_any_flag": float(flag[m].any(axis=1).mean()),
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
            res[f"{pname}_A_act_{cname}"] = E9.stats(pd.Series(
                E13.simulate2(lnp, shp, o_np, c_np, s, e, cost,
                              carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_SH_profit_positive":
            bool(res["second_half_A_act_base"]["profit"] > 0),
        "2_SH_ratio_beats_A":
            bool(ratio("second_half_A_act_base")
                 > ratio("second_half_A_base")),
        "3_SH_stress_ratio_beats_A":
            bool(ratio("second_half_A_act_stress")
                 > ratio("second_half_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
