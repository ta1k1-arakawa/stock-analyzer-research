"""EXP-012: GPA blend / swap variants of the EXP-009 long-short S.

Pre-registration: docs/experiments/EXP-012_PREREGISTRATION.md
Amendment 1: docs/experiments/EXP-012_AMENDMENT_1.md
  - GPA data source is the EDINET API v2 (free) instead of J-Quants Premium:
    annual securities reports (docTypeCode 120, corrections 130), type=5 CSV.
    GPA = gross profit / total assets from the SAME filing, available from
    the EDINET submission date. Hypothesis, variants and criteria unchanged.

Data handling for the EDINET panel (approved by the user on 2026-10-30):
  1. Duplicate rows are removed by doc_id (restart reprocessing artefact;
     duplicates are byte-identical).
  2. A code's GPA on a day is its latest filing's GPA by submission
     datetime. Correction filings (130, whose periodEnd is null in the
     EDINET listing) therefore overwrite the original value from their own
     submission date, exactly as Amendment 1 specifies.
  3. A code with no GPA available gets the neutral rank 0.5, per the
     pre-registration.

Design (incremental test, everything else identical to EXP-009 S / EXP-010):
  - S : EXP-009 long-short on the composite score (B/P rank + forecast ROE
        rank), recomputed here on the same cache for a fair head-to-head.
  - A : blend  - profitability leg = (forecast-ROE rank + GPA rank) / 2,
        score = (B/P rank + profitability leg) / 2.
  - B : swap   - score = (B/P rank + GPA rank) / 2.
  Legs are daily cross-sectional percentile ranks over the eligible
  universe, exactly as EXP-003 computes the B/P and ROE legs; the GPA rank
  is computed over eligible codes that have a GPA, with 0.5 for the rest.

Usage:
    python experiments/exp012_gpa_blend.py <cache_dir> <gpa_csv>
    # e.g. python experiments/exp012_gpa_blend.py data/jquants_exp002 \
    #          data/edinet_exp012/gpa.csv
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

BUDGET = 2_000_000
PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
# (one-way trading cost, annual short carry) -- identical to EXP-009
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}


# ----------------------------------------------------------------------------
# GPA leg (point-in-time, from the EDINET panel built by exp012_fetch_edinet)
# ----------------------------------------------------------------------------
def gpa_panel(gpa_csv: Path, dates, codes) -> pd.DataFrame:
    """Raw GPA per (date, code): latest filing by submission date, carried
    forward until the next filing. NaN before a code's first filing."""
    g = pd.read_csv(gpa_csv, dtype={"code": str})
    g = g.drop_duplicates(subset=["doc_id"], keep="first")
    g["submit_date"] = pd.to_datetime(
        g["submit_datetime"].str.slice(0, 10), errors="coerce")
    g = g.dropna(subset=["submit_date", "gpa"])
    dates = pd.DatetimeIndex(dates)
    dvals = dates.to_numpy()
    raw = pd.DataFrame(np.nan, index=dates, columns=list(codes))
    for code, grp in g.groupby("code"):
        if code not in raw.columns:
            continue
        grp = grp.sort_values("submit_date")
        gd = grp["submit_date"].to_numpy()
        gv = grp["gpa"].to_numpy(dtype=float)
        idx = np.searchsorted(gd, dvals, side="right") - 1
        raw[code] = np.where(idx >= 0, gv[np.clip(idx, 0, len(gv) - 1)],
                             np.nan)
    return raw


def gpa_ranks(raw: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    """Percentile rank of GPA among eligible codes that have one; eligible
    codes without a GPA get the neutral 0.5; ineligible stay NaN."""
    r = raw.where(mask).rank(axis=1, pct=True)
    return r.where(raw.where(mask).notna(), 0.5).where(mask)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main(cache: Path, gpa_csv: Path) -> None:
    if not (cache / "topix.json").exists():
        raise SystemExit(f"cache not found: {cache} (expected topix.json inside)")
    if not gpa_csv.exists():
        raise SystemExit(f"GPA panel not found: {gpa_csv}")
    topix, panel, fins = E3.load(cache)
    dates = topix.index

    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    bp_r = sig["value_only"]
    roe_r = sig["profit_only"]
    codes = list(comp.columns)
    mask = comp.notna()

    raw_gpa = gpa_panel(gpa_csv, dates, codes)
    gpa_r = gpa_ranks(raw_gpa, mask)
    score_a = ((bp_r + (roe_r + gpa_r) / 2.0) / 2.0).where(mask)
    score_b = ((bp_r + gpa_r) / 2.0).where(mask)

    score = comp.to_numpy()
    score_a_np = score_a.to_numpy()
    score_b_np = score_b.to_numpy()
    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()

    variants = {"S": score, "A": score_a_np, "B": score_b_np}
    res: dict = {}
    for pname, (a, b) in PERIODS.items():
        start = int(dates.searchsorted(pd.Timestamp(a)))
        end = int(dates.searchsorted(pd.Timestamp(b), side="right")) - 1
        idx = dates[start : end + 1]
        for cname, (cost, carry) in COSTS.items():
            for v, sc in variants.items():
                res[f"{pname}_{v}_{cname}"] = E9.stats(pd.Series(
                    E9.simulate(sc, o, c, start, end, cost, carry, 1.0, 0.5),
                    index=idx))

    def verdict() -> dict:
        out = {}
        for v in ("A", "B"):
            g = lambda p, k: res[f"{p}_{v}_base"][k]  # noqa: E731
            s = lambda p, k: res[f"{p}_S_base"][k]  # noqa: E731
            c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
            c2 = all((g(p, "annual_over_dd") or -9) > (s(p, "annual_over_dd") or -9)
                     for p in ("first_half", "second_half"))
            gf, sf = res[f"full_{v}_stress"], res["full_S_stress"]
            c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > (sf["annual_over_dd"] or -9)
            out[v] = {
                "1_profit_positive_both_halves": bool(c1),
                "2_ratio_gt_S_both_halves": bool(c2),
                "3_full_stress_positive_and_ratio_gt_S": bool(c3),
                "promising": bool(c1 and c2 and c3),
            }
        return out

    elig = mask.to_numpy()
    diag = {
        "gpa_rank_mean_row_std": float(gpa_r.std(axis=1).mean()),
        "eligible_cells_with_gpa_share": float(
            (raw_gpa.notna().to_numpy() & elig).sum() / elig.sum()),
        "codes_with_any_gpa": int(raw_gpa.notna().any().sum()),
    }
    print(json.dumps({"res": res, "verdict": verdict(), "diag": diag},
                     ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
