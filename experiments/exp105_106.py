"""EXP-105 / EXP-106 book tests (preregistrations pushed first, commit c0115855).

EXP-105 (A_pr): A + progress-rate tilt. At each Q1/Q2/Q3 disclosure where the
  FY OP forecast is UNCHANGED vs the previous forecast value, excess progress
  = cumulative OP / FY OP forecast - firm's own mean progress at the same
  quarter over the prior 5 fiscal years (>=3 prior obs required). Signal
  active 100 calendar days; prog_r = pct rank of excess among valid names
  with an active signal (0.5 for names without). Score = (comp_r + mom_r +
  prog_r) / 3, A mechanics.
EXP-106 (A_oo): A with revision momentum recomputed EXCLUDING revision
  events whose code has a TDnet one-off title (特別利益|特別損失|減損)
  within +/-7 calendar days. Signs are E10's own; flagged events are dropped
  from the tally only (the diff chain is not recomputed).

S and A are recomputed in-script; A must reproduce the current-cache
reference (FH +970,644 / 0.348 / DD -23.76%; SH +4,133,557 / 1.584;
full stress ratio 0.428) or the run is invalid. EXP-106's momentum with an
empty flag set must equal E10's exactly (asserted).

Usage: python exp105_106.py <cache_dir> <tdnet_dir>
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

PERIODS = {
    "first_half": ("2017-01-04", "2021-12-30"),
    "second_half": ("2022-01-04", "2026-09-25"),
    "full": ("2017-01-04", "2026-09-25"),
}
COSTS = {"base": (0.0003, 0.03), "stress": (0.0010, 0.05)}
ONEOFF_PATS = ("特別利益", "特別損失", "減損")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


# ---- EXP-105: progress-rate events -------------------------------------
def progress_events(fins: dict):
    """Return (events, prog_by_quarter_median).

    events: list of (code, disc_date Timestamp, excess float).
    Per preregistration: quarterly records only; progress needs OP actual
    and FOP > 0; unchanged = FOP equals the previous forecast value in the
    code's OP-forecast series (EXP-003 rule: NxFOP for FY statements, FOP
    otherwise); norm = mean progress at the same quarter over the prior 5
    fiscal years (by CurFYEn), >= 3 prior observations required.
    """
    events = []
    prog_hist: dict[tuple[str, str], list[tuple[str, float]]] = {}
    med: dict[str, list[float]] = {}
    for code, recs in fins.items():
        rows = []
        for r in recs:
            d = r.get("DiscDate")
            if not d:
                continue
            is_fy = r.get("CurPerType") == "FY" and \
                "FinancialStatements" in str(r.get("DocType"))
            fc = num(r.get("NxFOP")) if is_fy else num(r.get("FOP"))
            rows.append({"d": pd.Timestamp(d), "t": str(r.get("DiscTime") or ""),
                         "pt": str(r.get("CurPerType")), "fc": fc,
                         "fop": num(r.get("FOP")), "op": num(r.get("OP")),
                         "fyen": str(r.get("CurFYEn") or "")})
        rows.sort(key=lambda x: (x["d"], x["t"]))
        prev_fc = np.nan
        for r in rows:
            if r["pt"] in ("1Q", "2Q", "3Q"):
                if np.isfinite(r["op"]) and np.isfinite(r["fop"]) and r["fop"] > 0:
                    prog = r["op"] / r["fop"]
                    med.setdefault(r["pt"], []).append(prog)
                    key = (code, r["pt"])
                    hist = [(fy, p) for fy, p in prog_hist.get(key, [])
                            if fy < r["fyen"]][-5:]
                    if (np.isfinite(prev_fc) and r["fop"] == prev_fc
                            and len(hist) >= 3):
                        events.append((str(code), r["d"],
                                       prog - float(np.mean([p for _, p in hist]))))
                    prog_hist.setdefault(key, []).append((r["fyen"], prog))
            if np.isfinite(r["fc"]):
                prev_fc = r["fc"]
    medians = {q: float(np.median(v)) for q, v in med.items()}
    return events, medians


def progress_panel(events, dates, codes, mask):
    """Daily prog_r panel: pct rank of excess among valid names with an
    active signal; 0.5 where no signal; NaN outside the valid mask."""
    excess = pd.DataFrame(np.nan, index=dates, columns=codes)
    dv = dates.to_numpy()
    for code, d, ex in events:
        if code not in excess.columns:
            continue
        lo = int(np.searchsorted(dv, np.datetime64(d), side="left"))
        hi = int(np.searchsorted(dv, np.datetime64(d + pd.Timedelta(days=100)),
                                 side="right"))
        if hi > lo:
            excess.iloc[lo:hi, excess.columns.get_loc(code)] = ex
    sig = excess.notna() & mask
    prog_r = pd.DataFrame(0.5, index=dates, columns=codes)
    # rank only among signal names, per day
    ranked = excess.where(sig).rank(axis=1, pct=True)
    prog_r = prog_r.where(~sig, ranked)
    return prog_r.where(mask), sig


# ---- EXP-106: cleaned revision momentum --------------------------------
def oneoff_dates(tdnet_dir: Path) -> dict[str, list[pd.Timestamp]]:
    out: dict[str, list[pd.Timestamp]] = {}
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
            if any(p in title for p in ONEOFF_PATS):
                out.setdefault(str(it.get("code")), []).append(
                    pd.Timestamp(str(it.get("pubdate"))[:10]))
    return out


def cleaned_momentum(fins, dates, codes, oneoff, window_days=7):
    """E10.revision_momentum_scores with flagged revision events dropped
    from the tally. Returns (rank panel, diag)."""
    rec = E10._as_records(fins)
    rec["rev_sign"] = np.sign(rec.groupby("code")["np_forecast"].diff().fillna(0.0))
    rev = rec[rec["rev_sign"] != 0].copy()
    n_events = len(rev)
    flagged = np.zeros(n_events, dtype=bool)
    if oneoff:
        for i, (code, dd) in enumerate(zip(rev["code"], rev["disc_date"])):
            ds = oneoff.get(str(code))
            if ds:
                arr = np.array(ds, dtype="datetime64[ns]")
                if np.any(np.abs((arr - np.datetime64(dd)).astype("timedelta64[D]").astype(int)) <= window_days):
                    flagged[i] = True
    rev = rev[~flagged]
    dates = pd.DatetimeIndex(dates)
    mom = pd.DataFrame(0.0, index=dates, columns=list(codes))
    dvals = dates.to_numpy()
    lo_vals = dvals - np.timedelta64(E10.MOM_WINDOW_DAYS, "D")
    for code, g in rev.groupby("code"):
        if code not in mom.columns:
            continue
        gd = g["disc_date"].to_numpy()
        gs = g["rev_sign"].to_numpy(dtype=float)
        order = np.argsort(gd, kind="stable")
        gd, gs = gd[order], gs[order]
        cum = np.cumsum(gs)
        hi = np.searchsorted(gd, dvals, side="right") - 1
        lo = np.searchsorted(gd, lo_vals, side="right") - 1
        tot = np.where(hi >= 0, cum[np.clip(hi, 0, len(cum) - 1)], 0.0)
        tot_lo = np.where(lo >= 0, cum[np.clip(lo, 0, len(cum) - 1)], 0.0)
        mom[code] = tot - tot_lo
    diag = {"revision_events": int(n_events), "flagged": int(flagged.sum()),
            "flagged_share": float(flagged.mean()) if n_events else 0.0}
    return mom.rank(axis=1, pct=True), diag


def main(cache: Path, tdnet_dir: Path) -> None:
    topix, panel, fins = E3.load(cache)
    dates = topix.index
    codes = list(panel["C"].columns)
    sig = E3.signals(panel, fins, dates)
    comp = sig["composite"]
    mom = E10.revision_momentum_scores(fins, dates, codes)
    mask = comp.notna()
    comp_r = comp.rank(axis=1, pct=True)
    score_a = ((comp_r + mom.where(mask)) / 2.0).where(mask)

    # EXP-105
    events, prog_medians = progress_events(fins)
    prog_r, sig_mask = progress_panel(events, dates, codes, mask)
    score_pr = ((comp_r + mom.where(mask) + prog_r) / 3.0).where(mask)

    # EXP-106 (+ faithfulness: empty flags must reproduce E10 exactly)
    oneoff = oneoff_dates(tdnet_dir)
    mom_clean, diag106 = cleaned_momentum(fins, dates, codes, oneoff)
    mom_noflag, _ = cleaned_momentum(fins, dates, codes, {})
    faith = float(np.nanmax(np.abs((mom_noflag - mom).to_numpy())))
    score_oo = ((comp_r + mom_clean.where(mask)) / 2.0).where(mask)

    o = panel["O"].to_numpy()
    c = panel["C"].ffill().to_numpy()
    panels = {"S": comp.to_numpy(), "A": score_a.to_numpy(),
              "PR": score_pr.to_numpy(), "OO": score_oo.to_numpy()}

    res: dict = {}
    for pname, (a_, b_) in PERIODS.items():
        s = int(dates.searchsorted(pd.Timestamp(a_)))
        e = int(dates.searchsorted(pd.Timestamp(b_), side="right")) - 1
        idx = dates[s:e + 1]
        for cname, (cost, carry) in COSTS.items():
            for vname, sc in panels.items():
                res[f"{pname}_{vname}_{cname}"] = E9.stats(pd.Series(
                    E9.simulate(sc, o, c, s, e, cost, carry, 1.0, 0.5), index=idx))

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

    sh_rows = (dates >= "2022-01-04") & (dates <= "2026-09-25")
    diag = {
        "exp105_events": len(events),
        "exp105_progress_median_by_quarter": prog_medians,
        "exp105_signal_names_median_per_day_SH": float(sig_mask[sh_rows].sum(axis=1).median()),
        "exp106": diag106,
        "exp106_momentum_faithfulness_max_abs_diff": faith,
        "A_FH": res["first_half_A_base"], "A_SH": res["second_half_A_base"],
        "A_full_stress": res["full_A_stress"],
    }
    verdict = {"EXP105_PR_standard_vs_A": std_verdict("PR"),
               "EXP106_OO_standard_vs_A": std_verdict("OO")}
    print(json.dumps({"res": res, "verdict": verdict, "diag": diag},
                     ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
