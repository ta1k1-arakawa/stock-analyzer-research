"""EXP-107 book test (preregistration pushed first, commit 897e2e64).

A_lp: A + Lazy Prices tilt. For each code, consecutive-PerEn-year
securities-report pairs give sim = character-bigram Jaccard (set,
whitespace removed) of the BusinessRisksTextBlock, attached to the
LATER filing (extraction identical to gate1_extract.py; pairs.csv is
built by extract_pairs.py). Point-in-time: sim activates the day AFTER
the later filing's submission date (state at day t = sim of the latest
pair-bearing filing with submit < t), persists until the next pair
activates, and is NOT updated by filings whose pair is uncomputable.
lp_r = percentile rank of sim among A's valid names that hold a state
(higher sim = higher rank, average ties); names without state are
neutral 0.5. Score A_lp = (comp_r + mom_r + lp_r) / 3, A mechanics
(long 1.0 / short 0.5).

S and A are recomputed in-script; A must reproduce the current-cache
reference (FH +970,644 / 0.348 / DD -23.76%; SH +4,133,557 / 1.584;
full stress ratio 0.428) or the run is invalid and reported as such.
Judgement: standard 3 criteria vs A, exactly as preregistered. No
MD&A-based variant is run (registration forbids it); the MD&A
similarity distribution is reference diagnostic only.

Usage: python exp107_lazy.py <cache_dir> <pairs_csv>
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
A_REF = {"first_half_A_base": (970644, 0.348),
         "second_half_A_base": (4133557, 1.584),
         "full_A_stress_ratio": 0.428}


def lp_panel(pairs: pd.DataFrame, dates, codes, mask):
    """Return (lp_r panel masked to A's valid set, has_state & mask).

    State(t) per code = sim of the latest pair-bearing filing with
    submit < t (strictly: activation starts on the first trading day
    after the submission date).
    """
    state = pd.DataFrame(np.nan, index=dates, columns=codes)
    dv = dates.to_numpy()
    pairs = pairs.sort_values(["code", "submit"], kind="stable")
    for code, submit, sim in zip(pairs["code"], pairs["submit"],
                                 pairs["sim_risk"]):
        if code not in state.columns:
            continue
        lo = int(np.searchsorted(dv, np.datetime64(submit), side="right"))
        if lo < len(dv):
            state.iloc[lo:, state.columns.get_loc(code)] = sim
    has = state.notna() & mask
    ranked = state.where(has).rank(axis=1, pct=True)
    lp_r = pd.DataFrame(0.5, index=dates, columns=codes)
    lp_r = lp_r.where(~has, ranked)
    return lp_r.where(mask), has


def main(cache: Path, pairs_csv: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    mask = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    score_a = ((comp_r + mom.where(mask)) / 2.0).where(mask)

    pairs = pd.read_csv(pairs_csv, dtype={"code": str})
    pairs["submit"] = pd.to_datetime(pairs["submit"])
    lp_r, has = lp_panel(pairs, dates, codes, mask)
    score_lp = ((comp_r + mom.where(mask) + lp_r) / 3.0).where(mask)

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()
    panels = {"S": comp.to_numpy(), "A": score_a.to_numpy(),
              "LP": score_lp.to_numpy()}
    res: dict = {}
    for pname, (a_, b_) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a_)))
        e = int(dates.searchsorted(pd.Timestamp(b_), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            for vname, sc in panels.items():
                res[f"{pname}_{vname}_{cname}"] = E9.stats(pd.Series(
                    E9.simulate(sc, o, c, s, e, cost, carry, 1.0, 0.5),
                    index=idx))

    faith = {
        "FH_profit_match": bool(res["first_half_A_base"]["profit"]
            == A_REF["first_half_A_base"][0]),
        "FH_ratio_match": bool(res["first_half_A_base"]["annual_over_dd"]
            == A_REF["first_half_A_base"][1]),
        "SH_profit_match": bool(res["second_half_A_base"]["profit"]
            == A_REF["second_half_A_base"][0]),
        "SH_ratio_match": bool(res["second_half_A_base"]["annual_over_dd"]
            == A_REF["second_half_A_base"][1]),
        "full_stress_ratio_match": bool(
            res["full_A_stress"]["annual_over_dd"]
            == A_REF["full_A_stress_ratio"]),
    }
    faith["all_match"] = bool(all(faith.values()))

    def std_verdict(v, base="A"):
        g = lambda p, k: res[f"{p}_{v}_base"][k]
        bb = lambda p, k: res[f"{p}_{base}_base"][k]
        c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
        c2 = all((g(p, "annual_over_dd") or -9) > (bb(p, "annual_over_dd") or -9)
                 for p in ("first_half", "second_half"))
        gf, bf = res[f"full_{v}_stress"], res[f"full_{base}_stress"]
        c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > (bf["annual_over_dd"] or -9)
        return {"1_profit_positive_both_halves": bool(c1),
                "2_ratio_gt_base_both_halves": bool(c2),
                "3_full_stress_positive_and_ratio_gt_base": bool(c3),
                "promising": bool(c1 and c2 and c3)}

    # diagnostics (no returns involved)
    yrs = dates.year
    state_names_eoy, state_names_med = {}, {}
    for y in sorted(set(yrs)):
        sel = has[yrs == y]
        if len(sel):
            state_names_eoy[int(y)] = int(sel.iloc[-1].sum())
            state_names_med[int(y)] = float(sel.sum(axis=1).median())
    date_ok = np.asarray((dates >= "2017-01-04")
                         & (dates <= "2026-09-25"))
    valid_np = mask.to_numpy() & date_ok[:, None]
    has_np = has.to_numpy()
    diag = {
        "pairs_built": int(len(pairs)),
        "pairs_codes": int(pairs["code"].nunique()),
        "state_names_at_year_end": state_names_eoy,
        "state_names_median_per_day_by_year": state_names_med,
        "share_valid_namedays_with_state": float(
            (has_np & valid_np).sum() / valid_np.sum()),
        "share_days_with_any_state": float(
            has_np[date_ok].any(axis=1).mean()),
        "A_FH": res["first_half_A_base"], "A_SH": res["second_half_A_base"],
        "A_full_stress": res["full_A_stress"],
    }
    out = {"res": res, "faithfulness": faith,
           "verdict": {"EXP107_LP_standard_vs_A": std_verdict("LP")},
           "diag": diag}
    Path(__file__).with_name("result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
