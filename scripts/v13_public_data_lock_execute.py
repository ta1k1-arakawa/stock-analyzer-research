"""Guarded V13 acquisition. The Direct-Windows wrapper supplies the human gate."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import BinaryIO, Callable
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import v13_public_data_lock as pipeline

STUDY = "V13_CONDITIONAL_CROSS_SECTIONAL_SHORT_HORIZON"
OPERATION_SCHEMA = "V13_PUBLIC_DATALOCK_OPERATION_V1"
SAFE_SCHEMA = "V13_PUBLIC_DATALOCK_SAFE_MANIFEST_V2"


class _OfficialLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if re.search(r"(?:^|/)data_j\.xlsx?(?:\?|$)", href, re.I):
                self.links.append(href)


def _network_fetch(url: str) -> BinaryIO:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.jpx.co.jp", "query1.finance.yahoo.com"}:
        raise ValueError("PROVIDER_MISMATCH")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    response = urllib.request.urlopen(request, timeout=30)
    if urllib.parse.urlparse(response.geturl()).hostname != parsed.hostname:
        response.close()
        raise ValueError("REDIRECT_HOST_MISMATCH")
    return response


def _json_bytes(obj: dict) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _publish_json(path: Path, obj: dict) -> None:
    pending = path.with_name(path.name + ".pending")
    if path.exists() or pending.exists():
        raise ValueError("JSON_PUBLICATION_COLLISION")
    with pending.open("xb") as stream:
        stream.write(_json_bytes(obj))
        stream.flush()
        os.fsync(stream.fileno())
    if path.exists():
        raise ValueError("JSON_PUBLICATION_COLLISION")
    os.replace(pending, path)


def _existing_json(path: Path) -> dict | None:
    if path.with_name(path.name + ".pending").exists():
        raise ValueError("AMBIGUOUS_PENDING_JSON")
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("JSON_NOT_FILE")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("JSON_SCHEMA_MISMATCH")
    return value


def _bound_json(path: Path, expected: dict) -> None:
    observed = _existing_json(path)
    if observed is None:
        _publish_json(path, expected)
    elif observed != expected:
        raise ValueError("DURABLE_STATE_MISMATCH")


def _raw(url: str, path: Path, fetch: Callable[[str], BinaryIO]) -> pipeline.RawLock:
    existing = pipeline.existing_raw_lock(path)
    if existing is not None:
        return existing
    return pipeline.acquire_raw_lock(path, lambda: fetch(url))


def _operation(implementation_sha: str) -> dict:
    return {"schema": OPERATION_SCHEMA, "study": STUDY,
            "implementation_sha": implementation_sha,
            "calendar_sha256": pipeline.MASTER_CALENDAR_SHA256,
            "calendar_result_blob": pipeline.MASTER_CALENDAR_SAFE_RESULT_BLOB,
            "jpx_provider": "www.jpx.co.jp", "yahoo_provider": "query1.finance.yahoo.com",
            "window_start": pipeline.START.isoformat(), "window_end": pipeline.END.isoformat(),
            "jpx_page": pipeline.JPX_PAGE}


def preflight_calendar(calendar_lock: Path, calendar_sha256: str,
                       safe_result_path: Path | None = None) -> dict:
    result_path = safe_result_path or (Path(__file__).resolve().parents[1] / "docs/v13/V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT.json")
    pipeline.validate_generated_calendar_result(result_path.read_bytes())
    _, manifest = pipeline.validate_generated_calendar(calendar_lock.read_bytes(), calendar_sha256)
    return manifest


def execute(*, t1_state: Path, v4_csv: Path, calendar_lock: Path,
            calendar_sha256: str, output: Path, implementation_sha: str,
            fetch: Callable[[str], BinaryIO] = _network_fetch,
            safe_result_path: Path | None = None) -> dict:
    """Resume the same operation root. Tests inject a fake transport."""
    if not re.fullmatch(r"[0-9a-f]{40}", implementation_sha):
        raise ValueError("IMPLEMENTATION_SHA_REQUIRED")
    calendar_manifest = preflight_calendar(calendar_lock, calendar_sha256, safe_result_path)
    operation = _operation(implementation_sha)
    completed_present = False
    if output.exists():
        if not output.is_dir():
            raise ValueError("OUTPUT_NOT_DIRECTORY")
        observed_operation = _existing_json(output / "operation.json")
        if observed_operation is None and not any(output.iterdir()):
            _publish_json(output / "operation.json", operation)
            observed_operation = operation
        if observed_operation != operation:
            raise ValueError("OPERATION_MISMATCH")
        completed_present = _existing_json(output / "safe-manifest.json") is not None
    else:
        output.mkdir(mode=0o700)
        _publish_json(output / "operation.json", operation)
    if completed_present:
        def no_fetch(_url: str) -> BinaryIO:
            raise ValueError("COMPLETED_OPERATION_RAW_LOCK_MISSING")
        fetch = no_fetch
    # Selection is always recomputed from the bound private T1 state and
    # the original locked JPX bytes, including when a safe manifest exists.
    t1 = pipeline.validate_t1_state(json.loads(t1_state.read_bytes()))
    v4 = pipeline.read_v4_codes(v4_csv.read_bytes())
    excluded, exclusion_manifest = pipeline.build_exclusions(v4, t1)
    page = _raw(pipeline.JPX_PAGE, output / "jpx-page.raw", fetch)
    links = _OfficialLinks()
    links.feed(page.raw.decode("utf-8", errors="replace"))
    candidates = sorted(set(urllib.parse.urljoin(pipeline.JPX_PAGE, href) for href in links.links))
    if len(candidates) != 1 or urllib.parse.urlparse(candidates[0]).hostname != "www.jpx.co.jp":
        raise ValueError("JPX_SOURCE_AMBIGUOUS")
    jpx = _raw(candidates[0], output / "jpx-listed-issues.raw", fetch)
    eligible = pipeline.parse_jpx(jpx)
    selected, universe_manifest = pipeline.select_universe(
        eligible, excluded, jpx, implementation_sha, "LOCKED_PUBLIC_PAYLOAD")
    universe_manifest["jpx_payload_url_sha256"] = pipeline.digest(candidates[0].encode("utf-8"))
    universe_manifest["jpx_page_raw_sha256"] = page.sha256
    _bound_json(output / "selected.private.json", {"selected": selected})
    price_manifests = []
    omitted_observations = 0
    omitted_payloads = 0
    invalid_high_rows = 0
    invalid_low_rows = 0
    invalid_both_rows = 0
    tokyo = ZoneInfo("Asia/Tokyo")
    period1 = int(datetime(2015, 1, 1, tzinfo=tokyo).timestamp())
    period2 = int(datetime(2026, 1, 1, tzinfo=tokyo).timestamp())
    params = urllib.parse.urlencode({"period1": period1, "period2": period2,
                                     "interval": "1d", "events": "history",
                                     "includeAdjustedClose": "true"})
    for code in selected:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.T?{params}"
        lock = _raw(url, output / f"yahoo-{code}.raw", fetch)
        rows, manifest = pipeline.parse_yahoo(
            lock, code, omit_provider_invalid_ohlc_ordering=True)
        omitted = manifest["omitted_provider_invalid_ohlc_ordering_count"]
        omitted_observations += omitted
        omitted_payloads += int(omitted > 0)
        invalid_high_rows += manifest["provider_invalid_high_order_row_count"]
        invalid_low_rows += manifest["provider_invalid_low_order_row_count"]
        invalid_both_rows += manifest["provider_invalid_both_order_row_count"]
        _bound_json(output / f"price-{code}.private.json",
                    {day.isoformat(): row for day, row in rows.items()})
        price_manifests.append(manifest)
    safe_universe = {key: value for key, value in universe_manifest.items()
                     if key in {"raw_sha256", "raw_byte_count", "eligible_count", "eligible_sha256",
                                "exclusion_count", "exclusion_sha256", "selected_count",
                                "selected_sha256", "implementation_sha",
                                "jpx_payload_url_sha256", "jpx_page_raw_sha256"}}
    safe_calendar = {key: value for key, value in calendar_manifest.items()
                     if key != "input_type"}
    safe = {"schema": SAFE_SCHEMA,
            "operation_sha256": pipeline.digest(_json_bytes(operation)),
            "jpx_page": page.manifest(), "jpx": jpx.manifest(),
            "exclusions": exclusion_manifest, "universe": safe_universe,
            "calendar": safe_calendar, "yahoo_payload_count": len(price_manifests),
            "yahoo_raw_set_sha256": pipeline.digest(json.dumps(price_manifests, sort_keys=True).encode()),
            "provider_invalid_ohlc_ordering_omitted_count": omitted_observations,
            "provider_invalid_ohlc_ordering_payload_count": omitted_payloads,
            "provider_invalid_high_order_row_count": invalid_high_rows,
            "provider_invalid_low_order_row_count": invalid_low_rows,
            "provider_invalid_both_order_row_count": invalid_both_rows,
            "model_fits": 0, "backtests": 0, "outcome_calculations": 0}
    completed = _existing_json(output / "safe-manifest.json")
    if completed is not None:
        if completed != safe:
            raise ValueError("SAFE_MANIFEST_MISMATCH")
        return completed
    _publish_json(output / "safe-manifest.json", safe)
    return safe


def main() -> int:
    if sys.argv[1:2] == ["--preflight-calendar"]:
        if len(sys.argv) != 4:
            raise ValueError("CALENDAR_PREFLIGHT_ARGUMENTS")
        preflight_calendar(Path(sys.argv[2]), sys.argv[3])
        print("CALENDAR_PREFLIGHT_PASS=true")
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--t1-state", type=Path, required=True)
    parser.add_argument("--v4-csv", type=Path, required=True)
    parser.add_argument("--calendar-lock", type=Path, required=True)
    parser.add_argument("--calendar-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--implementation-sha", required=True)
    args = parser.parse_args()
    execute(**vars(args))
    print("PUBLIC_DATALOCK_PASS=true")
    print("YAHOO_PAYLOAD_COUNT=500")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("PUBLIC_DATALOCK_PASS=false", file=sys.stderr)
        sys.exit(1)
