"""EXP-084: voluntary-disclosure thickness DECREASE penalty (round 10).

Preregistration: docs/experiments/EXP-084_PREREGISTRATION.md
dVolA = voluntary-disclosure count in (t-365d, t] minus count in
(t-730d, t-365d], voluntary = TDnet title matching EXP-054's patterns.
Descriptive gate: median daily count of names with dVolA <= -2 must
be >= 8, and the flagged names' next-20bd TOPIX-excess return must be
negative in both halves. Book test (if the gate passes): long score =
A tilt - 0.10 on flagged names, shorts follow A; standard 3 criteria.
Usage: python experiments/exp084_voluntary_decrease.py <cache> <tdnet_dir>
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


def dvol_matrix(tdnet_dir: Path, dates: pd.DatetimeIndex,
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
    out = pd.DataFrame(0, index=dates, columns=codes, dtype=float)
    for code, ds in vol.items():
        if code not in out.columns:
            continue
        a = np.sort(np.array(ds, dtype="datetime64[ns]"))
        hi = np.searchsorted(a, dv, side="right")
        mid = np.searchsorted(a, dv - np.timedelta64(365, "D"), side="right")
        lo = np.searchsorted(a, dv - np.timedelta64(730, "D"), side="right")
        out[code] = (hi - mid) - (mid - lo)
    return out


def main(cache: Path, tdnet_dir: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid)) / 2.0).where(valid)

    dvol = dvol_matrix(tdnet_dir, dates, codes)
    flagged = (dvol <= -2) & valid
    win = (dates >= "2017-01-04") & (dates <= "2026-09-25")
    med_all = float(flagged[win].sum(axis=1).median())

    close = panel["C"].ffill()
    exc = close.pct_change(fill_method=None).sub(
        topix["C"].pct_change(fill_method=None), axis=0)
    entered = flagged & ~flagged.shift(1, fill_value=False)
    fh = (dates >= "2017-01-04") & (dates <= "2021-12-30")
    sh = (dates >= "2022-01-04") & (dates <= "2026-09-25")
    era_ret = {}
    for name, m in (("first_half", fh), ("second_half", sh)):
        vals = []
        idxs = np.flatnonzero(np.asarray(m))
        ent = entered.to_numpy()
        ex = exc.to_numpy()
        cols = {c: j for j, c in enumerate(codes)}
        for i in idxs:
            if i + 20 >= len(dates):
                continue
            for code in codes:
                if ent[i, cols[code]]:
                    r = float((1 + pd.Series(ex[i + 1:i + 21, cols[code]]).fillna(0)).prod() - 1)
                    vals.append(r)
        era_ret[name] = {"n": len(vals), "mean_excess_pct": round(float(np.mean(vals)) * 100, 3) if vals else None}
    gate = (med_all >= 8 and era_ret["first_half"]["mean_excess_pct"] is not None
            and era_ret["first_half"]["mean_excess_pct"] < 0
            and era_ret["second_half"]["mean_excess_pct"] is not None
            and era_ret["second_half"]["mean_excess_pct"] < 0)
    print(json.dumps({"gate": {"median_flagged": med_all, "eras": era_ret,
                               "passed": bool(gate)}}, ensure_ascii=False))
    if not gate:
        print("VERDICT: KILLED at the descriptive gate")
        return

    long_p = (score_a - 0.10 * flagged).where(valid)
    o = panel["O"].to_numpy()
    c_ff = close.to_numpy()
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
            res[f"{pname}_Avd_{cname}"] = E9.stats(pd.Series(
                np.asarray(E13.simulate2(long_p.to_numpy(), score_a.to_numpy(),
                                         o, c_ff, start, end, cost, carry, 1.0, 0.5), dtype=float), index=idx))
    g = lambda p, k: res[f"{p}_Avd_base"][k]  # noqa: E731
    a = lambda p, k: res[f"{p}_A_base"][k]  # noqa: E731
    verdict = {
        "1_profit_positive_both_halves": bool(all(g(p, "profit") > 0 for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all((g(p, "annual_over_dd") or -9) > (a(p, "annual_over_dd") or -9) for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(res["full_Avd_stress"]["profit"] > 0 and (res["full_Avd_stress"]["annual_over_dd"] or -9) > (res["full_A_stress"]["annual_over_dd"] or -9)),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict}, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
