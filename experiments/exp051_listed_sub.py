"""EXP-051: listed-subsidiary flag on A.

Preregistration: docs/experiments/EXP-051_PREREGISTRATION.md

ListedSub_i(t) = 1 when the most recent major-shareholders
document (SubDate <= t, from the archived J-Quants EDINET data)
lists a holder with ShsRatio >= 0.5 whose normalised name
matches a listed company (name set in exp051_listed_names.json,
the union of the 2017/2019/2021/2023/2026 masters) and whose
name carries none of the nominee/institution keywords.
Shorts: flagged names are removed from the short score (NaN).
Longs: +0.10 on A's score when flagged and the B/P rank
(signals' value_only) is >= 0.5. Simulated with EXP-013's
simulate2.

Usage:
    python experiments/exp051_listed_sub.py <cache_dir> <archive_dir>
"""
from __future__ import annotations

import glob
import json
import re
import sys
import unicodedata
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
EXCL = ("信託", "カストディ", "銀行", "保険", "証券", "生命",
        "年金", "基金", "機構", "持株会", "共済")


def norm(name) -> str:
    s = unicodedata.normalize("NFKC", str(name or ""))
    s = re.split(r"[\(（]", s)[0]
    for w in ("株式会社", "有限会社", "合同会社", "ホールディングス"):
        s = s.replace(w, "")
    s = s.replace("グループ", "")
    return re.sub(r"[\s　・]", "", s).strip()


def flag_matrix(archive: Path, dates: pd.DatetimeIndex,
                codes: list[str]) -> pd.DataFrame:
    listed = set(json.loads((Path(__file__).resolve().parent
                             / "exp051_listed_names.json")
                            .read_text()))
    flag = pd.DataFrame(False, index=dates, columns=codes)
    dv = dates.to_numpy()
    for f in glob.glob(str(archive / "major" / "*.json")):
        code = Path(f).stem
        if code not in flag.columns:
            continue
        docs = json.loads(Path(f).read_text())
        states = []
        for d in sorted(docs, key=lambda r: str(r.get("SubDate", ""))):
            hit = any(
                (h.get("ShsRatio") or 0) >= 0.5
                and not any(e in str(h.get("HldrName", ""))
                            for e in EXCL)
                and norm(h.get("HldrName")) in listed
                for h in (d.get("Hldrs") or []))
            states.append((pd.Timestamp(d["SubDate"]), hit))
        if not states:
            continue
        sd = pd.DatetimeIndex([s[0] for s in states])
        sv = np.array([s[1] for s in states])
        idx = np.searchsorted(sd, dv, side="right") - 1
        flag[code] = np.where(idx >= 0,
                              sv[np.clip(idx, 0, len(sv) - 1)], False)
    return flag


def main(cache: Path, archive: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    o_np = panel["O"].to_numpy()
    c_np = panel["C"].ffill().to_numpy()
    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    bp_rank = sig["value_only"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    valid = comp.notna()
    score_a = ((comp.rank(axis=1, pct=True) + mom.where(valid))
               / 2.0).where(valid)
    flag = flag_matrix(archive, dates, codes)
    bonus = (flag & bp_rank.ge(0.5)).where(valid, False).fillna(False)
    long_score = (score_a + 0.10 * bonus.astype(float)).where(valid)
    short_score = score_a.where(~flag)
    snp = score_a.to_numpy()
    lnp = long_score.to_numpy()
    shp = short_score.to_numpy()

    diag = {}
    for pname, (a, b) in PERIODS.items():
        m = (dates >= a) & (dates <= b)
        diag[pname] = {
            "flagged_names_median": float(flag[m].sum(axis=1).median()),
            "long_bonus_days_share": float(
                (bonus[m].any(axis=1)).mean()),
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
            res[f"{pname}_A_sub_{cname}"] = E9.stats(pd.Series(
                E13.simulate2(lnp, shp, o_np, c_np, s, e, cost,
                              carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_sub_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_sub_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_sub_stress"]["profit"] > 0
            and ratio("full_A_sub_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
