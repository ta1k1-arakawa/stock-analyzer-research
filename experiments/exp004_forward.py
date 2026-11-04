"""EXP-004: forward comparison of three 20-stock rotation portfolios.

  R  rule      : EXP-003 composite (B/P rank + forecast-ROE rank). Real money follows this one.
  M  LightGBM  : same rotation, stocks ranked by a LightGBM model frozen before the start.
  L  Claude    : R's ranking, but skips stocks whose latest earnings report (決算短信) Claude rates
                 as a likely value trap (trap_risk >= 4).

Pre-registration: docs/experiments/EXP-004_PREREGISTRATION.md
Commands (run in this order every trading day after the data is published, ~20:00 JST):
  python experiments/exp004_forward.py update-data   # free data: yfinance prices + TDnet XBRL summaries
  python experiments/exp004_forward.py score         # Claude Code (your Claude subscription) reads new 決算短信
  python experiments/exp004_forward.py step          # executes today's paper orders, decides tomorrow's
  python experiments/exp004_forward.py notify        # sends R's order sheet to Slack (SLACK_WEBHOOK_URL)
  python experiments/exp004_forward.py eval-l        # Amendment 1: rating-level check of Claude (L)
One-time, before the start (used the J-Quants cache while the subscription was active):
  python experiments/exp004_forward.py train         # fits and freezes the LightGBM model
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp003_rotation as E3  # noqa: E402
import free_data as FD  # noqa: E402
import exp010_earnings_momentum as E10  # noqa: E402  (EXP-010 revision-momentum leg)

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "jquants_exp002"
FWD = ROOT / "forward"
MODEL = ROOT / "experiments" / "models" / "exp004_lgbm.txt"
MODEL_META = ROOT / "experiments" / "models" / "exp004_lgbm_meta.json"
JQ = "https://api.jquants.com/v2"
START = pd.Timestamp("2026-09-28")  # first trading day (all tranches buy at the open)
BUDGET = 400_000
COST = 0.0003
N_TRANCHES, PER_TRANCHE, HOLD_DAYS = 10, 2, 20
SPARE = 2  # extra names per tranche in case an open does not trade
TRAIN_END = pd.Timestamp("2026-08-26")  # last signal date whose 20-day target is fully known
TRAP_MAX = 3  # L keeps stocks with trap_risk <= 3; unscored stocks count as 3
PDF_PAGES = 6  # the summary and the management discussion come first in a 決算短信
MAX_CALLS_PER_RUN = 25  # stay well inside the subscription's usage limits per daily run
PORTFOLIOS = ("R", "M", "L", "W", "V", "S", "A", "AR", "AA", "AV", "A75", "AT", "AF", "A75F", "AV75", "AVF", "AV75F", "ATOW75")
SHORT_FRAC, SHORT_CARRY = 0.5, 0.03  # EXP-009 S: short the bottom names for 50% of equity, 3%/yr carry
SHORT_FRAC_BY = {"A75": 0.75, "A75F": 0.75, "AV75": 0.75, "AV75F": 0.75, "ATOW75": 0.75}  # EXP-074: A75 runs A's score with a 0.75 short fraction (operational DD test, paper only); EXP-082: A75F/AV75 stack the same lever on AF/AV; EXP-086: AV75F/ATOW75 likewise
REAL = "V"  # EXP-008: real money follows V (same picks as R, cash split by 1/volatility)


# ----------------------------------------------------------------------------
# data update (per code only; never date-wide requests)
# ----------------------------------------------------------------------------

def update_data() -> None:
    codes = (FWD / "universe.txt").read_text().split()
    print(json.dumps({"prices": FD.update_prices(codes), "fundamentals": FD.update_fundamentals(codes, days=10),
                      "restate_events": FD.update_restate_events(codes, days=10),
                      "large_events": update_large_events(codes, days=10),
                      "voluntary_events": update_voluntary_events(codes, days=10)},
                     ensure_ascii=False))


_VOLUNTARY_PATS = ("決算説明", "説明会", "個人投資家", "中期経営計画")


def update_voluntary_events(codes: list[str], days: int = 10) -> dict:
    """EXP-055: append voluntary-disclosure events (EXP-054 title
    patterns) from the TDnet daily lists to
    forward/voluntary_events.csv."""
    path = FWD / "voluntary_events.csv"
    seen, rows = set(), []
    if path.exists():
        ev = pd.read_csv(path, dtype={"code": str})
        for _, r in ev.iterrows():
            row = {"date": str(r["date"])[:10], "code": r["code"],
                   "title": str(r.get("title", ""))}
            rows.append(row)
            seen.add((row["date"], row["code"], row["title"]))
    universe = set(codes)
    added = 0
    today = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None).normalize()
    for back in range(days):
        day = today - pd.Timedelta(days=back)
        for d in FD.list_rows(day):
            if d["code"] not in universe:
                continue
            if not any(p in d["title"] for p in _VOLUNTARY_PATS):
                continue
            key = (str(day.date()), d["code"], d["title"])
            if key in seen:
                continue
            seen.add(key)
            rows.append({"date": key[0], "code": key[1], "title": key[2]})
            added += 1
    rows.sort(key=lambda r: (r["date"], r["code"]))
    pd.DataFrame(rows, columns=["date", "code", "title"]).to_csv(path, index=False)
    return {"added": added, "total": len(rows)}


_IMPPROP_NONE = re.compile(r"(該当|記載)(事項)?(なし|無し|はありません|ございません)")


def _impprop_present(h: dict) -> bool:
    """EXP-052: ImpProp free text indicates important proposals."""
    v = h.get("ImpProp")
    return isinstance(v, str) and bool(v.strip()) and not _IMPPROP_NONE.search(v)


def update_large_events(codes: list[str], days: int = 10) -> dict:
    """EXP-053: append qualifying activist large-holding events
    (EXP-052 rules) to forward/large_events.csv, fetched from
    J-Quants by submission date. Never raises: a feed failure must
    not stop the daily routine."""
    path = FWD / "large_events.csv"
    seen, rows = set(), []
    if path.exists():
        ev = pd.read_csv(path, dtype={"code": str})
        for _, r in ev.iterrows():
            rows.append({"date": str(r["date"])[:10], "code": r["code"]})
            seen.add((str(r["date"])[:10], r["code"]))
    universe = set(codes)
    added = 0
    try:
        sys.path.insert(0, str(Path.home() / "workspace" / "custom-connectors" / "custom.jquants" / "bin"))
        from jquants_api import get_json
        today = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None).normalize()
        for back in range(days):
            day = today - pd.Timedelta(days=back)
            data = get_json("/v2/edinet/large-volume-shareholders",
                            {"date": day.strftime("%Y%m%d")})
            for d in data.get("data", []):
                raw = str(d.get("Code", ""))
                code = raw[:4] if len(raw) == 5 and raw.endswith("0") else raw
                if code not in universe:
                    continue
                t = str(d.get("LargeHldgTypeCode"))
                if t not in ("1", "2"):
                    continue
                if not any(_impprop_present(h) for h in (d.get("Hldrs") or [])):
                    continue
                if t == "2":
                    try:
                        if float(d.get("TotalShsRatio")) - float(d.get("TotalShsRatioLast")) < 0.01:
                            continue
                    except (TypeError, ValueError):
                        continue
                key = (str(d.get("SubDate"))[:10], code)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"date": key[0], "code": code})
                added += 1
    except Exception as e:  # feed failure: keep existing events
        print(f"large_events update failed: {str(e)[:200]}")
    rows.sort(key=lambda r: (r["date"], r["code"]))
    pd.DataFrame(rows, columns=["date", "code"]).to_csv(path, index=False)
    return {"added": added, "total": len(rows)}


def next_trading_day(after: pd.Timestamp) -> pd.Timestamp:
    """Next weekday that is not a TSE holiday (forward/tse_holidays.txt)."""
    lines = (FWD / "tse_holidays.txt").read_text().splitlines()
    holidays = {pd.Timestamp(x) for x in lines if x and not x.startswith("#")}
    if after >= max(holidays):
        raise SystemExit("forward/tse_holidays.txt does not cover the next trading day; add the next year's holidays")
    d = after + pd.Timedelta(days=1)
    while d.weekday() >= 5 or d in holidays:
        d += pd.Timedelta(days=1)
    return d


# ----------------------------------------------------------------------------
# LightGBM features (cross-sectional percentile ranks among eligible stocks)
# ----------------------------------------------------------------------------

FEATURES = ["bp", "roe", "mom20", "mom60", "mom250", "vol60", "size", "liq", "roe_chg60"]


def features(panel, fins, dates) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    sig = E3.signals(panel, fins, dates)
    ok = sig["composite"].notna()
    eq, npf = E3.fundamentals(fins, dates)
    cols = panel["C"].columns
    eq, npf = eq.reindex(columns=cols), npf.reindex(columns=cols)
    c = panel["C"].ffill()
    ret = c.pct_change(fill_method=None)
    raw = {
        "bp": sig["value_only"],
        "roe": sig["profit_only"],
        "mom20": c / c.shift(20) - 1,
        "mom60": c / c.shift(60) - 1,
        "mom250": c.shift(20) / c.shift(250) - 1,
        "vol60": ret.rolling(60, min_periods=40).std(),
        "size": np.log(panel["MktCap"]),
        "liq": np.log(panel["Va"].fillna(0.0).rolling(20, min_periods=20).mean() + 1.0),
        "roe_chg60": (npf - npf.shift(60)) / eq,
    }
    feats = {k: v.where(ok).rank(axis=1, pct=True) for k, v in raw.items()}
    return feats, ok


def train() -> None:
    import lightgbm as lgb

    topix, panel, fins = E3.load(CACHE)
    dates = topix.index
    feats, ok = features(panel, fins, dates)
    o = panel["O"]
    fwd = o.shift(-(HOLD_DAYS + 1)) / o.shift(-1) - 1  # buy next open, sell 20 trading days later at the open
    target = fwd.where(ok).rank(axis=1, pct=True)
    first = int(dates.searchsorted(pd.Timestamp("2017-01-04")))
    last = int(dates.searchsorted(TRAIN_END, side="right")) - 1
    rows = []
    for t in range(first, last + 1, 5):
        d = dates[t]
        x = pd.DataFrame({k: v.loc[d] for k, v in feats.items()})
        x["y"] = target.loc[d]
        rows.append(x.dropna(subset=["y"]))
    data = pd.concat(rows)
    model = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=200,
                              subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=0,
                              deterministic=True, force_row_wise=True, verbose=-1)
    model.fit(data[FEATURES], data["y"])
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(MODEL))
    meta = {
        "trained_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "signal_dates": [str(dates[first].date()), str(dates[last].date())], "every_n_days": 5,
        "rows": int(len(data)), "features": FEATURES,
        "target": "percentile rank of open(t+21)/open(t+1)-1 among eligible stocks",
        "params": model.get_params(),
        "feature_importance_gain": dict(zip(FEATURES, [round(float(g), 1) for g in
                                                      model.booster_.feature_importance("gain")])),
        "model_sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest(),
    }
    MODEL_META.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({k: v for k, v in meta.items() if k != "params"}, ensure_ascii=False, indent=1))


def model_scores(feats: dict[str, pd.DataFrame], ok: pd.DataFrame, d: pd.Timestamp) -> pd.Series:
    import lightgbm as lgb

    meta = json.loads(MODEL_META.read_text())
    if hashlib.sha256(MODEL.read_bytes()).hexdigest() != meta["model_sha256"]:
        raise SystemExit("frozen LightGBM model hash mismatch")
    booster = lgb.Booster(model_file=str(MODEL))
    x = pd.DataFrame({k: feats[k].loc[d] for k in FEATURES})[ok.loc[d]]
    return pd.Series(booster.predict(x[FEATURES]), index=x.index)


# ----------------------------------------------------------------------------
# Claude reads each new 決算短信 (earnings report) once, when it is published
# ----------------------------------------------------------------------------

SCORE_FILE = FWD / "llm_scores.jsonl"
SYSTEM = (
    "あなたは日本株の決算短信を読む株式アナリストです。"
    "この会社は株価が割安（PBRが低い）で、会社予想ベースのROEも高い銘柄の候補です。"
    "決算短信を読み、今後3〜6か月でこの会社の稼ぐ力が落ちる、または会社予想が下方修正される可能性"
    "（いわゆる割安のワナ）がどれくらいあるかを1〜5で評価してください。"
    "5=非常に高い（一時的な利益で予想がかさ上げされている、受注や需要が急に弱っている、"
    "継続企業の前提に注記がある、など）、3=どちらとも言えない、1=非常に低い（需要が堅調で予想も保守的）。"
    "書かれていることだけを根拠にし、株価の動きは考えないでください。"
)


def first_pages(pdf: bytes, n: int) -> bytes:
    from pypdf import PdfReader, PdfWriter

    reader, writer = PdfReader(io.BytesIO(pdf)), PdfWriter()
    for page in reader.pages[:n]:
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def ask_claude(pdf_path: Path) -> dict:
    """Run Claude Code headless (authenticated with CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`)."""
    prompt = (SYSTEM + f"\n\n決算短信の PDF：{pdf_path}\nこのファイルを読み、次の JSON だけを1行で答えてください："
              '{"trap_risk": 1〜5 の整数, "reason": "日本語で1〜2文"}')
    try:
        run = subprocess.run(["claude", "-p", prompt, "--output-format", "json", "--allowedTools", "Read",
                              "--max-turns", "4"], capture_output=True, text=True, timeout=600)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"status": f"cli_{type(e).__name__}"}
    if run.returncode != 0:
        return {"status": "cli_error", "detail": run.stderr[-300:]}
    try:
        result = json.loads(run.stdout).get("result", "")
        m = re.search(r"\{[^{}]*\"trap_risk\"[^{}]*\}", result)
        out = json.loads(m.group(0))
        risk = int(out["trap_risk"])
        if risk not in (1, 2, 3, 4, 5):
            raise ValueError
    except (json.JSONDecodeError, AttributeError, KeyError, TypeError, ValueError):
        return {"status": "bad_output"}
    return {"status": "ok", "trap_risk": risk, "reason": str(out.get("reason", ""))[:300]}


REVISION_PROMPT = (
    "これは日本の上場会社の「業績予想の修正に関するお知らせ」の PDF です。"
    "修正後の通期（今期）の「親会社株主に帰属する当期純利益」（なければ「当期純利益」）の予想値を読み取ってください。"
    "単位（百万円・千円・円）に注意し、円に直してください。範囲で書かれていれば中央値、書かれていなければ null。"
)


def read_revision(pdf_path: Path) -> dict:
    prompt = (REVISION_PROMPT + f"\n\nPDF：{pdf_path}\n次の JSON だけを1行で答えてください："
              '{"np_forecast_yen": 数値または null}')
    try:
        run = subprocess.run(["claude", "-p", prompt, "--output-format", "json", "--allowedTools", "Read",
                              "--max-turns", "4"], capture_output=True, text=True, timeout=600)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return {"status": f"cli_{type(e).__name__}"}
    if run.returncode != 0:
        return {"status": "cli_error"}
    try:
        result = json.loads(run.stdout).get("result", "")
        out = json.loads(re.search(r"\{[^{}]*\"np_forecast_yen\"[^{}]*\}", result).group(0))
        v = out["np_forecast_yen"]
        return {"status": "ok", "np_forecast": None if v is None else float(v)}
    except (json.JSONDecodeError, AttributeError, KeyError, TypeError, ValueError):
        return {"status": "bad_output"}


def process_revisions() -> dict:
    """Claude reads queued 業績予想の修正 PDFs and the new forecast is added to forward/fundamentals.csv."""
    import csv as _csv

    q = FD.REVISION_QUEUE
    if not q.exists():
        return {}
    with q.open(newline="") as f:
        rows = list(_csv.DictReader(f))
    counts = {}
    for r in rows:
        if r["status"] != "pending":
            continue
        resp = requests.get(FD.TDNET + r["pdf"], headers=FD.UA, timeout=60)
        if resp.status_code != 200:
            r["status"] = "pdf_not_found"
        else:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"{r['code']}_{r['disc_no']}.pdf"
                path.write_bytes(resp.content)
                res = read_revision(path)
            if res["status"] == "ok":
                FD.add_revision(r["code"], r["disc_date"], r["disc_time"], r["disc_no"], res["np_forecast"])
                r["status"] = "done" if res["np_forecast"] is not None else "no_value"
            elif res["status"] == "bad_output":
                r["status"] = "bad_output"
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    with q.open("w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=FD.REVISION_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return counts


def liquid_now(code: str) -> bool:
    f = FD.PRICES / f"{code}.csv"
    if not f.exists():
        return False
    px = pd.read_csv(f).tail(E3.LIQ_DAYS)
    return len(px) == E3.LIQ_DAYS and float((px["Close"] * px["Volume"]).mean()) >= E3.LIQ_MIN


def score() -> None:
    """Score 決算短信 disclosed in the last 20 days that are not scored yet (liquid stocks only)."""
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        print(json.dumps({"skipped": "CLAUDE_CODE_OAUTH_TOKEN is not set"}))
        return
    revisions = process_revisions()
    index = FWD / "tdnet_pdfs.csv"
    if not index.exists():
        print(json.dumps({"scored": {}, "revisions": revisions}, ensure_ascii=False))
        return
    done = set()
    if SCORE_FILE.exists():
        done = {json.loads(line)["disc_no"] for line in SCORE_FILE.read_text().splitlines() if line.strip()}
    today = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None).normalize()
    oldest = max(START - pd.Timedelta(days=20), today - pd.Timedelta(days=20))
    counts, calls = {}, 0
    docs = pd.read_csv(index, dtype=str)
    for r in docs.itertuples(index=False):
        if calls >= MAX_CALLS_PER_RUN:
            break
        if "FinancialStatements" not in r.doc_type or r.disc_no in done or pd.Timestamp(r.disc_date) < oldest:
            continue
        if not liquid_now(r.code):
            continue
        resp = requests.get(FD.TDNET + r.pdf, headers=FD.UA, timeout=60)
        if resp.status_code != 200:
            res = {"status": "pdf_not_found"}
        else:
            calls += 1
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / f"{r.code}_{r.disc_no}.pdf"
                path.write_bytes(first_pages(resp.content, PDF_PAGES))
                res = ask_claude(path)
        counts[res["status"]] = counts.get(res["status"], 0) + 1
        if res["status"] != "ok" and res["status"] != "bad_output":
            continue  # retry on the next run (usage limit, network, CLI problems)
        rec = {"disc_no": r.disc_no, "code": r.code, "disc_date": r.disc_date, "doc_type": r.doc_type,
               "scored_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), **res}
        with SCORE_FILE.open("a") as out:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        done.add(r.disc_no)
    print(json.dumps({"scored": counts, "revisions": revisions}, ensure_ascii=False))


def trap_risk(asof: pd.Timestamp) -> dict[str, int]:
    """Latest trap_risk per code among reports disclosed on or before `asof` (scored ones only)."""
    latest = {}
    if SCORE_FILE.exists():
        for line in SCORE_FILE.read_text().splitlines():
            r = json.loads(line)
            if r.get("status") == "ok" and pd.Timestamp(r["disc_date"]) <= asof:
                if r["code"] not in latest or r["disc_date"] >= latest[r["code"]][0]:
                    latest[r["code"]] = (r["disc_date"], r["trap_risk"])
    return {c: v[1] for c, v in latest.items()}


# ----------------------------------------------------------------------------
# paper portfolios
# ----------------------------------------------------------------------------

def restate_flags(today: pd.Timestamp) -> set[str]:
    """EXP-046/047: codes with >= 2 numeric-correction events on earnings
    releases in the trailing 24 months (events effective the trading day
    after disclosure, so only disclosure dates before `today` count)."""
    path = FWD / "restate_events.csv"
    if not path.exists():
        return set()
    ev = pd.read_csv(path, dtype={"code": str})
    if ev.empty:
        return set()
    d = pd.to_datetime(ev["date"])
    lo = today - pd.DateOffset(months=24)
    recent = ev[(d < today) & (d >= lo)]
    counts = recent["code"].value_counts()
    return set(counts[counts >= 2].index)


def transitional_flags() -> set[str]:
    """EXP-077: TOPIX second-stage transitional stocks (JPX list of
    2026-10-07), static seed file; the step-down schedule runs to the
    2027-10 re-evaluation. Missing file -> no exclusions."""
    path = FWD / "transitional_codes.csv"
    if not path.exists():
        return set()
    df = pd.read_csv(path, dtype={"code": str})
    return set(df["code"]) if not df.empty else set()


def fc_episodes_today(fins: dict, today: pd.Timestamp) -> tuple[dict, set]:
    """EXP-080/081: forecast-credibility episodes active on `today`.
    Returns ({code: 1 + clipped habit}, {loss-avoidance codes}).
    Mirrors experiments/exp080_forecast_credibility.py exactly:
    an episode runs from the FY results disclosure that sets NxFNp
    until the first later disclosure that changes the forecast, or
    3 months, whichever first; habit = mean initial-forecast bias of
    the last 3 completed fiscal years (needs >= 2)."""
    def num(x):
        try:
            return float(x)
        except Exception:
            return float("nan")
    import numpy as _np
    factors, la_codes = {}, set()
    for code, recs in fins.items():
        rows = []
        for r in recs:
            if not r.get("DiscDate"):
                continue
            is_fy = r.get("CurPerType") == "FY" and "FinancialStatements" in str(r.get("DocType"))
            fv = num(r.get("NxFNp")) if is_fy else num(r.get("FNP"))
            rows.append({"d": pd.Timestamp(r["DiscDate"]), "t": str(r.get("DiscTime") or ""),
                         "is_fy": is_fy, "fv": fv, "np": num(r.get("NP")),
                         "sales": num(r.get("Sales")), "nx": num(r.get("NxFNp"))})
        rows.sort(key=lambda x: (x["d"], x["t"]))
        biases, pending_init = [], _np.nan
        for i, r in enumerate(rows):
            if not r["is_fy"]:
                continue
            if _np.isfinite(pending_init) and _np.isfinite(r["np"]) and r["np"] != 0:
                biases.append(float(_np.clip((pending_init - r["np"]) / abs(r["np"]), -2, 2)))
            pending_init = r["nx"]
            v0 = r["nx"]
            if not _np.isfinite(v0) or len(biases) < 2 or r["d"] > today:
                continue
            cap = r["d"] + pd.DateOffset(months=3)
            end = cap
            for r2 in rows[i + 1:]:
                if r2["d"] > cap:
                    break
                if _np.isfinite(r2["fv"]) and r2["fv"] != v0:
                    end = r2["d"]
                    break
            if r["d"] <= today < end:
                habit = float(_np.mean(biases[-3:]))
                factors[code] = 1.0 + float(_np.clip(habit, -0.5, 1.0))
                if (_np.isfinite(r["np"]) and r["np"] < 0 and 0 < v0
                        and _np.isfinite(r["sales"]) and r["sales"] > 0
                        and v0 < 0.01 * r["sales"]):
                    la_codes.add(code)
    return factors, la_codes


def activist_flags(today: pd.Timestamp) -> set[str]:
    """EXP-052/053: codes within 120 calendar days after a qualifying
    activist large-holding event (active from the day after the
    submission date)."""
    path = FWD / "large_events.csv"
    if not path.exists():
        return set()
    ev = pd.read_csv(path, dtype={"code": str})
    if ev.empty:
        return set()
    age = (today - pd.to_datetime(ev["date"])).dt.days
    return set(ev.loc[(age >= 1) & (age <= 120), "code"])


def voluntary_bonus(today: pd.Timestamp) -> set[str]:
    """EXP-054/055: codes whose voluntary-disclosure count rose by
    >= 2 (last 365 days vs the 365 days before that)."""
    path = FWD / "voluntary_events.csv"
    if not path.exists():
        return set()
    ev = pd.read_csv(path, dtype={"code": str})
    if ev.empty:
        return set()
    age = (today - pd.to_datetime(ev["date"])).dt.days
    cur = ev.loc[(age >= 0) & (age < 365), "code"].value_counts()
    pri = ev.loc[(age >= 365) & (age < 730), "code"].value_counts()
    delta = cur.subtract(pri, fill_value=0)
    return set(delta[delta >= 2].index)


def rank_multiplier(rank: float) -> float:
    """EXP-007 W: 1-10th 1.5x, 20th 1.0x, 30th and below 0.5x."""
    return float(np.clip(2.0 - rank / 20.0, 0.5, 1.5))


def split_weights(name: str, buys: list[str], pend: dict) -> np.ndarray:
    """How a tranche's cash is split between its new names: equal (R, M, L), by rank (W), by 1/volatility (V)."""
    if name == "W":
        ranks = pend.get("ranks", {})
        return np.array([rank_multiplier(ranks.get(x, 20)) for x in buys])
    if name == "V":
        vol = pend.get("vol", {})
        v = np.array([vol.get(x, np.nan) for x in buys], dtype=float)
        if np.all(np.isfinite(v) & (v > 0)):
            return 1.0 / v
    return np.ones(len(buys))


def load_state() -> dict:
    p = FWD / "state.json"
    if p.exists():
        state = json.loads(p.read_text())
        if "W" not in state:  # EXP-007: W starts with R's first orders (initial picks are ranks 1, 2, 3, ...)
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            if pend and "ranks" not in pend:
                pend["ranks"] = {}
                for k in sorted(pend["orders"], key=int):
                    for x in pend["orders"][k]:
                        pend["ranks"].setdefault(x, len(pend["ranks"]) + 1)
            state["W"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                          "pending": pend}
        if "S" not in state:  # EXP-009: S = R's longs plus shorts of the bottom names (starts with R's first long orders)
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["S"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                          "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "A" not in state:  # EXP-010: A = S mechanics on the momentum-tilted score (starts with R's first long orders)
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["A"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                          "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "AR" not in state:  # EXP-047: AR = A with the EXP-046 restatement screen on the long side
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["AR"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                           "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "AA" not in state:  # EXP-053: AA = A with the EXP-052 activist follow (long bonus + short exclusion)
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["AA"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                           "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "AV" not in state:  # EXP-055: AV = A with the EXP-054 voluntary-disclosure bonus on the long side
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["AV"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                           "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "A75" not in state:  # EXP-074: A75 = A mechanics with short fraction 0.75 (starts with R's first long orders)
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["A75"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                           "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "AT" not in state:  # EXP-077: AT = A with TOPIX transitional stocks excluded on the long side
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["AT"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                           "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "AF" not in state:  # EXP-081: AF = A with the EXP-080 forecast-credibility haircut
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["AF"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                           "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "A75F" not in state:  # EXP-082: A75F = AF score with short fraction 0.75
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["A75F"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                             "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "AV75" not in state:  # EXP-082: AV75 = AV score with short fraction 0.75
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["AV75"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                             "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "AVF" not in state:  # EXP-086: AVF = AF score plus the AV bonus on the long side
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["AVF"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                            "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "AV75F" not in state:  # EXP-086: AV75F = AVF score with short fraction 0.75
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["AV75F"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                              "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "ATOW75" not in state:  # EXP-086: ATOW75 = EXP-083 tug-of-war stack, observation only
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["ATOW75"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                               "shorts": [{} for _ in range(N_TRANCHES)], "realized": 0.0, "pending": pend}
        if "V" not in state:  # EXP-008: V starts with R's first orders
            pend = json.loads(json.dumps(state["R"]["pending"])) if state["R"]["pending"] else None
            state["V"] = {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                          "pending": pend}
        return state
    return {name: {"tranches": [{"cash": BUDGET / N_TRANCHES, "holdings": {}} for _ in range(N_TRANCHES)],
                   "pending": None} for name in PORTFOLIOS} | {"last_step": None}


def due_tranches(day: pd.Timestamp, trading_days: list[pd.Timestamp]) -> list[int]:
    if day < START:
        return []
    i = sum(1 for d in trading_days if START <= d < day)
    if i == 0:
        return list(range(N_TRANCHES))
    return [(i % HOLD_DAYS) // 2] if i % 2 == 0 else []


def step() -> None:
    """Process every trading day after the last processed one, in order (catches up missed runs)."""
    topix_all, panel_all, fins = FD.load()
    state = load_state()
    last = pd.Timestamp(state["last_step"]) if state["last_step"] else topix_all.index[-2]
    todo = [d for d in topix_all.index if d > last]
    if not todo:
        print(json.dumps({"skipped": f"already stepped for {last.date()}"}))
        return
    for day in todo:
        state = load_state()
        step_day(state, topix_all.loc[:day], {k: v.loc[:day] for k, v in panel_all.items()}, fins)


def step_day(state: dict, topix: pd.DataFrame, panel: dict, fins: dict) -> None:
    dates = topix.index
    today = dates[-1]
    o, c = panel["O"], panel["C"].ffill()
    ledger_rows = []
    for name in PORTFOLIOS:
        pf = state[name]
        pend = pf["pending"]
        if pend and pd.Timestamp(pend["exec_date"]) == today:
            bought = set().union(*(pf["tranches"][m]["holdings"] for m in range(N_TRANCHES)
                                   if str(m) not in pend["orders"]))
            for k_str, cands in pend["orders"].items():
                tr = pf["tranches"][int(k_str)]
                for code, sh in tr["holdings"].items():
                    px = o.at[today, code] if o.at[today, code] > 0 else c[code].loc[:today].iloc[-2]
                    tr["cash"] += sh * px * (1 - COST)
                tr["holdings"] = {}
                buys = [x for x in cands if o.at[today, x] > 0 and x not in bought][:PER_TRANCHE]
                bought |= set(buys)
                if buys:
                    ranks = pend.get("ranks", {})
                    w = split_weights(name, buys, pend)
                    w = w / w.sum()
                    tr["holdings"] = {x: tr["cash"] * wx / (o.at[today, x] * (1 + COST)) for x, wx in zip(buys, w)}
                    tr["cash"] = 0.0
            if "shorts" in pf and "short_orders" in pend:
                held_s = set().union(*(pf["shorts"][m] for m in range(N_TRANCHES) if str(m) not in pend["short_orders"]))
                for k_str, cands in pend["short_orders"].items():
                    book = pf["shorts"][int(k_str)]
                    for code, (p0, n) in book.items():
                        px = (o.at[today, code] if o.at[today, code] > 0 else c[code].loc[:today].iloc[-2]) * (1 + COST)
                        pf["realized"] += n * (1 - px / p0)
                    new_s = [x for x in cands if o.at[today, x] > 0 and x not in held_s][:PER_TRANCHE]
                    held_s |= set(new_s)
                    notional = pend["equity"] * SHORT_FRAC_BY.get(name, SHORT_FRAC) / N_TRANCHES
                    pf["shorts"][int(k_str)] = {x: [float(o.at[today, x] * (1 - COST)), notional / len(new_s)]
                                                for x in new_s} if new_s else {}
            pf["pending"] = None
        elif pend and pd.Timestamp(pend["exec_date"]) < today:
            raise SystemExit(f"{name}: pending orders for {pend['exec_date']} were never executed (missed a day?)")
        value = sum(t["cash"] + sum(sh * c.at[today, x] for x, sh in t["holdings"].items()) for t in pf["tranches"])
        if "shorts" in pf:
            pf["realized"] -= sum(n for b in pf["shorts"] for _, n in b.values()) * SHORT_CARRY / 245
            value += pf["realized"] + sum(n * (1 - c.at[today, x] / p0) for b in pf["shorts"] for x, (p0, n) in b.items())
        ledger_rows.append((name, value, sum(len(t["holdings"]) for t in pf["tranches"])))

    nxt = next_trading_day(today)
    trading_days = sorted(set(dates[dates >= START]) | {nxt})
    due = due_tranches(nxt, trading_days)
    if due:
        sig = E3.signals(panel, fins, dates)
        comp = sig["composite"].loc[today].dropna()
        feats, ok = features(panel, fins, dates)
        rank = {
            "R": comp.sort_values(ascending=False, kind="stable"),
            "M": model_scores(feats, ok, today).sort_values(ascending=False, kind="stable"),
        }
        risk = trap_risk(today)
        rank["L"] = rank["R"][[risk.get(x, 3) <= TRAP_MAX for x in rank["R"].index]]
        rank["W"] = rank["R"]
        rank["V"] = rank["R"]
        rank["S"] = rank["R"]
        mom_today = E10.revision_momentum_scores(fins, dates, list(panel["C"].columns)).loc[today]
        tilted = (comp.rank(pct=True) + mom_today.reindex(comp.index)) / 2.0
        rank["A"] = tilted.dropna().sort_values(ascending=False, kind="stable")
        flagged = restate_flags(today)
        rank["AR"] = rank["A"][[x not in flagged for x in rank["A"].index]]
        act = activist_flags(today)
        if act:
            boosted = tilted + 0.15 * tilted.index.isin(act)
            rank["AA"] = boosted.dropna().sort_values(ascending=False, kind="stable")
        else:
            rank["AA"] = rank["A"]
        rank["AA_s"] = rank["A"][[x not in act for x in rank["A"].index]]
        rank["A75"] = rank["A"]  # EXP-074: identical score to A; only the short fraction differs
        tflag = transitional_flags()
        rank["AT"] = rank["A"][[x not in tflag for x in rank["A"].index]]  # EXP-077: long-side exclusion of transitional stocks
        vd = voluntary_bonus(today)
        if vd:
            boosted_v = tilted + 0.10 * tilted.index.isin(vd)
            rank["AV"] = boosted_v.dropna().sort_values(ascending=False, kind="stable")
        else:
            rank["AV"] = rank["A"]
        fc_factors, fc_la = fc_episodes_today(fins, today)
        if fc_factors:
            eq_f, npf_f = E3.fundamentals(fins, dates)
            eq_t = eq_f.loc[today].reindex(comp.index)
            npf_t = npf_f.loc[today].reindex(comp.index)
            fac = pd.Series({x: fc_factors.get(x, 1.0) for x in comp.index})
            npf_adj = npf_t / fac
            mcap_t = panel["MktCap"].loc[today].reindex(comp.index) * 1e6
            liq_t = panel["Va"].fillna(0.0).rolling(E3.LIQ_DAYS, min_periods=E3.LIQ_DAYS).mean().loc[today].reindex(comp.index)
            ok_t = (liq_t >= E3.LIQ_MIN) & (mcap_t > 0) & (eq_t > 0) & npf_adj.notna() & panel["C"].loc[today].reindex(comp.index).notna()
            comp_fc = (eq_t / mcap_t).where(ok_t).rank(pct=True) + (npf_adj / eq_t).where(ok_t).rank(pct=True)
            tilted_fc = (comp_fc.rank(pct=True) + mom_today.reindex(comp_fc.index)) / 2.0
            rank["AF_s"] = tilted_fc.dropna().sort_values(ascending=False, kind="stable")
            rank["AF"] = rank["AF_s"][[x not in fc_la for x in rank["AF_s"].index]]
            boosted_fc = tilted_fc + 0.10 * tilted_fc.index.isin(vd) if vd else tilted_fc
            rank["AVF_s"] = rank["AF_s"]
            avf_long = boosted_fc.dropna().sort_values(ascending=False, kind="stable")
            rank["AVF"] = avf_long[[x not in fc_la for x in avf_long.index]]
            rank["AV75F"] = rank["AVF"]
            rank["AV75F_s"] = rank["AF_s"]
        else:
            rank["AF"] = rank["A"]
            rank["AF_s"] = rank["A"]
            rank["AVF"] = rank["AV"]
            rank["AVF_s"] = rank["A"]
            rank["AV75F"] = rank["AV"]
            rank["AV75F_s"] = rank["A"]
        rank["A75F"] = rank["AF"]  # EXP-082: identical scores to AF; only the short fraction differs
        rank["A75F_s"] = rank["AF_s"]
        rank["AV75"] = rank["AV"]  # EXP-082: identical score to AV; only the short fraction differs
        o_df, c_df = panel["O"], panel["C"]
        overnight = o_df / c_df.shift(1) - 1.0
        intraday = c_df / o_df - 1.0
        tug = ((overnight > 0) & (intraday < 0)).where(overnight.notna() & intraday.notna()).rolling(20, min_periods=15).mean()
        tow_r = tug.loc[today].reindex(comp.index).rank(pct=True).fillna(0.5)
        tow_score = ((comp.rank(pct=True) + mom_today.reindex(comp.index) + tow_r) / 3.0)
        rank["ATOW75"] = tow_score.dropna().sort_values(ascending=False, kind="stable")  # EXP-086: observation only
        vol60 = panel["C"].pct_change(fill_method=None).rolling(60, min_periods=40).std().loc[today]
        eq, npf = E3.fundamentals(fins, dates)
        mcap = panel["MktCap"].loc[today] * 1e6
        order = {x: i + 1 for i, x in enumerate(rank["R"].index)}
        info = {x: {"rank": order[x], "n": len(order),
                    "pbr": round(float(mcap[x] / eq.at[today, x]), 2),
                    "roe": round(float(npf.at[today, x] / eq.at[today, x]), 4)} for x in rank["R"].index[:80]}
        for name in PORTFOLIOS:
            pf = state[name]
            # names kept by tranches that do not trade tomorrow, plus names given to earlier due tranches
            others = set().union(*(pf["tranches"][m]["holdings"] for m in range(N_TRANCHES) if m not in due))
            orders, taken = {}, set()
            for k in due:
                pool = [x for x in rank[name].index if x not in others and x not in taken]
                orders[str(k)] = pool[:PER_TRANCHE + SPARE]
                taken |= set(pool[:PER_TRANCHE])
            tranche_value = {str(k): pf["tranches"][k]["cash"] + sum(sh * c.at[today, x] for x, sh in
                                                                 pf["tranches"][k]["holdings"].items()) for k in due}
            pf["pending"] = {"decided_on": str(today.date()), "exec_date": str(nxt.date()), "orders": orders,
                             "tranche_value": tranche_value, "ranks": {x: v["rank"] for x, v in info.items()}}
            pf["pending"]["vol"] = {x: round(float(vol60[x]), 6) for c in orders.values() for x in c
                                    if np.isfinite(vol60.get(x, np.nan))}
            if name in ("R", "W", "V"):
                pf["pending"]["info"] = {x: info[x] for c in orders.values() for x in c if x in info}
            if "shorts" in pf:
                others_s = set().union(*(pf["shorts"][m] for m in range(N_TRANCHES) if m not in due))
                sorders, taken_s = {}, set()
                for k in due:
                    srank = rank["A"] if name in ("AR", "AV", "A75", "AT", "AV75", "ATOW75") else (rank["AA_s"] if name == "AA" else (rank["AF_s"] if name in ("AF", "AVF") else (rank["A75F_s"] if name in ("A75F", "AV75F") else rank[name])))  # EXP-047/053/055/077: AR/AV/A75/AT/AV75/ATOW75 shorts follow A; AA shorts follow A minus activist-flagged names; AF/AVF/A75F/AV75F shorts follow A_fc (EXP-081/082/086)
                    pool = [x for x in srank.index[::-1] if x not in others_s and x not in taken_s]
                    sorders[str(k)] = pool[:PER_TRANCHE + SPARE]
                    taken_s |= set(pool[:PER_TRANCHE])
                pf["pending"]["short_orders"] = sorders
                pf["pending"]["equity"] = next(v for n, v, _ in ledger_rows if n == name)
        write_order_sheet(state, today, nxt, due)

    state["last_step"] = str(today.date())
    (FWD / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n")
    ledger = FWD / "ledger.csv"
    new = not ledger.exists()
    with ledger.open("a") as f:
        if new:
            f.write("date,portfolio,value,positions,topix_close\n")
        for name, value, n in ledger_rows:
            f.write(f"{today.date()},{name},{value:.0f},{n},{topix['C'].iloc[-1]:.2f}\n")
    print(json.dumps({"date": str(today.date()), "values": {n: round(v) for n, v, _ in ledger_rows},
                      "next_trading_day": str(nxt.date()), "tranches_due": due}, ensure_ascii=False))


def write_order_sheet(state: dict, today, nxt, due) -> None:
    """Human-readable order sheet for the real-money portfolio R (and the paper ones for reference)."""
    names_file = FWD / "names.json"
    names = json.loads(names_file.read_text()) if names_file.exists() else {}
    nm = lambda x: f"{x} {names.get(x, '')}".strip()  # noqa: E731
    lines = [f"# {nxt.date()} の寄付の注文（{today.date()} の終値で決定）", ""]
    for name in PORTFOLIOS:
        pf = state[name]
        title = {"R": "R（ペーパー：ルール・等金額）", "M": "M（ペーパー：LightGBM）", "L": "L（ペーパー：Claude が決算短信を確認）", "W": "W（ペーパー：点数で金額を配分）", "V": "V（実運用：値動きで金額を配分）", "S": "S（ペーパー：上位を買い、下位を空売り）", "A": "A（ペーパー：決算モメンタム傾斜つきロング・ショート）", "AR": "AR（ペーパー：A＋訂正反復スクリーン）", "AA": "AA（ペーパー：A＋アクティビスト追随）", "AV": "AV（ペーパー：A＋任意開示の厚み）", "A75": "A75（ペーパー：A＋ショート比率0.75）", "AT": "AT（ペーパー：A＋TOPIX移行措置銘柄の回避）", "AF": "AF（ペーパー：A＋予想の癖による割引）", "A75F": "A75F（ペーパー：AF×ショート比率0.75）", "AV75": "AV75（ペーパー：AV×ショート比率0.75）", "AVF": "AVF（ペーパー：AV＋予想の癖の割引）", "AV75F": "AV75F（ペーパー：AVF×ショート比率0.75）", "ATOW75": "ATOW75（観測専用：綱引き×ショート比率0.75）"}[name]
        lines += [f"## {title}", "", "| 組 | 売る（寄成） | 買う（寄成、上から2つ。寄付がつかなければ次の候補） |", "|---|---|---|"]
        for k, cands in pf["pending"]["orders"].items():
            sell = "、".join(nm(x) for x in sorted(pf["tranches"][int(k)]["holdings"])) or "なし"
            lines.append(f"| {int(k) + 1} | {sell} | {'、'.join(nm(x) for x in cands)} |")
        lines.append("")
    lines.append("同じ銘柄を売って買い直す場合は、実際には何もしなくてよい。")
    out = FWD / "orders" / f"{nxt.date()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")


L_EVAL_FROM = pd.Timestamp("2026-09-28")


def eval_l() -> None:
    """Amendment 1: judge Claude's ratings directly, report by report (much faster than portfolio profit).

    For each scored report disclosed on or after L_EVAL_FROM: buy at the open of the first trading day after
    the disclosure, sell at the open 20 trading days later; subtract the equal-weight return of all liquid
    universe stocks over the same days. Compare ratings 1-2 (low trap risk) with 4-5 (high trap risk).
    """
    topix, panel, fins = FD.load()
    dates = topix.index
    o = panel["O"]
    liquid = panel["Va"].fillna(0.0).rolling(E3.LIQ_DAYS, min_periods=E3.LIQ_DAYS).mean() >= E3.LIQ_MIN
    rows = []
    if SCORE_FILE.exists():
        for line in SCORE_FILE.read_text().splitlines():
            r = json.loads(line)
            d = pd.Timestamp(r["disc_date"])
            if r.get("status") != "ok" or d < L_EVAL_FROM:
                continue
            e = int(dates.searchsorted(d, side="right"))
            x = e + HOLD_DAYS
            if x >= len(dates) or not o.iat[e, o.columns.get_loc(r["code"])] > 0:
                continue
            gross = o.iloc[x] / o.iloc[e] - 1
            bench = gross[liquid.iloc[e - 1]].mean()
            ret = gross[r["code"]]
            if np.isfinite(ret):
                rows.append({"code": r["code"], "disc_date": r["disc_date"], "trap_risk": r["trap_risk"],
                             "excess": float(ret - bench)})
    df = pd.DataFrame(rows, columns=["code", "disc_date", "trap_risk", "excess"])
    low, high = df[df.trap_risk <= 2]["excess"], df[df.trap_risk >= 4]["excess"]
    out = {"reports_evaluated": int(len(df)), "by_rating": {int(k): {"n": int(len(g)), "mean_excess_pct": round(float(g.mean()) * 100, 3)}
                                                            for k, g in df.groupby("trap_risk")["excess"]}}
    if len(low) >= 2 and len(high) >= 2:
        diff = low.mean() - high.mean()
        se = np.sqrt(low.var(ddof=1) / len(low) + high.var(ddof=1) / len(high))
        out["low_minus_high_pct"] = round(float(diff) * 100, 3)
        out["welch_t"] = round(float(diff / se), 2)
        out["enough_data"] = bool(len(low) >= 30 and len(high) >= 30)
    (FWD / "l_eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(out, ensure_ascii=False))


WEEKDAY = "月火水木金土日"


def jp_date(d: str) -> str:
    t = pd.Timestamp(d)
    return f"{t.month}/{t.day}（{WEEKDAY[t.weekday()]}）"


def slack_message(state: dict) -> dict:
    """Block Kit message for the real-money portfolio R (Slack has no tables; use sections and lists)."""
    names_file = FWD / "names.json"
    names = json.loads(names_file.read_text()) if names_file.exists() else {}
    nm = lambda x: f"{x} {names.get(x, '')}".strip()  # noqa: E731
    pf, pend = state[REAL], state[REAL]["pending"]
    sells, buys, spares, keeps = [], [], [], []
    for k, cands in pend["orders"].items():
        held = sorted(pf["tranches"][int(k)]["holdings"])
        new = cands[:PER_TRANCHE]
        value = pend.get("tranche_value", {}).get(k, BUDGET / N_TRANCHES)
        w = split_weights(REAL, new, pend)
        w = w / w.sum() if len(new) else w
        keeps += [x for x in held if x in new]
        sells += [x for x in held if x not in new]
        buys += [(x, value * wx) for x, wx in zip(new, w) if x not in held]
        spares += cands[PER_TRANCHE:]
    taken = {x for x, _ in buys} | set(keeps) | {x for t in pf["tranches"] for x in t["holdings"]}
    spares = [x for x in dict.fromkeys(spares) if x not in taken]
    title = f"{jp_date(pend['exec_date'])} 朝の注文"
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": title}},
              {"type": "context", "elements": [{"type": "mrkdwn", "text":
               f"{jp_date(pend['decided_on'])}の終値で決定　・　すべて *寄成*（寄付の成行）　・　S株でOK"}]}]
    if not sells and not buys:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*今日は売買なし* :white_check_mark:\n入れ替えの日ですが、選ばれた銘柄が今と同じでした。"}})
    else:
        sell_txt = "\n".join(f"• {nm(x)}" for x in sells) or "なし"
        info = pend.get("info", {})

        def why(x: str) -> str:
            i = info.get(x)
            if not i:
                return ""
            price = f"財産の{i['pbr'] * 10:.1f}割の値段" if i["pbr"] < 1 else f"財産の{i['pbr']:.1f}倍の値段"
            line = (f"\n　　候補{i['n']}社中 *{i['rank']}位*｜PBR {i['pbr']:.2f}倍（{price}）"
                    f"｜予想ROE {i['roe']:.1%}（財産100円で年{i['roe'] * 100:.0f}円稼ぐ見込み）")
            v = pend.get("vol", {}).get(x)
            if v:
                feel = "荒いので少なめ" if v > 0.028 else ("穏やかなので多め" if v < 0.018 else "ふつう")
                line += f"\n　　金額の理由：1日の値動きが平均 ±{v * 100:.1f}%（{feel}）"
            return line
        buy_lines = [f"• *{nm(x)}*　約{int(round(v, -3)):,}円{why(x)}" for x, v in buys]
        if sells:
            blocks.append({"type": "section", "text": {"type": "mrkdwn",
                                                        "text": f":outbox_tray: *売る*（持っている全株）\n{sell_txt}"}})
        for n0 in range(0, len(buy_lines), 6):  # Slack allows 3,000 characters per section
            head = ":inbox_tray: *買う*（金額は40万円で運用する場合の目安）\n" if n0 == 0 else ""
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": head + "\n".join(buy_lines[n0:n0 + 6])}})
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
                       "選び方：割安さ（PBR が低いほど高い）の順位＋稼ぐ力（予想ROE が高いほど高い）の順位が高い会社。"
                       "金額：値動きが荒い会社は少なめ、穏やかな会社は多め（2社で組の資金を分ける）"}]})
        if spares:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
                           "寄付で買えなかった銘柄があれば、代わりに上から順に：" + "、".join(nm(x) for x in spares[:4])}]})
    if keeps:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
                       "そのまま持ち続ける：" + "、".join(nm(x) for x in keeps)}]})
    ledger = FWD / "ledger.csv"
    if ledger.exists():
        led = pd.read_csv(ledger)
        r = led[(led.portfolio == REAL) & (pd.to_datetime(led.date) >= START)]
        if len(r):
            first = led[(led.portfolio == REAL)].iloc[0] if (led.portfolio == REAL).any() else r.iloc[0]
            gain = r["value"].iloc[-1] / BUDGET - 1
            tpx = r["topix_close"].iloc[-1] / first["topix_close"] - 1
            blocks += [{"type": "divider"}, {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*実運用（V）の成績*\n{gain:+.1%}"},
                {"type": "mrkdwn", "text": f"*TOPIX（同じ期間）*\n{tpx:+.1%}"}]}]
    return {"text": f"{title}：売る {len(sells)}銘柄・買う {len(buys)}銘柄",
            "blocks": blocks}


def notify() -> None:
    """Send the real-money (R) orders to Slack, once per order sheet (FORCE_NOTIFY=1 to resend)."""
    url = os.environ.get("SLACK_WEBHOOK_URL")
    state = load_state()
    pend = state[REAL]["pending"]
    force = os.environ.get("FORCE_NOTIFY") == "1"
    if not url or not pend or (state.get("notified") == pend["exec_date"] and not force):
        print(json.dumps({"notified": False}))
        return
    r = requests.post(url, json=slack_message(state), timeout=10)
    if r.status_code == 200:
        state["notified"] = pend["exec_date"]
        (FWD / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"notified": r.status_code == 200, "detail": r.text[:200]}, ensure_ascii=False))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"update-data": update_data, "train": train, "score": score, "step": step, "notify": notify, "eval-l": eval_l}.get(
        cmd, lambda: sys.exit(__doc__))()
