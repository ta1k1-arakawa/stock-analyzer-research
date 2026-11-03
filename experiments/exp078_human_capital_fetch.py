"""Fetch average salary + headcount from EDINET annual securities
reports for two waves (FY ends 2021-07..2022-06 and 2024-07..2025-06).

Target scan days come from the J-Quants fins FY DiscDates in the
EXP-002 cache (ASR follows the earnings release by ~1-6 weeks).
Resumable: list responses and extracted values are cached on disk.
Output: waves.json {wave: {code: {salary, hc_now, hc_p3, period_end, filed}}}
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import time
import urllib.parse
import zipfile
from pathlib import Path

import pandas as pd

spec = importlib.util.spec_from_file_location(
    "EA", "/home/hatch/workspace/custom-connectors/custom.edinet/bin/edinet_api.py")
EA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(EA)
HOST = "https://api.edinet-fsa.go.jp/api/v2"
OUT = Path("/home/hatch/workspace/exp079_kill")
CACHE = Path("/home/hatch/workspace/cache/jquants_exp002")
SALARY_EL = "AverageAnnualSalaryInformationAboutReportingCompanyInformationAboutEmployees"
EMP_EL = "jpcrp_cor:NumberOfEmployees"


def fetch_json(url: str):
    for k in range(4):
        try:
            st, _, body = EA.fetch(url)
            return json.loads(body) if st == 200 else None
        except Exception:
            time.sleep(2 * (k + 1))
    return None


def list_day(ds: str):
    f = OUT / "lists" / f"{ds}.json"
    if f.exists():
        return json.loads(f.read_text())
    data = fetch_json(f"{HOST}/documents.json?" +
                      urllib.parse.urlencode({"date": ds, "type": 2}))
    if data is None:
        return None
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(data))
    time.sleep(0.25)
    return data


def extract(docid: str) -> dict | None:
    body = None
    for k in range(4):
        try:
            st, _, body = EA.fetch(f"{HOST}/documents/{docid}?type=5")
            if st == 200:
                break
            body = None
        except Exception:
            body = None
            time.sleep(2 * (k + 1))
    if body is None:
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
    except Exception:
        return None
    salary = hc_now = hc_p3 = None
    for n in z.namelist():
        if not n.endswith(".csv"):
            continue
        raw = z.read(n).decode("utf-16", errors="replace")
        for line in raw.splitlines():
            cols = [c.strip().strip('"') for c in line.split("\t")]
            if len(cols) < 9:
                continue
            el, ctx, val = cols[0], cols[2], cols[8]
            if SALARY_EL in el and ctx == "CurrentYearInstant_NonConsolidatedMember":
                try:
                    salary = float(val.replace(",", ""))
                except Exception:
                    pass
            elif el == EMP_EL and ctx == "CurrentYearInstant":
                try:
                    hc_now = float(val.replace(",", ""))
                except Exception:
                    pass
            elif el == EMP_EL and ctx == "Prior3YearInstant":
                try:
                    hc_p3 = float(val.replace(",", ""))
                except Exception:
                    pass
    if salary is None and hc_now is None:
        return None
    return {"salary": salary, "hc_now": hc_now, "hc_p3": hc_p3}


def wave_targets(wave: str):
    """code -> (period_end, disc_date) from fins FY records."""
    lo, hi = (("2021-07-01", "2022-06-30") if wave == "w2022"
              else ("2024-07-01", "2025-06-30"))
    out = {}
    for jf in sorted((CACHE / "fins").glob("*.json")):
        code = jf.stem
        for r in json.loads(jf.read_text()):
            if ("FinancialStatements" not in str(r.get("DocType"))
                    or r.get("CurPerType") != "FY" or not r.get("CurFYEn")):
                continue
            pe, dd = r["CurFYEn"], r.get("DiscDate")
            if lo <= pe <= hi and dd:
                if code not in out or pe > out[code][0]:
                    out[code] = (pe, dd)
    return out


def run_wave(wave: str) -> dict:
    targets = wave_targets(wave)
    days = set()
    for _, dd in targets.values():
        base = pd.Timestamp(dd)
        for k in range(3, 46):
            days.add(str((base + pd.Timedelta(days=k)).date()))
    print(f"{wave}: {len(targets)} codes, {len(days)} scan days", flush=True)
    found = {}
    for ds in sorted(days):
        data = list_day(ds)
        if not data:
            continue
        for r in data.get("results", []):
            code = (r.get("secCode") or "")[:4]
            if (r.get("docTypeCode") == "120" and code in targets
                    and r.get("csvFlag") == "1" and code not in found):
                pe, _ = targets[code]
                found[code] = {"doc": r["docID"], "period_end": pe, "filed": ds}
    print(f"{wave}: filings found {len(found)}", flush=True)
    result = {}
    done_file = OUT / f"{wave}_values.json"
    if done_file.exists():
        result = json.loads(done_file.read_text())
    for i, (code, meta) in enumerate(sorted(found.items())):
        if code in result:
            continue
        vals = extract(meta["doc"])
        if vals:
            result[code] = {**vals, "period_end": meta["period_end"],
                            "filed": meta["filed"]}
        if i % 25 == 0:
            done_file.write_text(json.dumps(result))
            print(f"{wave}: extracted {len(result)}", flush=True)
        time.sleep(0.2)
    done_file.write_text(json.dumps(result))
    print(f"{wave}: DONE extracted {len(result)}", flush=True)
    return result


if __name__ == "__main__":
    waves = {}
    for w in ("w2022", "w2025"):
        waves[w] = run_wave(w)
    (OUT / "waves.json").write_text(json.dumps(waves))
    print("ALL DONE")
