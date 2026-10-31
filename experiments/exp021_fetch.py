"""EXP-021: fetch the wide (Prime, ~1,550 code) J-Quants cache.

Preregistration: docs/experiments/EXP-021_PREREGISTRATION.md (committed
before this code was run).  Writes an EXP-002-shaped cache (bars/,
fins/, topix.json) plus universe.json with sector codes.  Resumable:
codes whose output file already exists and is non-empty are skipped,
so the script can be re-launched after an interruption.  Failures are
logged to failures.json in the output directory for a later mop-up.

Run:  python experiments/exp021_fetch.py [out_dir]
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/hatch/workspace/custom-connectors/custom.jquants/bin")
from jquants_api import get_json  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/jquants_wide")
MASTER_DATE = "2026-10-30"
FROM = "2016-10-31"
TO = "2026-10-30"
SPACING = 0.5


def save(path: Path, obj) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False))
    tmp.replace(path)


def fetch_with_retry(path, params, tag):
    delay = 30
    for attempt in range(4):
        try:
            return get_json(path, params)["data"]
        except Exception as e:  # HTTPError surfaces as SystemExit text;
            # network drops (RemoteDisconnected, URLError) arrive raw
            msg = f"{type(e).__name__}: {e}"
            transient = isinstance(e, SystemExit) and not any(
                s in msg for s in ("400", "401", "403", "404")) \
                or not isinstance(e, SystemExit)
            if transient and attempt < 3:
                print(f"[retry {attempt + 1}] {tag}: {msg[:120]}", flush=True)
                time.sleep(delay)
                delay *= 2
                continue
            raise


def main() -> None:
    (OUT / "bars").mkdir(parents=True, exist_ok=True)
    (OUT / "fins").mkdir(parents=True, exist_ok=True)

    master = fetch_with_retry("/v2/equities/master", {"date": MASTER_DATE},
                              "master")
    universe = [r for r in master
                if r.get("MktNm") == "プライム" and r.get("ProdCat") == "011"]
    save(OUT / "universe.json", universe)
    codes5 = sorted(r["Code"] for r in universe)
    print(f"universe: {len(codes5)} codes", flush=True)

    if not (OUT / "topix.json").exists():
        topix = fetch_with_retry("/v2/indices/bars/daily/topix",
                                 {"from": FROM, "to": TO}, "topix")
        save(OUT / "topix.json", topix)
        print(f"topix: {len(topix)} rows", flush=True)

    failures = []
    done = 0
    for i, code5 in enumerate(codes5):
        code4 = code5[:4]
        try:
            bp = OUT / "bars" / f"{code4}.json"
            if not (bp.exists() and bp.stat().st_size > 2):
                bars = fetch_with_retry(
                    "/v2/equities/bars/daily",
                    {"code": code5, "from": FROM, "to": TO}, f"bars {code5}")
                save(bp, bars)
                time.sleep(SPACING)
            fp = OUT / "fins" / f"{code4}.json"
            if not (fp.exists() and fp.stat().st_size > 2):
                fins = fetch_with_retry("/v2/fins/summary",
                                        {"code": code5}, f"fins {code5}")
                save(fp, fins)
                time.sleep(SPACING)
        except Exception as e:
            failures.append({"code": code5,
                             "error": f"{type(e).__name__}: {e}"[:200]})
            print(f"[fail] {code5}: {type(e).__name__}: {str(e)[:140]}",
                  flush=True)
        done += 1
        if done % 25 == 0 or done == len(codes5):
            print(f"[{done}/{len(codes5)}] failures={len(failures)}",
                  flush=True)
    save(OUT / "failures.json", failures)
    print(f"DONE codes={len(codes5)} failures={len(failures)}", flush=True)


if __name__ == "__main__":
    main()
