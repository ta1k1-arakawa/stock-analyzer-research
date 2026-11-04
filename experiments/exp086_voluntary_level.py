"""EXP-086C: voluntary-disclosure LEVEL tilt (top quartile of the
trailing-12m voluntary count gets +0.10 on the long side).

Preregistration: docs/experiments/EXP-086_PREREGISTRATION.md
Standard 3 criteria vs A. Usage:
    python experiments/exp086_voluntary_level.py <cache_dir> <tdnet_dir>
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
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


def count_matrix(tdnet_dir: Path, dates: pd.DatetimeIndex,
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
    dv = dates.to_numpy()
    out = pd.DataFrame(0.0, index=dates, columns=codes)
    for code, ds in vol.items():
        if code not in out.columns:
            continue
        a = np.sort(np.array(ds, dtype="datetime64[ns]"))
        hi = np.searchsorted(a, dv, side="right")
        lo = np.searchsorted(a, dv - np.timedelta64(365, "D"), side="right")
        out[code] = hi - lo
    return out


def main(cache: Path, tdnet_dir: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid)) / 2.0).where(valid)

    cnt = count_matrix(tdnet_dir, dates, codes)
    cnt_r = cnt.where(valid).rank(axis=1, pct=True)
    flagged = (cnt_r >= 0.75) & valid
    win = (dates >= "2017-01-04") & (dates <= "2026-09-25")
    med = float(flagged[win].sum(axis=1).median())
    long_l = (score_a + 0.10 * flagged).where(valid)

    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(comp.to_numpy(), o, c_ff, start, end, cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_a.to_numpy(), o, c_ff, start, end, cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_Avl_{cname}"] = E9.stats(pd.Series(
                np.asarray(E13.simulate2(long_l.to_numpy(), score_a.to_numpy(),
                                         o, c_ff, start, end, cost, carry, 1.0, 0.5), dtype=float), index=idx))
    g = lambda p, k: res[f"{p}_Avl_base"][k]  # noqa: E731
    av = lambda p, k: res[f"{p}_A_base"][k]  # noqa: E731
    verdict = {
        "1_profit_positive_both_halves": bool(all(g(p, "profit") > 0 for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all((g(p, "annual_over_dd") or -9) > (av(p, "annual_over_dd") or -9) for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(res["full_Avl_stress"]["profit"] > 0 and (res["full_Avl_stress"]["annual_over_dd"] or -9) > (res["full_A_stress"]["annual_over_dd"] or -9)),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"median_flagged": med, "res": res, "verdict": verdict}, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
