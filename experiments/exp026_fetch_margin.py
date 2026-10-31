"""EXP-026 data fetch: weekly margin interest for the EXP-002 universe.

Pulls /v2/markets/margin-interest for every code in the EXP-002 cache
(2016-10-31..2026-09-30) and stores the raw rows as
<out_dir>/<code4>.json. Resumable: codes whose file exists and is
non-empty are skipped.

Usage:
    python experiments/exp026_fetch_margin.py <exp002_cache> <out_dir>
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(
    0, str(Path.home() / "workspace/custom-connectors/custom.jquants/bin"))
from jquants_api import get_json  # noqa: E402

FROM, TO = "2016-10-31", "2026-09-30"


def main(cache: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    codes = sorted(p.stem for p in (cache / "bars").glob("*.json"))
    failures = []
    done = 0
    for i, code4 in enumerate(codes, 1):
        f = out_dir / f"{code4}.json"
        if f.exists() and f.stat().st_size > 2:
            done += 1
            continue
        try:
            rows = get_json("/v2/markets/margin-interest",
                            {"code": code4 + "0", "from": FROM,
                             "to": TO})["data"]
            f.write_text(json.dumps(rows))
            done += 1
        except Exception as e:
            failures.append({"code": code4, "error": str(e)[:160]})
        if i % 50 == 0:
            print(f"[{i}/{len(codes)}] done={done} failures={len(failures)}",
                  flush=True)
        time.sleep(0.3)
    (out_dir / "failures.json").write_text(json.dumps(failures, indent=1))
    print(f"DONE done={done} failures={len(failures)}", flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
