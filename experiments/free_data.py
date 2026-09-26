"""Free data sources for the EXP-004 forward test (replaces the paid J-Quants API).

  prices        : yfinance (Yahoo Finance, <code>.T), split-adjusted daily OHLCV and splits
  fundamentals  : TDnet (東証 適時開示) 決算短信 / 業績予想の修正 XBRL summaries, appended to
                  forward/fundamentals.csv (seeded once from J-Quants before the subscription ended)
  calendar      : weekdays minus the TSE holidays in forward/tse_holidays.txt

The loader returns the same (topix, panel, fins) shapes as exp003_rotation.load, so every signal and
simulation function works unchanged. TOPIX is proxied by the TOPIX ETF 1306.
"""
from __future__ import annotations

import csv
import io
import re
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
FWD = ROOT / "forward"
PRICES = ROOT / "data" / "free" / "prices"
FUND = FWD / "fundamentals.csv"
FUND_FIELDS = ["code", "disc_date", "disc_time", "disc_no", "doc_type", "per_type", "fy_end",
               "equity", "np_forecast", "shares_out"]
TDNET = "https://www.release.tdnet.info/inbs/"
TOPIX_PROXY = "1306"
UA = {"User-Agent": "Mozilla/5.0 (stock-analyzer research)"}


# ----------------------------------------------------------------------------
# prices (yfinance)
# ----------------------------------------------------------------------------

def update_prices(codes: list[str], start: str = "2016-01-01") -> dict:
    import yfinance as yf

    PRICES.mkdir(parents=True, exist_ok=True)
    failed = []
    for code in codes + [TOPIX_PROXY]:
        f = PRICES / f"{code}.csv"
        for attempt in range(4):
            try:
                df = yf.Ticker(f"{code}.T").history(start=start, auto_adjust=False, actions=True)
                break
            except Exception:  # yfinance raises many types; retry then give up for this code
                df = None
                time.sleep(5 * (attempt + 1))
        if df is None or df.empty:
            failed.append(code)
            continue
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        out = df[["Open", "High", "Low", "Close", "Volume", "Stock Splits"]].rename(columns={"Stock Splits": "Split"})
        out.index.name = "Date"
        out.to_csv(f)
        time.sleep(0.5)
    return {"codes": len(codes), "failed": failed}


# ----------------------------------------------------------------------------
# fundamentals (TDnet XBRL summaries)
# ----------------------------------------------------------------------------

def read_fund() -> list[dict]:
    with FUND.open(newline="") as f:
        return list(csv.DictReader(f))


def ix_values(html: str) -> list[tuple[str, str, float]]:
    """(name, contextRef, value) for every ix:nonFraction in an inline-XBRL summary."""
    out = []
    for m in re.finditer(r"<ix:nonFraction([^>]*)>(.*?)</ix:nonFraction>", html, re.S):
        attrs, text = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        name = re.search(r'name="([^"]+)"', attrs)
        ctx = re.search(r'contextRef="([^"]+)"', attrs)
        if not name or not ctx or not text or text in ("-", "―"):
            continue
        try:
            v = float(text.replace(",", ""))
        except ValueError:
            continue
        scale = re.search(r'scale="(-?\d+)"', attrs)
        v *= 10 ** int(scale.group(1)) if scale else 1
        if re.search(r'sign="-"', attrs):
            v = -v
        out.append((name.group(1).split(":")[-1], ctx.group(1), v))
    return out


def pick(vals, names: tuple[str, ...], ctx_all: tuple[str, ...], ctx_none: tuple[str, ...] = ()) -> float | None:
    """First value (consolidated preferred) whose name is in `names` and whose context has every string in
    ctx_all and none in ctx_none. Ranged forecasts (Upper/Lower members) are averaged."""
    for consolidated in (True, False):
        hits = [v for n, c, v in vals if n in names and all(s in c for s in ctx_all)
                and not any(s in c for s in ctx_none)
                and (("NonConsolidated" not in c) == consolidated)]
        exact = [v for n, c, v in vals if n in names and all(s in c for s in ctx_all)
                 and not any(s in c for s in ctx_none + ("Upper", "Lower"))
                 and (("NonConsolidated" not in c) == consolidated)]
        if exact:
            return exact[0]
        if hits:
            return float(np.mean(hits))
    return None


NP_FORECAST = ("ForecastProfitAttributableToOwnersOfParent", "ForecastNetIncome", "ForecastProfit")
EQUITY = ("NetAssets",)
SHARES = ("NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock",)


def parse_summary(html: str, is_fy_statement: bool, is_statement: bool) -> dict:
    vals = ix_values(html)
    year = "NextYearDuration" if is_fy_statement else "CurrentYearDuration"
    out = {"np_forecast": pick(vals, NP_FORECAST, (year, "ForecastMember"))}
    if is_statement:
        out["equity"] = pick(vals, EQUITY, ("Instant", "ResultMember"), ("Prior",))
        out["shares_out"] = pick(vals, SHARES, ("Instant",), ("Prior",))  # issued, incl. treasury (as J-Quants)
    return out


def list_rows(day: pd.Timestamp) -> list[dict]:
    """Every disclosure on TDnet for one day: time, 4-char code, title, pdf, xbrl zip."""
    rows = []
    for page in range(1, 100):
        r = requests.get(f"{TDNET}I_list_{page:03d}_{day:%Y%m%d}.html", headers=UA, timeout=30)
        if r.status_code != 200:
            break
        r.encoding = "utf-8"
        found = 0
        for tr in re.findall(r"<tr>(.*?)</tr>", r.text, re.S):
            code = re.search(r'kjCode"[^>]*>\s*([0-9A-Z]{4,5})', tr)
            if not code:
                continue
            found += 1
            title = re.search(r'kjTitle"[^>]*>.*?<a href="([^"]+\.pdf)"[^>]*>(.*?)</a>', tr, re.S)
            xbrl = re.search(r'kjXbrl"[^>]*>.*?<a href="([^"]+\.zip)"', tr, re.S)
            tm = re.search(r'kjTime"[^>]*>\s*([0-9:]+)', tr)
            rows.append({"code": code.group(1)[:4], "time": (tm.group(1) + ":00") if tm else "",
                         "title": re.sub(r"<[^>]+>|\s+", "", title.group(2)) if title else "",
                         "pdf": title.group(1) if title else "", "xbrl": xbrl.group(1) if xbrl else ""})
        if not found:
            break
        time.sleep(0.5)
    return rows


def doc_kind(title: str) -> tuple[str, str] | None:
    """(doc_type, per_type) in the J-Quants naming, or None for disclosures we do not use."""
    if "訂正" in title:
        return None
    if "決算短信" in title:
        per = "FY"
        for key, p in (("第１四半期", "1Q"), ("第1四半期", "1Q"), ("第２四半期", "2Q"), ("第2四半期", "2Q"),
                       ("中間", "2Q"), ("第３四半期", "3Q"), ("第3四半期", "3Q")):
            if key in title:
                per = p
        return f"{per}FinancialStatements_TDnet", per
    if "業績予想" in title and "修正" in title:
        return "EarnForecastRevision", "FY"
    return None


REVISION_QUEUE = FWD / "revision_queue.csv"
REVISION_FIELDS = ["code", "disc_date", "disc_time", "disc_no", "pdf", "status"]


def queue_revision(d: dict, day: pd.Timestamp) -> int:
    """業績予想の修正 has no XBRL on TDnet: queue its PDF so Claude can read the new net-profit forecast."""
    disc_no = re.sub(r"\D", "", d["pdf"])[-14:]
    rows = []
    if REVISION_QUEUE.exists():
        with REVISION_QUEUE.open(newline="") as f:
            rows = list(csv.DictReader(f))
    if any(r["disc_no"] == disc_no for r in rows):
        return 0
    rows.append({"code": d["code"], "disc_date": str(day.date()), "disc_time": d["time"], "disc_no": disc_no,
                 "pdf": d["pdf"], "status": "pending"})
    with REVISION_QUEUE.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REVISION_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return 1


def add_revision(code: str, disc_date: str, disc_time: str, disc_no: str, np_forecast: float | None) -> None:
    rows = read_fund()
    rows.append({"code": code, "disc_date": disc_date, "disc_time": disc_time, "disc_no": disc_no,
                 "doc_type": "EarnForecastRevision", "per_type": "FY", "fy_end": "", "equity": "",
                 "np_forecast": "" if np_forecast is None else str(int(np_forecast)), "shares_out": ""})
    rows.sort(key=lambda x: (x["code"], x["disc_date"], x["disc_time"], x["disc_no"]))
    with FUND.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FUND_FIELDS)
        w.writeheader()
        w.writerows(rows)


def update_fundamentals(codes: list[str], days: int = 7) -> dict:
    """Append 決算短信 / 業績予想の修正 of universe codes from the last `days` calendar days."""
    rows = read_fund()
    seen = {(r["code"], r["disc_no"]) for r in rows}
    universe = set(codes)
    added, failed, stats = 0, [], {"tdnet_rows": 0, "universe_docs": 0, "already_known": 0, "revisions_queued": 0}
    today = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None).normalize()
    for back in range(days):
        day = today - pd.Timedelta(days=back)
        for d in list_rows(day):
            stats["tdnet_rows"] += 1
            kind = doc_kind(d["title"])
            if d["code"] not in universe or not kind:
                continue
            stats["universe_docs"] += 1
            if not d["xbrl"]:
                if (d["code"], re.sub(r"\D", "", d["pdf"])[-14:]) in seen:
                    stats["already_known"] += 1
                elif kind[0] == "EarnForecastRevision":
                    stats["revisions_queued"] += queue_revision(d, day)
                continue
            disc_no = re.sub(r"\D", "", d["xbrl"])[-14:]
            if (d["code"], disc_no) in seen:
                stats["already_known"] += 1
                continue
            try:
                z = zipfile.ZipFile(io.BytesIO(requests.get(TDNET + d["xbrl"], headers=UA, timeout=60).content))
                names = [n for n in z.namelist() if "Summary" in n and n.endswith(("ixbrl.htm", ".htm"))]
                html = z.read(names[0]).decode("utf-8", "ignore")
            except Exception as e:  # keep going; the record is retried on the next run
                failed.append(f"{d['code']} {d['title'][:20]} {type(e).__name__}")
                continue
            doc_type, per = kind
            vals = parse_summary(html, is_fy_statement=(per == "FY" and "FinancialStatements" in doc_type),
                                 is_statement="FinancialStatements" in doc_type)
            rec = {"code": d["code"], "disc_date": str(day.date()), "disc_time": d["time"], "disc_no": disc_no,
                   "doc_type": doc_type, "per_type": per, "fy_end": "",
                   "equity": "" if vals.get("equity") is None else str(int(vals["equity"])),
                   "np_forecast": "" if vals.get("np_forecast") is None else str(int(vals["np_forecast"])),
                   "shares_out": "" if vals.get("shares_out") is None else str(int(vals["shares_out"])),
                   "pdf": d["pdf"]}
            rows.append({k: rec[k] for k in FUND_FIELDS})
            seen.add((d["code"], disc_no))
            added += 1
            pdf_index = FWD / "tdnet_pdfs.csv"
            new = not pdf_index.exists()
            with pdf_index.open("a", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["code", "disc_date", "disc_no", "doc_type", "pdf"])
                w.writerow([d["code"], str(day.date()), disc_no, doc_type, d["pdf"]])
    rows.sort(key=lambda x: (x["code"], x["disc_date"], x["disc_time"], x["disc_no"]))
    with FUND.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FUND_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return {"added": added, "failed": failed, **stats}


# ----------------------------------------------------------------------------
# loader with the same shapes as exp003_rotation.load
# ----------------------------------------------------------------------------

def load():
    fund = pd.read_csv(FUND, dtype=str).fillna("")
    fins = {}
    for r in fund.itertuples(index=False):
        is_fy = r.per_type == "FY" and "FinancialStatements" in r.doc_type
        fins.setdefault(r.code, []).append({
            "DiscDate": r.disc_date, "DiscTime": r.disc_time, "DocType": r.doc_type, "CurPerType": r.per_type,
            "CurFYEn": r.fy_end, "Eq": r.equity, "FNP": "" if is_fy else r.np_forecast,
            "NxFNp": r.np_forecast if is_fy else "", "NxtFYEn": "",
        })
    px = {}
    for f in sorted(PRICES.glob("*.csv")):
        px[f.stem] = pd.read_csv(f, parse_dates=["Date"], index_col="Date")
    tp = px.pop(TOPIX_PROXY)
    topix = tp[["Open", "Close"]].rename(columns={"Open": "O", "Close": "C"}).astype(float)
    topix = topix[topix["C"] > 0]
    dates = topix.index
    codes = sorted(set(px) & set(fins))
    O = pd.DataFrame({c: px[c]["Open"] for c in codes}).reindex(dates).replace(0, np.nan)
    C = pd.DataFrame({c: px[c]["Close"] for c in codes}).reindex(dates).replace(0, np.nan)
    vol = pd.DataFrame({c: px[c]["Volume"] for c in codes}).reindex(dates)
    va = (C * vol).where(vol > 0)
    mcap = pd.DataFrame(index=dates, columns=codes, dtype=float)
    for c in codes:
        sh = fund[(fund.code == c) & (fund.shares_out != "")]
        if sh.empty:
            continue
        splits = px[c]["Split"].replace(0, 1.0).fillna(1.0)
        s = pd.Series(np.nan, index=dates)
        for r in sh.itertuples(index=False):
            pos = dates.searchsorted(pd.Timestamp(r.disc_date))
            if pos < len(dates):
                after = splits[splits.index > pd.Timestamp(r.disc_date)].prod()
                s.iloc[pos] = float(r.shares_out) * after
        mcap[c] = s.ffill() * C[c] / 1e6  # million yen, as J-Quants MktCap
    panel = {"O": O, "C": C, "Va": va, "MktCap": mcap}
    traded = O.notna().any(axis=1)
    return topix[traded], {k: v[traded] for k, v in panel.items()}, fins


if __name__ == "__main__":
    codes = (FWD / "universe.txt").read_text().split()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "prices":
        print(update_prices(codes))
    elif cmd == "fundamentals":
        print(update_fundamentals(codes, days=int(sys.argv[2]) if len(sys.argv) > 2 else 7))
    else:
        sys.exit("usage: free_data.py prices | fundamentals [days]")
