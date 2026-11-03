"""Sample accuracy probe: geographic sales extraction from EDINET
annual securities reports (text block) for 30 universe filers.

Parse rule: CurrentYearDuration RevenuesFromExternalCustomers-
InformationForEachRegionTextBlock; numbers are thousands-grouped and
concatenated; validate by sum(parts) == total; Japan = first value.
Report: coverage (block present), parse pass rate, failures.
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import urllib.parse
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "EA", "/home/hatch/workspace/custom-connectors/custom.edinet/bin/edinet_api.py")
EA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(EA)
HOST = "https://api.edinet-fsa.go.jp/api/v2"
OUT = Path("/home/hatch/workspace/exp078_probe")
UNI = {p.stem for p in Path("/home/hatch/workspace/cache/jquants_exp002/bars").glob("*.json")}
FW = str.maketrans("０１２３４５６７８９，", "0123456789,")


def fetch_json(url):
    st, _, body = EA.fetch(url)
    return json.loads(body) if st == 200 else None


def collect_sample(n=30):
    got = {}
    for d in range(1, 31):
        if len(got) >= n:
            break
        date = f"2025-06-{d:02d}"
        data = fetch_json(f"{HOST}/documents.json?" +
                          urllib.parse.urlencode({"date": date, "type": 2}))
        if not data:
            continue
        for r in data.get("results", []):
            code = (r.get("secCode") or "")[:4]
            if (r.get("docTypeCode") == "120" and code in UNI
                    and r.get("csvFlag") == "1" and code not in got):
                got[code] = {"code": code, "doc": r["docID"],
                             "name": r["filerName"], "filed": date}
        print(f"{date}: sample {len(got)}", flush=True)
    return list(got.values())


def parse_block(text: str):
    """Return (japan_share, n_numbers, status).

    v2: regional figures are truncated independently, so footing is
    validated with a tolerance of 1 unit per part. A dash counts as 0.
    The omission note (Japan > 90%) is usable as a censored value.
    """
    t = text.translate(FW)
    t = re.sub(r"\s+", "", t)
    if "90" in t and "省略" in t and "本邦" in t:
        return None, 0, "omitted_japan_gt90"
    i = t.find("売上高")
    if i < 0:
        return None, 0, "no_sales_header"
    seg = t[i:]
    j = seg.find("(注)")
    if j > 0:
        seg = seg[:j]
    m = re.search(r"\d", seg)
    if not m:
        return None, 0, "no_digits"
    digits = seg[m.start():]
    digits = re.split(r"[（(]", digits)[0]
    nums, pos = [], 0
    pat = re.compile(r"\d{1,3}(?:,\d{3})+|\d+|－|-")
    while pos < len(digits):
        mm = pat.match(digits, pos)
        if not mm:
            return None, 0, "segmentation_fail"
        g = mm.group()
        nums.append(0 if g in ("－", "-") else int(g.replace(",", "")))
        pos = mm.end()
    if len(nums) < 2:
        return None, len(nums), "too_few_numbers"
    parts, total = nums[:-1], nums[-1]
    if abs(sum(parts) - total) > len(parts):
        return None, len(nums), "sum_mismatch"
    if not (0 < parts[0] <= total):
        return None, len(nums), "japan_out_of_range"
    return parts[0] / total, len(nums), "ok"


def extract(docid: str):
    st, _, body = EA.fetch(f"{HOST}/documents/{docid}?type=5")
    if st != 200:
        return None, "download_fail"
    z = zipfile.ZipFile(io.BytesIO(body))
    for n in z.namelist():
        if not n.endswith(".csv"):
            continue
        raw = z.read(n).decode("utf-16", errors="replace")
        for line in raw.splitlines():
            cols = [c.strip().strip('"') for c in line.split("\t")]
            if (len(cols) >= 9
                    and "RevenuesFromExternalCustomersInformationForEachRegionTextBlock" in cols[0]
                    and cols[2] == "CurrentYearDuration"):
                return cols[8], "block_found"
    return None, "block_missing"


def main():
    sample_file = OUT / "sample.json"
    if sample_file.exists():
        sample = json.loads(sample_file.read_text())
    else:
        sample = collect_sample()
        sample_file.write_text(json.dumps(sample, ensure_ascii=False))
    print(f"sample size: {len(sample)}")
    results = []
    for s in sample:
        text, status = extract(s["doc"])
        if text is None:
            results.append({**s, "status": status})
            print(s["code"], s["name"][:14], status, flush=True)
            continue
        share, nnum, pstatus = parse_block(text)
        results.append({**s, "status": pstatus, "japan_share": share,
                        "n_numbers": nnum})
        print(s["code"], s["name"][:14], pstatus,
              f"japan={share:.3f}" if share is not None else "", flush=True)
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    from collections import Counter
    c = Counter(r["status"] for r in results)
    ok = c.get("ok", 0)
    found = sum(v for k2, v in c.items() if k2 != "block_missing" and k2 != "download_fail")
    print("\nstatus counts:", dict(c))
    print(f"block coverage: {found}/{len(results)} = {found / len(results):.0%}")
    print(f"parse success (of sample): {ok}/{len(results)} = {ok / len(results):.0%}")
    print(f"parse success (of blocks): {ok}/{found} = {ok / found:.0%}" if found else "")


if __name__ == "__main__":
    main()
