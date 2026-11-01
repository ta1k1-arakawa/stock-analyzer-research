"""EXP-029: cross-holding reduction tilt from EDINET annual reports.

Preregistration: docs/experiments/EXP-029_PREREGISTRATION.md
Processing rules: docs/experiments/EXP-029_AMENDMENT_1.md (doc_id
dedup; a correction filing replaces the ratio of the code's most
recent annual report from the correction's submission date).

Signal: ratio = InvestmentSecurities / NetAssets per fiscal year;
reduction = previous year's ratio - latest year's ratio, usable from
the first trading day on/after the submission date of the filing that
establishes the pair, forward-filled. A_cross = (composite rank +
revision-momentum rank + reduction rank) / 3 on A's valid set, with
missing reduction ranked neutral 0.5. Coverage gate: median daily
share of A-valid names with a non-missing signal must be >= 50%.
Judged against A (recomputed; S also reported) by the standard three
criteria. Positive ratios only; net assets <= 0 rows already carry a
blank ratio in cross.csv and are dropped here.

Usage:
    python experiments/exp029_cross_holding.py <cache_dir> <cross_csv>
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

PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
GATE = 0.50


def build_events(cross_csv: Path):
    """Per code: list of (submit_date, reduction or None) in submit
    order, after dedup and correction handling (Amendment 1)."""
    df = pd.read_csv(cross_csv, dtype={"code": str})
    n_dup = int(df.duplicated(subset=["doc_id"]).sum())
    df = df.drop_duplicates(subset=["doc_id"]).copy()
    df = df[df["ratio"].notna()]
    df["submit"] = pd.to_datetime(df["submit_datetime"]).dt.normalize()
    df = df.sort_values(["code", "submit", "doc_id"])
    events: dict[str, list] = {}
    diag = {"dup_removed": n_dup, "corr_applied": 0, "corr_ignored": 0}
    for code, g in df.groupby("code"):
        ratios: dict[str, float] = {}
        ev: list = []
        for _, r in g.iterrows():
            if int(r["doc_type"]) == 130:
                if not ratios:
                    diag["corr_ignored"] += 1
                    continue
                latest = max(ratios)
                ratios[latest] = float(r["ratio"])
                diag["corr_applied"] += 1
            else:
                if pd.isna(r["period_end"]):
                    continue
                ratios[str(r["period_end"])] = float(r["ratio"])
            if len(ratios) >= 2:
                ks = sorted(ratios)
                ev.append((r["submit"],
                           ratios[ks[-2]] - ratios[ks[-1]]))
            else:
                ev.append((r["submit"], None))
        events[code] = ev
    return events, diag


def signal_frame(events, dates: pd.DatetimeIndex,
                 codes: list[str]) -> pd.DataFrame:
    out = pd.DataFrame(np.nan, index=dates, columns=codes, dtype=float)
    for code, ev in events.items():
        if code not in out.columns:
            continue
        col = np.full(len(dates), np.nan)
        for submit, val in ev:
            i = int(dates.searchsorted(submit))
            if i < len(dates):
                col[i] = np.nan if val is None else val
        s = pd.Series(col).ffill()
        out[code] = s.to_numpy()
    return out


def main(cache: Path, cross_csv: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    comp = E3.signals(panel, fins, dates)["composite"]
    codes = list(comp.columns)
    mom = E10.revision_momentum_scores(fins, dates, codes)

    events, diag = build_events(cross_csv)
    sig = signal_frame(events, dates, codes)

    valid = comp.notna()
    cov = (sig.notna() & valid).sum(axis=1) / valid.sum(axis=1)
    win = (dates >= pd.Timestamp("2017-01-04")) \
        & (dates <= pd.Timestamp("2026-09-25"))
    med_cov = float(cov[win].median())
    diag["median_coverage"] = med_cov
    diag["codes_with_signal"] = int(sig.notna().any().sum())
    if med_cov < GATE:
        print(json.dumps({"gate_failed": True, "diag": diag},
                         ensure_ascii=False, indent=1))
        return

    comp_r = comp.rank(axis=1, pct=True)
    cross_r = sig.rank(axis=1, pct=True).where(sig.notna(), 0.5)
    score_a = ((comp_r + mom.where(valid)) / 2.0).where(valid)
    score_x = ((comp_r + mom.where(valid) + cross_r) / 3.0).where(valid)

    o = panel["O"].to_numpy()
    c_ff = panel["C"].ffill().to_numpy()
    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start:end + 1]
        for cname, (cost, carry) in COSTS.items():
            res[f"{pname}_S_{cname}"] = E9.stats(pd.Series(
                E9.simulate(comp.to_numpy(), o, c_ff, start, end, cost,
                            carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_a.to_numpy(), o, c_ff, start, end,
                            cost, carry, 1.0, 0.5), index=idx))
            res[f"{pname}_A_cross_{cname}"] = E9.stats(pd.Series(
                E9.simulate(score_x.to_numpy(), o, c_ff, start, end,
                            cost, carry, 1.0, 0.5), index=idx))

    def ratio(k):
        return res[k]["annual_over_dd"]

    verdict = {
        "1_profit_positive_both_halves": bool(all(
            res[f"{p}_A_cross_base"]["profit"] > 0
            for p in ("first_half", "second_half"))),
        "2_ratio_beats_A_both_halves": bool(all(
            ratio(f"{p}_A_cross_base") > ratio(f"{p}_A_base")
            for p in ("first_half", "second_half"))),
        "3_full_stress_beats_A": bool(
            res["full_A_cross_stress"]["profit"] > 0
            and ratio("full_A_cross_stress") > ratio("full_A_stress")),
    }
    verdict["promising"] = bool(all(verdict.values()))
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
