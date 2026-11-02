"""EXP-075: accumulate AGM voting results from EDINET extraordinary
reports (docTypeCode 180) for the 306-code universe.

Archive-first: every matched filing's XBRL-to-CSV zip is saved under
~/workspace/cache/edinet_agm/zips/, and the per-candidate approval
rates parsed from the resolution text block are appended to
~/workspace/cache/edinet_agm/agm_votes.csv. Resumable: completed list
dates are recorded in state.json and skipped on rerun.

Usage:
    accumulate_agm.py --from 2025-01-01 --to 2026-11-02
    accumulate_agm.py --recent 12        (trailing N days, for cron)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, "/home/hatch/workspace/custom-connectors/custom.edinet/bin")
sys.path.insert(0, "/home/hatch/workspace/exp046_push/experiments")
import edinet_api as EA  # noqa: E402
import exp003_rotation as E3  # noqa: E402

BASE = Path("/home/hatch/workspace/cache/edinet_agm")
ZIPS = BASE / "zips"
OUT = BASE / "agm_votes.csv"
STATE = BASE / "state.json"
HOST = "https://api.edinet-fsa.go.jp/api/v2"


def universe() -> set[str]:
    _, panel, _ = E3.load(Path("/home/hatch/workspace/cache/jquants_exp002"))
    return {c + "0" for c in panel["C"].columns}


def fetch_json(url: str, tries: int = 3) -> dict | None:
    for k in range(tries):
        status, _, body = EA.fetch(url)
        if status == 200:
            return json.loads(body.decode("utf-8"))
        if status == 429 or status >= 500:
            time.sleep(5 * (k + 1))
            continue
        return None
    return None


def fetch_bytes(url: str, tries: int = 3) -> bytes | None:
    for k in range(tries):
        status, _, body = EA.fetch(url)
        if status == 200:
            return body
        if status == 429 or status >= 500:
            time.sleep(5 * (k + 1))
            continue
        return None
    return None


NUM = r"\d{1,3}(?:,\d{3})+|\d+"
ROW_RE = re.compile(
    rf"(?P<name>[一-龥ぁ-んァ-ヶ・]{{2,12}}?)(?P<for>{NUM})(?P<rest>\d[\d,]*?)"
    rf"(?:\(注\)\d+)?(?P<result>可決|否決)\(?(?P<appr>\d{{1,3}}\.\d+)%?\)?")
PROP_RE = re.compile(rf"(?:\(注\)\d+)?(可決|否決)\(?(\d{{1,3}}\.\d+)%?\)?")
_FW = str.maketrans("０１２３４５６７８９（）％", "0123456789()%")


def normalize(s: str) -> str:
    return re.sub(r"\s+", "", s.translate(_FW))


def split_rest(rest: str, votes_for: int, appr: float) -> tuple[int, int] | None:
    """rest = AGAINST and ABSTAIN digit runs concatenated (commas kept
    inside AGAINST when present). Choose the split whose implied
    approval % matches the stated one within 0.06pt."""
    cands = []
    if "," in rest:
        i = rest.rindex(",")
        head = rest[: i + 3] if len(rest) >= i + 3 else rest
        cands.append((head, rest[len(head):]))
    for cut in range(1, len(rest)):
        cands.append((rest[:cut], rest[cut:]))
    for a_str, b_str in cands:
        try:
            against = int(a_str.replace(",", ""))
            abstain = int(b_str) if b_str else 0
        except ValueError:
            continue
        tot = votes_for + against + abstain
        if tot > 0 and abs(100.0 * votes_for / tot - appr) <= 0.06:
            return against, abstain
    return None


def candidate_names(t: str) -> set[str]:
    """Names are enumerated in the agenda part ('…として、A、B、Cを選任')."""
    names: set[str] = set()
    for m in re.finditer(r"として、?(.{2,200}?)を選任", t):
        for nm in re.split(r"[、及びおよび]+", m.group(1)):
            nm = nm.strip("　 ")
            if 2 <= len(nm) <= 6 and re.fullmatch(r"[一-龥ぁ-んァ-ヶ・]+", nm):
                names.add(nm)
    return names


def parse_votes(text: str) -> tuple[list[dict], list[dict]]:
    """Return (candidate rows, shareholder-proposal rows). Candidate
    rows are accepted only when the name was enumerated in the agenda
    part as an election candidate."""
    t = normalize(text)
    names = candidate_names(t)
    i = t.rfind("決議の結果")
    region = t[i:] if i >= 0 else t
    agenda = t[:i] if i >= 0 else ""
    cands = []
    pos = 0
    while True:
        m = ROW_RE.search(region, pos)
        if not m:
            break
        nm = m.group("name")
        if nm not in names:
            pos = m.start() + 1  # over-long name swallowed the real row
            continue
        pos = m.end()
        votes_for = int(m.group("for").replace(",", ""))
        appr = float(m.group("appr"))
        sp = split_rest(m.group("rest"), votes_for, appr)
        cands.append({"name": nm, "approval_pct": appr,
                      "result": m.group("result"),
                      "verified": sp is not None})
    props = []
    sections = re.split(r"(第\d+号議案)", region)
    for j in range(1, len(sections), 2):
        head = sections[j] + sections[j + 1][:30]
        if "株主提案" in head:
            m = PROP_RE.search(sections[j + 1])
            if m:
                props.append({"header": head[:40],
                              "approval_pct": float(m.group(2)),
                              "result": m.group(1), "shareholder": True})
    return cands, props


def extract(zip_bytes: bytes) -> dict | None:
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    csv_names = [n for n in z.namelist() if n.endswith(".csv")]
    if not csv_names:
        return None
    raw = z.read(csv_names[0]).decode("utf-16", errors="replace")
    rep_name, text = "", ""
    for row in csv.reader(io.StringIO(raw), delimiter="\t"):
        if not row:
            continue
        eid = row[0]
        val = row[-1] if len(row) > 1 else ""
        if eid.endswith("TitleAndNameOfRepresentativeCoverPage"):
            rep_name = re.sub(r"\s+", "", val)
        if eid.endswith("ResolutionOfShareholdersMeetingTextBlock"):
            text = val
    if not text:
        return None
    rows, props = parse_votes(text)
    for r in rows:  # representative = candidate whose name ends the title string
        if rep_name.endswith(r["name"]):
            r["is_rep"] = True
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", normalize(text))
    agm_date = (f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                if m else "")
    shp = [p for p in props if p["shareholder"]]
    return {"agm_date": agm_date, "rep_name": rep_name, "rows": rows,
            "has_shareholder_proposal": bool(shp),
            "shareholder_max_approval": max(
                (p["approval_pct"] for p in shp), default=None)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="dfrom")
    ap.add_argument("--to", dest="dto")
    ap.add_argument("--recent", type=int)
    args = ap.parse_args()
    import pandas as pd
    today = pd.Timestamp.now(tz="Asia/Tokyo").normalize().tz_localize(None)
    if args.recent:
        dto = today - pd.Timedelta(days=1)
        dfrom = dto - pd.Timedelta(days=args.recent - 1)
    else:
        dfrom, dto = pd.Timestamp(args.dfrom), pd.Timestamp(args.dto)
    BASE.mkdir(parents=True, exist_ok=True)
    ZIPS.mkdir(parents=True, exist_ok=True)
    state = (json.loads(STATE.read_text()) if STATE.exists()
             else {"done_dates": [], "docids": []})
    done = set(state["done_dates"])
    seen_docs = set(state["docids"])
    uni = universe()
    new_rows = []
    day = dfrom
    while day <= dto:
        ds = str(day.date())
        if ds in done:
            day += pd.Timedelta(days=1)
            continue
        d = fetch_json(f"{HOST}/documents.json?date={ds}&type=2")
        if d is None:
            print(f"{ds}: list fetch failed, will retry next run", flush=True)
            day += pd.Timedelta(days=1)
            continue
        targets = [r for r in d.get("results", [])
                   if r.get("docTypeCode") == "180"
                   and r.get("secCode") in uni
                   and r.get("docID") not in seen_docs]
        for r in targets:
            doc = r["docID"]
            body = fetch_bytes(f"{HOST}/documents/{doc}?type=5")
            if body is None:
                print(f"{ds} {doc}: download failed", flush=True)
                continue
            (ZIPS / f"{doc}.zip").write_bytes(body)
            seen_docs.add(doc)
            try:
                ext = extract(body)
            except Exception as e:  # keep the zip; parsing can be redone
                print(f"{ds} {doc}: extract error {e}", flush=True)
                ext = None
            code = (r.get("secCode") or "")[:4]
            if ext and ext["rows"]:
                apprs = [x["approval_pct"] for x in ext["rows"]]
                rep_appr = next((x["approval_pct"] for x in ext["rows"]
                                 if x.get("is_rep")), None)
                new_rows.append({
                    "code": code, "filer": r.get("filerName", ""),
                    "submit": ds, "agm_date": ext["agm_date"], "doc_id": doc,
                    "n_candidates": len(ext["rows"]),
                    "min_approval_pct": min(apprs),
                    "rep_approval_pct": rep_appr if rep_appr is not None else "",
                    "shareholder_proposal": int(ext["has_shareholder_proposal"]),
                    "shareholder_max_approval": (
                        ext["shareholder_max_approval"]
                        if ext["shareholder_max_approval"] is not None else ""),
                    "all_approval_pcts": ";".join(str(a) for a in apprs)})
            else:
                new_rows.append({
                    "code": code, "filer": r.get("filerName", ""),
                    "submit": ds, "agm_date": "", "doc_id": doc,
                    "n_candidates": 0, "min_approval_pct": "",
                    "rep_approval_pct": "", "shareholder_proposal": "",
                    "shareholder_max_approval": "",
                    "all_approval_pcts": ""})
            time.sleep(1.2)
        done.add(ds)
        state = {"done_dates": sorted(done), "docids": sorted(seen_docs)}
        STATE.write_text(json.dumps(state))
        print(f"{ds}: done (targets {len(targets)})", flush=True)
        day += pd.Timedelta(days=1)
    if new_rows:
        exists = OUT.exists()
        with OUT.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(new_rows[0].keys()))
            if not exists:
                w.writeheader()
            w.writerows(new_rows)
    print(f"finished: {len(new_rows)} filings recorded")


if __name__ == "__main__":
    main()
