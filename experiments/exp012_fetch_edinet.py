#!/usr/bin/env python3
"""EXP-012: fetch gross profit / total assets from EDINET annual securities
reports (docTypeCode 120, corrections 130) via the EDINET API v2, and build
the point-in-time GPA panel described in EXP-012_AMENDMENT_1.

Credential: EDINET_API_KEY environment variable when set (repo use). On
Muse's VM the key lives in the registered connection custom.edinet and is
attached through the surrogate mechanism instead; either way the key is
never written to disk, arguments, or logs.

Data kept under <out>/ (default data/edinet_exp012):
  lists/<date>.json.gz   raw documents.json (type=2) per day
  gpa.csv                code, period_end, submit_datetime, doc_id,
                         doc_type, gross_profit, total_assets, gpa, consol
  state.json             resume state (dates listed, docIDs processed)
  manifest.json          sha256 of gpa.csv + counts (written at the end)
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

HOST = "api.edinet-fsa.go.jp"
BASE = f"https://{HOST}/api/v2"


def build_url(url: str) -> str:
    key = os.environ.get("EDINET_API_KEY")
    if key:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}Subscription-Key={key}"
    sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
    from dynamic_credentials import url_with_surrogate_query_param
    return url_with_surrogate_query_param(
        url, "custom.edinet", allowed_hosts=[HOST])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused")


def fetch(url: str, spacing: float) -> bytes:
    delay = 5.0
    for attempt in range(4):
        try:
            req = urllib.request.Request(build_url(url))
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(req, timeout=90) as resp:
                body = resp.read()
            time.sleep(spacing)
            return body
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 3:
                print(f"  HTTP {e.code}, backoff {delay:.0f}s", flush=True)
                time.sleep(delay)
                delay *= 3
                continue
            raise
        except Exception:
            if attempt < 3:
                time.sleep(delay)
                delay *= 3
                continue
            raise
    raise RuntimeError("unreachable")


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def extract_gp_ta(zip_bytes: bytes):
    """Return (gross_profit, total_assets, consol) from a type=5 CSV zip."""
    found = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in z.namelist():
            if not name.lower().endswith(".csv"):
                continue
            text = z.read(name).decode("utf-16", errors="replace")
            rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
            if not rows or "要素ID" not in rows[0]:
                continue
            hdr = {h: i for i, h in enumerate(rows[0])}
            need = ("要素ID", "コンテキストID", "値")
            if any(k not in hdr for k in need):
                continue
            for r in rows[1:]:
                if len(r) <= max(hdr[k] for k in need):
                    continue
                elem = r[hdr["要素ID"]]
                local = elem.split(":")[-1]
                kind = None
                if "Summary" not in elem and local == "GrossProfit":
                    kind = "gp"
                elif "Summary" not in elem and local in ("Assets",
                                                         "TotalAssets"):
                    kind = "ta"
                if kind is None or kind in found:
                    continue
                ctx = r[hdr["コンテキストID"]]
                base = {"gp": "CurrentYearDuration",
                        "ta": "CurrentYearInstant"}[kind]
                if ctx == base:
                    consol = True
                elif ctx == base + "_NonConsolidatedMember":
                    consol = False
                else:
                    continue
                raw = r[hdr["値"]].replace(",", "").strip()
                try:
                    val = float(raw)
                except ValueError:
                    continue
                found[kind] = (val, consol)
    if "gp" in found and "ta" in found:
        return found["gp"][0], found["ta"][0], found["gp"][1] and found["ta"][1]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="../cache/jquants_exp002")
    ap.add_argument("--out", default="data/edinet_exp012")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-09-25")
    ap.add_argument("--spacing", type=float, default=1.2)
    ap.add_argument("--max-filings", type=int, default=0,
                    help="smoke test: stop after N filings")
    ap.add_argument("--budget-seconds", type=float, default=0,
                    help="stop cleanly (state saved) after N seconds")
    args = ap.parse_args()
    t0 = time.time()

    def over_budget() -> bool:
        return bool(args.budget_seconds) and \
            time.time() - t0 > args.budget_seconds

    out = Path(args.out)
    (out / "lists").mkdir(parents=True, exist_ok=True)
    universe = {p.stem for p in (Path(args.cache) / "fins").glob("*.json")}
    print(f"universe: {len(universe)} codes", flush=True)

    state_path = out / "state.json"
    state = {"listed": [], "done_docs": []}
    if state_path.exists():
        state = json.loads(state_path.read_text())
    listed = set(state["listed"])
    done_docs = set(state["done_docs"])

    gpa_path = out / "gpa.csv"
    gpa_exists = gpa_path.exists()
    gpa_file = open(gpa_path, "a", newline="", encoding="utf-8")
    writer = csv.writer(gpa_file)
    if not gpa_exists:
        writer.writerow(["code", "period_end", "submit_datetime", "doc_id",
                         "doc_type", "gross_profit", "total_assets", "gpa",
                         "consol"])

    def save_state():
        state_path.write_text(json.dumps(
            {"listed": sorted(listed), "done_docs": sorted(done_docs)}))

    # Phase 1: daily lists
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    todo = [d for d in daterange(start, end) if d.isoformat() not in listed]
    print(f"phase 1: {len(todo)} daily lists to fetch", flush=True)
    for i, d in enumerate(todo):
        if over_budget():
            save_state()
            gpa_file.close()
            print("BUDGET_STOP phase1", flush=True)
            return 0
        ds = d.isoformat()
        body = fetch(f"{BASE}/documents.json?date={ds}&type=2", args.spacing)
        with gzip.open(out / "lists" / f"{ds}.json.gz", "wb") as f:
            f.write(body)
        listed.add(ds)
        if (i + 1) % 100 == 0 or i + 1 == len(todo):
            save_state()
            print(f"  lists {i + 1}/{len(todo)} ({ds})", flush=True)
    save_state()

    # Phase 2: select filings; a 130 correction supersedes the 120 original
    chosen = {}
    for ds in sorted(listed):
        with gzip.open(out / "lists" / f"{ds}.json.gz", "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
        for r in data.get("results") or []:
            if r.get("docTypeCode") not in ("120", "130"):
                continue
            if str(r.get("csvFlag")) != "1":
                continue
            sec = (r.get("secCode") or "")[:4]
            if sec not in universe:
                continue
            key = (sec, r.get("periodEnd") or "")
            prev = chosen.get(key)
            rank = (1 if r["docTypeCode"] == "130" else 0,
                    r.get("submitDateTime") or "")
            if prev is None or rank > prev[0]:
                chosen[key] = (rank, r)
    filings = [v[1] for _, v in sorted(chosen.items())]
    print(f"phase 2: {len(filings)} filings selected", flush=True)

    # Phase 3: download type=5 CSVs and extract GP / TA
    n_ok = n_fail = 0
    for i, r in enumerate(filings):
        if over_budget():
            save_state()
            gpa_file.close()
            print("BUDGET_STOP phase3", flush=True)
            return 0
        doc = r["docID"]
        if doc in done_docs:
            continue
        body = fetch(f"{BASE}/documents/{doc}?type=5", args.spacing)
        got = extract_gp_ta(body)
        if got is None:
            n_fail += 1
            print(f"  [{i + 1}/{len(filings)}] {doc} "
                  f"{r.get('secCode')} NO GP/TA", flush=True)
        else:
            gp, ta, consol = got
            writer.writerow([r["secCode"][:4], r.get("periodEnd"),
                             r.get("submitDateTime"), doc,
                             r["docTypeCode"], f"{gp:.0f}", f"{ta:.0f}",
                             f"{gp / ta:.6f}" if ta else "",
                             1 if consol else 0])
            gpa_file.flush()
            n_ok += 1
            print(f"  [{i + 1}/{len(filings)}] {doc} {r.get('secCode')} "
                  f"GP={gp:,.0f} TA={ta:,.0f} GPA={gp / ta:.3f}", flush=True)
        done_docs.add(doc)
        if (i + 1) % 50 == 0:
            save_state()
        if args.max_filings and n_ok + n_fail >= args.max_filings:
            print("smoke limit reached", flush=True)
            break
    save_state()
    gpa_file.close()

    digest = hashlib.sha256(gpa_path.read_bytes()).hexdigest()
    manifest = {"gpa_csv_sha256": digest, "extracted_ok": n_ok,
                "no_gp_ta": n_fail, "filings_selected": len(filings),
                "lists_days": len(listed)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
