"""EXP-094: graded AV bonus (see EXP-094_PREREGISTRATION.md).

dVolA = voluntary-disclosure count in the last 12 months minus the
prior 12 months (EXP-054's definition, TDnet title corpus). Variant A:
+0.05 when dVolA == 2, +0.10 when dVolA >= 3. Variant B: +0.10 / +0.20.
Long side only; shorts are plain A. Standard three criteria vs A.

Usage: exp094_av_graded.py <jquants_cache_dir> <tdnet_dir>"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3      # noqa: E402
import exp009_long_short as E9    # noqa: E402
import exp010_earnings_momentum as E10  # noqa: E402
import exp013_vol_managed as E13  # noqa: E402

PERIODS = {"first_half": ("2017-01-04", "2021-12-30"),
           "second_half": ("2022-01-04", "2026-09-25"),
           "full": ("2017-01-04", "2026-09-25")}
COSTS = E9.COSTS
PATS = ("決算説明", "説明会", "個人投資家", "中期経営計画")


def delta_frame(tdnet_dir: Path, dates: pd.DatetimeIndex,
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
    delta = pd.DataFrame(0, index=dates, columns=codes)
    dv = dates.to_numpy()
    for code, ds in vol.items():
        if code not in delta.columns:
            continue
        a = np.sort(np.array(ds, dtype="datetime64[ns]"))
        hi = np.searchsorted(a, dv, side="right")
        mid = np.searchsorted(a, dv - np.timedelta64(365, "D"), side="right")
        lo = np.searchsorted(a, dv - np.timedelta64(730, "D"), side="right")
        delta[code] = (hi - mid) - (mid - lo)
    return delta


def main(cache: Path, tdnet_dir: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    mask = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(mask)) / 2.0).where(mask)

    delta = delta_frame(tdnet_dir, dates, codes)
    bonus_a = (0.05 * (delta == 2) + 0.10 * (delta >= 3)).where(mask, 0.0)
    bonus_b = (0.10 * (delta == 2) + 0.20 * (delta >= 3)).where(mask, 0.0)
    long_a = (score_a + bonus_a).where(mask)
    long_b = (score_a + bonus_b).where(mask)

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()
    s_np, a_np = comp.to_numpy(), score_a.to_numpy()
    la, lb = long_a.to_numpy(), long_b.to_numpy()

    res: dict = {}
    for pname, (x, y) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(x)))
        end = int(dates.searchsorted(pd.Timestamp(y), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(s_np, o, c, start, end, cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(a_np, o, c, start, end, cost, carry, 1.0, 0.5), index=idx))
            for tag, lg in (("AvgA", la), ("AvgB", lb)):
                res[f"{pname}_{tag}_{cname}"] = E9.stats(pd.Series(
                    np.asarray(E13.simulate2(lg, a_np, o, c, start, end, cost, carry, 1.0, 0.5),
                               dtype=float), index=idx))

    def verdict(tag: str) -> dict:
        g = lambda p, k: res[f"{p}_{tag}_base"][k]  # noqa: E731
        av = lambda p, k: res[f"{p}_A_base"][k]  # noqa: E731
        c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
        c2 = all((g(p, "annual_over_dd") or -9) > (av(p, "annual_over_dd") or -9)
                 for p in ("first_half", "second_half"))
        gf, af = res[f"full_{tag}_stress"], res["full_A_stress"]
        c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > (af["annual_over_dd"] or -9)
        return {"1_profit_positive_both_halves": bool(c1),
                "2_ratio_gt_A_both_halves": bool(c2),
                "3_full_stress_positive_and_ratio_gt_A": bool(c3),
                "promising": bool(c1 and c2 and c3)}

    print(json.dumps({"res": res,
                      "verdicts": {"AvgA": verdict("AvgA"), "AvgB": verdict("AvgB")}},
                     ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
