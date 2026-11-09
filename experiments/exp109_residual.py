"""EXP-109 book test (preregistration pushed first, commit 72aec692).

EXP-109 (A_res): A + unexpected initial-forecast residual tilt
(Kitagawa-Shuto). Episodes are FY FinancialStatements records; the residual
is the winsorised y = NxFNp/Eq minus its fitted value from an annual
(disclosure-calendar-year) cross-sectional OLS on prior-FY ROE, prior NP
growth, log prior sales and a loss dummy (y and continuous regressors
winsorised 1/99 within year before estimation; years with <30
post-screening episodes are void). Residual construction reproduces the
round-12 gate implementation (ws1_leftovers.py `ks_residuals`) exactly;
per preregistration completion 6, the episode set is ALL FY episodes
meeting the input requirements (not conditioned on EXP-080 habit
availability). The annual coefficients are estimated on the full calendar
year of episodes, exactly as registered (coefficient-timing caveat
disclosed in the preregistration; not "fixed" here).

Activation: from the day AFTER disclosure, persisting until the next FY
disclosure's resid activates; disclosures without a resid do not update
state. leg_r = 1 - pct_rank(resid) within A's valid set (average ranks for
ties), missing state = 0.5. A_res = (comp_r + mom_r + leg_r) / 3, A
mechanics (short 0.5).

S and A are recomputed in-script; A must reproduce the current-cache
reference (FH +970,644 / 0.348 / DD -23.76%; SH +4,133,557 / 1.584;
full stress ratio 0.428) or the run is invalid.

Usage: python exp109_residual.py <cache_dir> <out_dir>
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

A_REFERENCE = {
    "first_half_A_base": {"profit": 970644, "annual_over_dd": 0.348,
                          "max_dd_pct": -23.76},
    "second_half_A_base": {"profit": 4133557, "annual_over_dd": 1.584},
    "full_A_stress": {"annual_over_dd": 0.428},
}


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


# ---- episodes + residuals (gate construction, ws1_leftovers.ks_residuals)
def build_episodes(fins: dict) -> pd.DataFrame:
    """One row per FY FinancialStatements record, with the gate's prev_np
    semantics: prev_np = last finite FY-statement NP strictly before this
    record in the code's (DiscDate, DiscTime) sequence (captured before
    this record's own NP updates it). No habit conditioning."""
    rows_out = []
    for code, recs in fins.items():
        rows = []
        for r in recs:
            d = r.get("DiscDate")
            if not d:
                continue
            is_fy = r.get("CurPerType") == "FY" and \
                "FinancialStatements" in str(r.get("DocType"))
            if not is_fy:
                continue
            rows.append({"d": pd.Timestamp(d),
                         "t": str(r.get("DiscTime") or ""),
                         "np": num(r.get("NP")), "sales": num(r.get("Sales")),
                         "eq": num(r.get("Eq")), "nx": num(r.get("NxFNp"))})
        rows.sort(key=lambda x: (x["d"], x["t"]))
        prev_np = np.nan
        for r in rows:
            rows_out.append({"code": str(code), "disc": r["d"],
                             "F": r["nx"], "eq": r["eq"], "np": r["np"],
                             "sales": r["sales"], "prev_np": prev_np})
            if np.isfinite(r["np"]):
                prev_np = r["np"]
    return pd.DataFrame(rows_out)


def ks_residuals(df: pd.DataFrame):
    """Verbatim reproduction of the gate's residual construction."""
    df = df.copy()
    df["year"] = df["disc"].dt.year
    df = df[(df["eq"] > 0) & np.isfinite(df["F"]) & np.isfinite(df["np"])
            & (df["sales"] > 0)]
    with np.errstate(divide="ignore", invalid="ignore"):
        df["y"] = df["F"] / df["eq"]
        df["roe"] = df["np"] / df["eq"]
        df["growth"] = (df["np"] - df["prev_np"]) / df["prev_np"].abs()
    df["logsales"] = np.log(df["sales"])
    df["loss"] = (df["np"] < 0).astype(float)
    df = df[np.isfinite(df["growth"])]
    df["resid"] = np.nan
    kept_years = []
    void_years = []
    for yr, g in df.groupby("year"):
        if len(g) < 30:
            void_years.append((int(yr), len(g)))
            continue
        kept_years.append((int(yr), len(g)))
        cols = ["y", "roe", "growth", "logsales"]
        gg = g.copy()
        for c in cols:
            lo, hi = gg[c].quantile(0.01), gg[c].quantile(0.99)
            gg[c] = gg[c].clip(lo, hi)
        X = np.column_stack([np.ones(len(gg)), gg["roe"], gg["growth"],
                             gg["logsales"], gg["loss"]])
        beta, *_ = np.linalg.lstsq(X, gg["y"].to_numpy(), rcond=None)
        df.loc[g.index, "resid"] = gg["y"].to_numpy() - X @ beta
    return df, kept_years, void_years


def state_panel(episodes: pd.DataFrame, dates, codes) -> pd.DataFrame:
    """Daily resid state: for each code, the resid of the latest
    resid-bearing episode whose DiscDate is strictly before the trading
    date (activation from the day after disclosure). Episodes without a
    resid never enter the episode list used here, so they cannot update
    state."""
    panel = pd.DataFrame(np.nan, index=dates, columns=codes)
    dv = dates.to_numpy()
    ok = episodes[np.isfinite(episodes["resid"])]
    for code, g in ok.groupby("code"):
        if code not in panel.columns:
            continue
        g = g.sort_values("disc")
        ed = g["disc"].to_numpy()
        pos = np.searchsorted(ed, dv, side="left") - 1
        vals = np.where(pos >= 0,
                        g["resid"].to_numpy()[np.clip(pos, 0, len(g) - 1)],
                        np.nan)
        panel[code] = vals
    return panel


def main(cache: Path, out_dir: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    mask = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    score_a = ((comp_r + mom.where(mask)) / 2.0).where(mask)

    # EXP-109 residual leg
    raw_eps = build_episodes(fins)
    eps, kept_years, void_years = ks_residuals(raw_eps)
    state = state_panel(eps, dates, codes)
    has_state = state.notna() & mask
    ranked = state.where(has_state).rank(axis=1, pct=True)
    leg_r = pd.DataFrame(0.5, index=dates, columns=codes)
    leg_r = leg_r.where(~has_state, 1.0 - ranked).where(mask)
    score_res = ((comp_r + mom.where(mask) + leg_r) / 3.0).where(mask)

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()
    panels = {"S": comp.to_numpy(), "A": score_a.to_numpy(),
              "RES": score_res.to_numpy()}

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

    # ---- faithfulness gate: A must reproduce the registered references
    faith_checks = {}
    faithful = True
    for key, ref in A_REFERENCE.items():
        for k, v in ref.items():
            got = res[key][k]
            okk = (got == v)
            faith_checks[f"{key}.{k}"] = {"expected": v, "got": got,
                                          "match": bool(okk)}
            faithful = faithful and okk

    def std_verdict(v, base="A"):
        g = lambda p, k: res[f"{p}_{v}_base"][k]
        bb = lambda p, k: res[f"{p}_{base}_base"][k]
        c1 = all(g(p, "profit") > 0 for p in ("first_half", "second_half"))
        c2 = all((g(p, "annual_over_dd") or -9) > (bb(p, "annual_over_dd") or -9)
                 for p in ("first_half", "second_half"))
        gf, bf = res[f"full_{v}_stress"], res[f"full_{base}_stress"]
        c3 = gf["profit"] > 0 and (gf["annual_over_dd"] or -9) > \
            (bf["annual_over_dd"] or -9)
        return {"1_profit_positive_both_halves": bool(c1),
                "2_ratio_gt_base_both_halves": bool(c2),
                "3_full_stress_positive_and_ratio_gt_base": bool(c3),
                "promising": bool(c1 and c2 and c3)}

    verdict = std_verdict("RES") if faithful else None

    # ---- diagnostics
    eps_by_year = {}
    ok_eps = eps[np.isfinite(eps["resid"])]
    for yr, g in eps.groupby("year"):
        eps_by_year[int(yr)] = {
            "post_screening": int(len(g)),
            "with_resid": int(np.isfinite(g["resid"]).sum()),
        }
    resid_dist = {}
    for yr, g in ok_eps.groupby("year"):
        r = g["resid"]
        resid_dist[int(yr)] = {
            "n": int(len(r)), "mean": round(float(r.mean()), 4),
            "std": round(float(r.std()), 4),
            "min": round(float(r.min()), 4),
            "p25": round(float(r.quantile(0.25)), 4),
            "median": round(float(r.median()), 4),
            "p75": round(float(r.quantile(0.75)), 4),
            "max": round(float(r.max()), 4),
        }
    year_end_state = {}
    year_end_valid_state = {}
    for yr in range(2017, 2027):
        yd = dates[dates.year == yr]
        if len(yd) == 0:
            continue
        last = yd[-1]
        year_end_state[int(yr)] = int(state.loc[last].notna().sum())
        year_end_valid_state[int(yr)] = int(has_state.loc[last].sum())
    diag = {
        "raw_fy_episodes": int(len(raw_eps)),
        "post_screening_episodes": int(len(eps)),
        "episodes_with_resid": int(len(ok_eps)),
        "codes_with_resid": int(ok_eps["code"].nunique()),
        "kept_years": {int(y): int(n) for y, n in kept_years},
        "void_years": {int(y): int(n) for y, n in void_years},
        "episodes_by_year": eps_by_year,
        "resid_distribution_by_year": resid_dist,
        "names_with_state_year_end": year_end_state,
        "valid_names_with_state_year_end": year_end_valid_state,
        "nonneutral_share_valid_namedays": float(
            has_state.to_numpy().sum() / mask.to_numpy().sum()),
        "A_FH": res["first_half_A_base"], "A_SH": res["second_half_A_base"],
        "A_full_stress": res["full_A_stress"],
    }

    out = {"faithful": bool(faithful), "faith_checks": faith_checks,
           "res": res, "verdict": verdict, "diag": diag}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str))
    eps_out = eps.copy()
    eps_out["disc"] = eps_out["disc"].astype(str)
    eps_out.to_csv(out_dir / "episodes.csv", index=False)
    print(json.dumps({"faithful": bool(faithful),
                      "faith_checks": faith_checks,
                      "verdict": verdict,
                      "RES_FH": res["first_half_RES_base"],
                      "RES_SH": res["second_half_RES_base"],
                      "RES_full_stress": res["full_RES_stress"],
                      "A_FH": res["first_half_A_base"],
                      "A_SH": res["second_half_A_base"],
                      "A_full_stress": res["full_A_stress"],
                      "diag_summary": {
                          "raw_fy_episodes": diag["raw_fy_episodes"],
                          "post_screening": diag["post_screening_episodes"],
                          "with_resid": diag["episodes_with_resid"],
                          "codes_with_resid": diag["codes_with_resid"],
                          "kept_years": diag["kept_years"],
                          "void_years": diag["void_years"],
                          "nonneutral_share":
                              diag["nonneutral_share_valid_namedays"],
                      }}, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
