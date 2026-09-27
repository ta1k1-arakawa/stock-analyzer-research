"""Offline V13 public data locks. Callers must preserve bytes before parsing.

This module performs no network access, private-path discovery, or outcome work.
Identity-bearing return values must stay in protected local storage; only the
``*_manifest`` dictionaries are suitable for public reports.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable
from zoneinfo import ZoneInfo

START = date(2015, 1, 1)
END = date(2025, 12, 31)
V13_MASTER_CALENDAR_SOURCE_IDENTITY = "PANDAS_MARKET_CALENDARS_JPX_5_4_0_RELEASE_ARTIFACT"
MASTER_CALENDAR_SAFE_RESULT_BLOB = "336e5dd6141230b95fa4548231b0a137be6a15cb"
MASTER_CALENDAR_SHA256 = "30ad5d66c6c3b8bd2c71a814309e6133a03331437089103799551fa72150c44c"
MASTER_CALENDAR_SESSION_COUNT = 2687
CALENDAR_PROVENANCE = (
    ("source_identity", V13_MASTER_CALENDAR_SOURCE_IDENTITY),
    ("calendar_name", "JPX"),
    ("pandas_market_calendars_version", "5.4.0"),
    ("exchange_calendars_version", "4.13.2"),
    ("release_tag", "v5.4.0"),
    ("release_tag_commit", "275890784073a3a3a347e4f05f4dc986456e6a75"),
    ("jpx_source_file", "pandas_market_calendars/calendars/jpx.py"),
    ("jpx_source_blob", "a7a59b6cf910e325c85fc042459ff57ca8f70613"),
    ("holiday_source_file", "pandas_market_calendars/holidays/jp.py"),
    ("holiday_source_blob", "4c34214d06862e02ac22e946757463f748074fde"),
    ("official_pypi_wheel", "pandas_market_calendars-5.4.0-py3-none-any.whl"),
    ("official_pypi_wheel_sha256", "bb2b93b28d496cab173b41c7d120fd5cd9d506b31f3bb0ad3d1d9f2b60d9d9e3"),
    ("coverage_start", "2015-01-01"),
    ("coverage_end", "2025-12-31"),
)
SEED = "V13_CONDITIONAL_CROSS_SECTIONAL_SHORT_HORIZON|f9c38ad771710ffd157ac4fad0da15185db82707"
T1_SHA256 = "262201792183776e3bead4638646ee949c05d35c894c7a4053556befa6230e1d"
SOURCE_SCHEMA = "V8_JQUANTS_IDENTITY_RECOVERY_MANIFEST_V1"
SOURCE_CONTRACT = "V13_V8_JQUANTS_IDENTITY_RECOVERY_DESIGN"
SOURCE_COMMIT = "7565ca723c76801d74d8d319d65d280a689b3cfa"
SOURCE_BLOB = "f46ea0c304b0bbd2d230b9850acba9eada9f6908"
ELIGIBLE_SHA256 = "37630f8f754c1a1f0f3e07f0ffc26711c83e635b5eaf24533659f37970263405"
LEGACY_OUTSIDE_V4 = frozenset("1570 4689 5020 7211 7267 8306 9432".split())
ORDER = 'SHA256(UTF8(seed + "|" + code)), then canonical code ascending by ASCII/UTF-8 byte order'
JPX_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/01.html"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def code_hash(codes: Iterable[str]) -> str:
    """V8 identity format: ordered UTF-8 codes, newline delimited and terminated."""
    return digest(("\n".join(codes) + "\n").encode("utf-8"))


def validate_calendar_provenance(observed: Any) -> None:
    """Require the complete frozen source claim; no provider substitution."""
    if not isinstance(observed, dict) or observed != dict(CALENDAR_PROVENANCE):
        raise ValueError("CALENDAR_PROVENANCE_MISMATCH")


def _git_blob_sha1(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def validate_generated_calendar_result(raw: bytes) -> None:
    """Bind the published safe result to the consumed one-shot generation."""
    if _git_blob_sha1(raw) != MASTER_CALENDAR_SAFE_RESULT_BLOB:
        raise ValueError("CALENDAR_RESULT_BLOB_MISMATCH")
    result = json.loads(raw)
    if not isinstance(result, dict) or set(result) != {
        "schema", "status", "failure_class", "evidence_origin",
        "point_of_use_authorization_issue", "powershell51_remediation_issue",
        "execution_sha", "gate_consumed", "result_present", "safe_receipt_present",
        "source_identity", "coverage_start", "coverage_end", "calendar_sha256",
        "session_count", "anchor_2020_10_01", "anchor_2020_10_02", "completed_utc",
        "generation_authorization_reusable", "selected500_public_datalock_authorized",
        "model_fit_authorized", "backtest_authorized", "a_to_q_authorized",
        "real_trading_authorized",
    }:
        raise ValueError("CALENDAR_RESULT_SCHEMA_MISMATCH")
    expected = {
        "schema": "V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT_V1",
        "status": "PASS", "failure_class": "NONE",
        "evidence_origin": "HUMAN_RETURNED_DIRECT_WINDOWS_SAFE_OUTPUT",
        "point_of_use_authorization_issue": 90, "powershell51_remediation_issue": 91,
        "execution_sha": "d71a8401c8681f02725b2c4933acb169a64e41e3",
        "gate_consumed": True, "result_present": True, "safe_receipt_present": True,
        "source_identity": V13_MASTER_CALENDAR_SOURCE_IDENTITY,
        "coverage_start": START.isoformat(), "coverage_end": END.isoformat(),
        "calendar_sha256": MASTER_CALENDAR_SHA256,
        "session_count": MASTER_CALENDAR_SESSION_COUNT,
        "anchor_2020_10_01": "INELIGIBLE", "anchor_2020_10_02": "ELIGIBLE",
        "generation_authorization_reusable": False,
        "selected500_public_datalock_authorized": False,
        "model_fit_authorized": False, "backtest_authorized": False,
        "a_to_q_authorized": False, "real_trading_authorized": False,
    }
    if any(type(result[k]) is not type(v) or result[k] != v for k, v in expected.items()):
        raise ValueError("CALENDAR_RESULT_STATUS_MISMATCH")
    try:
        datetime.fromisoformat(result["completed_utc"].replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("CALENDAR_RESULT_COMPLETION_MISMATCH") from exc


def validate_generated_calendar(raw: bytes, supplied_sha256: str) -> tuple[tuple[date, ...], dict[str, Any]]:
    if supplied_sha256 != MASTER_CALENDAR_SHA256 or digest(raw) != MASTER_CALENDAR_SHA256:
        raise ValueError("CALENDAR_LOCK_MISMATCH")
    sessions, manifest = parse_canonical_calendar(RawLock.from_bytes(raw))
    validate_calendar_anchors(sessions)
    if (len(sessions) != MASTER_CALENDAR_SESSION_COUNT
            or sessions[0].year != START.year or sessions[-1].year != END.year):
        raise ValueError("CALENDAR_SESSION_COUNT_OR_SPAN_MISMATCH")
    return sessions, manifest


def _validate_wheel_source_bytes(
    wheel: bytes, installed_sources: dict[str, bytes],
    expected_wheel_sha256: str, expected_blobs: dict[str, str],
) -> None:
    """Pure V10A-style wheel SHA, unique ZIP entry, and Git-blob binding."""
    if digest(wheel) != expected_wheel_sha256 or set(installed_sources) != set(expected_blobs):
        raise ValueError("CALENDAR_SOURCE_MISMATCH")
    try:
        with zipfile.ZipFile(BytesIO(wheel)) as archive:
            for name, expected_blob in expected_blobs.items():
                matches = [info for info in archive.infolist() if info.orig_filename == name]
                if len(matches) != 1:
                    raise ValueError("CALENDAR_SOURCE_MISMATCH")
                entry = archive.read(matches[0])
                if entry != installed_sources[name] or _git_blob_sha1(entry) != expected_blob:
                    raise ValueError("CALENDAR_SOURCE_MISMATCH")
    except (OSError, RuntimeError, zipfile.BadZipFile, KeyError, TypeError,
            ValueError, AttributeError, UnicodeError) as exc:
        raise ValueError("CALENDAR_SOURCE_MISMATCH") from exc


def validate_calendar_release_artifact(wheel: bytes, installed_sources: dict[str, bytes],
                                       observed_provenance: Any) -> None:
    """Offline source check to run before any later authorized calendar creation."""
    validate_calendar_provenance(observed_provenance)
    expected = dict(CALENDAR_PROVENANCE)
    _validate_wheel_source_bytes(wheel, installed_sources,
                                 expected["official_pypi_wheel_sha256"], {
                                     expected["jpx_source_file"]: expected["jpx_source_blob"],
                                     expected["holiday_source_file"]: expected["holiday_source_blob"],
                                 })


def serialize_calendar(sessions: Iterable[date]) -> bytes:
    """Canonical V13 RawLock payload, without acquiring any sessions."""
    ordered = tuple(sessions)
    if (not ordered or any(type(day) is not date or not START <= day <= END for day in ordered)
            or any(left >= right for left, right in zip(ordered, ordered[1:]))):
        raise ValueError("CALENDAR_ORDER_OR_RANGE_MISMATCH")
    return ("\n".join(day.isoformat() for day in ordered) + "\n").encode("utf-8")


def serialize_calendar_schedule(schedule: Any) -> bytes:
    """Port V10A emitted-label and market-close checks for a supplied schedule."""
    import pandas as pd

    if not isinstance(schedule, pd.DataFrame) or "market_close" not in schedule.columns:
        raise ValueError("CALENDAR_SCHEDULE_MISMATCH")
    labels: list[date] = []
    for value in schedule.index:
        try:
            label = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("CALENDAR_SCHEDULE_MISMATCH") from exc
        if (pd.isna(label) or label.tzinfo is not None
                or any((label.hour, label.minute, label.second,
                        label.microsecond, label.nanosecond))):
            raise ValueError("CALENDAR_SCHEDULE_MISMATCH")
        labels.append(label.date())
    if any(left >= right for left, right in zip(labels, labels[1:])):
        raise ValueError("CALENDAR_SCHEDULE_MISMATCH")
    for value in schedule["market_close"]:
        try:
            close = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("CALENDAR_SCHEDULE_MISMATCH") from exc
        if pd.isna(close) or close.tzinfo is None:
            raise ValueError("CALENDAR_SCHEDULE_MISMATCH")
    ordered = tuple(labels)
    validate_calendar_anchors(ordered)
    return serialize_calendar(ordered)


def parse_canonical_calendar(lock: "RawLock") -> tuple[tuple[date, ...], dict[str, Any]]:
    """Bridge exact canonical bytes to the existing V13 parser."""
    sessions, manifest = parse_calendar(lock)
    if (serialize_calendar(sessions) != lock.raw or manifest["session_sha256"] != lock.sha256
            or digest(lock.raw) != lock.sha256):
        raise ValueError("CALENDAR_CANONICAL_BYTES_MISMATCH")
    return sessions, manifest


def validate_calendar_anchors(sessions: tuple[date, ...]) -> None:
    if date(2020, 10, 1) in sessions or date(2020, 10, 2) not in sessions:
        raise ValueError("CALENDAR_ANCHOR_MISMATCH")


def _codes(values: Iterable[str]) -> list[str]:
    result = list(values)
    if any(not isinstance(c, str) or re.fullmatch(r"[0-9A-Za-z]{4}", c) is None for c in result):
        raise ValueError("INVALID_CODE")
    result = [c.upper() for c in result]
    if len(set(result)) != len(result):
        raise ValueError("DUPLICATE_CODE")
    return result


def validate_t1_state(state: Any, *, expected_hash: str = T1_SHA256) -> tuple[str, ...]:
    if not isinstance(state, dict) or set(state) != {
        "schema", "source_schema", "source_contract", "source_commit", "source_blob",
        "eligible_count", "eligible_sha256", "t1_ticker_list_sha256", "t1_count",
        "known_definitely_acquired_prefix_count", "exclusion_disposition", "t1_membership"
    }:
        raise ValueError("T1_STATE_SCHEMA_MISMATCH")
    if (state["schema"] != "V13_JQUANTS_T1_EXCLUSION_STATE_V1"
            or state["source_schema"] != SOURCE_SCHEMA
            or state["source_contract"] != SOURCE_CONTRACT
            or state["source_commit"] != SOURCE_COMMIT
            or state["source_blob"] != SOURCE_BLOB
            or type(state["eligible_count"]) is not int or state["eligible_count"] != 3110
            or state["eligible_sha256"] != ELIGIBLE_SHA256
            or state["t1_ticker_list_sha256"] != expected_hash
            or type(state["t1_count"]) is not int or state["t1_count"] != 300
            or type(state["known_definitely_acquired_prefix_count"]) is not int
            or state["known_definitely_acquired_prefix_count"] != 297
            or state["exclusion_disposition"] != "EXCLUDE_FULL_RECOVERED_T1_BLOCK"
            or not isinstance(state["t1_membership"], list)):
        raise ValueError("T1_STATE_PROVENANCE_MISMATCH")
    members = _codes(state["t1_membership"])
    if members != state["t1_membership"]:
        raise ValueError("T1_STATE_MEMBERSHIP_MISMATCH")
    if len(members) != 300 or code_hash(members) != expected_hash:
        raise ValueError("T1_STATE_MEMBERSHIP_MISMATCH")
    return tuple(members)


def read_v4_codes(raw: bytes) -> tuple[str, ...]:
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    if rows.fieldnames != ["ticker", "market", "industry"]:
        raise ValueError("V4_SCHEMA_MISMATCH")
    result = _codes(row["ticker"] for row in rows)
    if len(result) != 300:
        raise ValueError("V4_COUNT_MISMATCH")
    return tuple(result)


def build_exclusions(v4: Iterable[str], t1: Iterable[str]) -> tuple[set[str], dict[str, Any]]:
    v4_codes = _codes(v4)
    t1_codes = _codes(t1)
    if len(v4_codes) != 300 or len(t1_codes) != 300:
        raise ValueError("EXCLUSION_SOURCE_COUNT_MISMATCH")
    merged = set(v4_codes) | LEGACY_OUTSIDE_V4 | set(t1_codes)
    ordered = sorted(merged)
    return merged, {"exclusion_count": len(merged), "exclusion_sha256": code_hash(ordered),
                    "v4_count": 300, "legacy_outside_v4_count": 7, "t1_count": 300,
                    "t1_sha256": code_hash(t1_codes)}


@dataclass(frozen=True)
class RawLock:
    raw: bytes
    sha256: str
    byte_count: int

    @classmethod
    def from_bytes(cls, raw: bytes) -> "RawLock":
        if not isinstance(raw, bytes):
            raise ValueError("INVALID_RAW_PAYLOAD")
        return cls(raw, digest(raw), len(raw))

    def manifest(self) -> dict[str, Any]:
        return {"raw_sha256": self.sha256, "raw_byte_count": self.byte_count}


def lock_payload(raw: bytes, destination: Path) -> RawLock:
    """Publish already available offline bytes; never use for live acquisition.

    A pending publication is ambiguous and blocks automatic reacquisition.
    A final lock is reused exactly after semantic failure.
    """
    lock = RawLock.from_bytes(raw)
    pending = destination.with_name(destination.name + ".pending")
    if destination.exists() or pending.exists():
        raise FileExistsError("RAW_LOCK_COLLISION")
    with pending.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if destination.exists():
        raise FileExistsError("RAW_LOCK_COLLISION")
    os.replace(pending, destination)
    return lock


def acquire_raw_lock(destination: Path, open_response: Callable[[], BinaryIO]) -> RawLock:
    """Stream one response into a durable attempt before it can complete.

    Only a setup failure (before a response is returned) is conclusively
    pre-complete. Once reading starts, an exception may race with the final
    response byte, so its pending evidence is retained for manual adjudication.
    """
    pending = destination.with_name(destination.name + ".pending")
    if destination.exists() or pending.exists():
        raise FileExistsError("RAW_LOCK_COLLISION")
    with pending.open("xb") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    try:
        response = open_response()
    except Exception:
        # No response object was returned, so this attempt could not
        # consume a complete payload under the transport contract.
        pending.unlink()
        raise
    with pending.open("ab") as stream:
        with closing(response):
            headers = getattr(response, "headers", None)
            length_text = headers.get("Content-Length") if headers is not None else None
            expected_length = None
            if length_text is not None:
                if not length_text.isdecimal():
                    raise ValueError("INVALID_RESPONSE_LENGTH")
                expected_length = int(length_text)
            byte_count = 0
            while True:
                chunk = response.read(64 * 1024)
                if not isinstance(chunk, bytes):
                    raise ValueError("INVALID_RESPONSE_CHUNK")
                if not chunk:
                    break
                stream.write(chunk)
                byte_count += len(chunk)
            if expected_length is not None and byte_count != expected_length:
                raise ValueError("INCOMPLETE_RESPONSE_LENGTH")
        stream.flush()
        os.fsync(stream.fileno())
    if destination.exists():
        raise FileExistsError("RAW_LOCK_COLLISION")
    os.replace(pending, destination)
    return RawLock.from_bytes(destination.read_bytes())


def existing_raw_lock(destination: Path) -> RawLock | None:
    """An unfinished publication is ambiguous even when a final file exists."""
    if destination.with_name(destination.name + ".pending").exists():
        raise ValueError("AMBIGUOUS_PENDING_RAW_LOCK")
    if not destination.exists():
        return None
    if not destination.is_file():
        raise ValueError("RAW_LOCK_NOT_FILE")
    return RawLock.from_bytes(destination.read_bytes())


def parse_jpx(lock: RawLock) -> dict[str, str]:
    """Parse locked official listed-issues XLS/XLSX or UTF-8 CSV fixture.

    Returns code to current 33-sector label. Unknown/blank sectors fail closed.
    """
    raw = lock.raw
    if raw.startswith(b"PK\x03\x04") or raw.startswith(b"\xd0\xcf\x11\xe0"):
        import pandas as pd
        frame = pd.read_excel(io.BytesIO(raw), dtype=str, engine="openpyxl" if raw.startswith(b"PK") else "xlrd")
        rows = frame.fillna("").to_dict("records")
    else:
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
    if not rows:
        raise ValueError("JPX_EMPTY")
    aliases = (("コード", "code", "ticker"),
               ("市場・商品区分", "市場・区分", "market"),
               ("33業種区分", "industry"))
    columns = []
    for candidates in aliases:
        column = next((c for c in candidates if c in rows[0]), None)
        if column is None:
            raise ValueError("JPX_SCHEMA_MISMATCH")
        columns.append(column)
    result: dict[str, str] = {}
    for row in rows:
        code, market, sector = (str(row[c]).strip() for c in columns)
        code = code.upper()
        if not (re.search(r"プライム|Prime|スタンダード|Standard", market, re.I)
                and re.search(r"内国株式|Domestic Stocks", market, re.I)):
            continue
        if re.search(r"ETF|ETP|REIT|投資信託|不動産投資信託|外国株式|Foreign|優先株|Preferred|新株|New Shares", market, re.I):
            continue
        if re.fullmatch(r"[0-9A-Z]{4}", code) is None:
            continue
        if not sector or sector in {"-", "MISSING", "nan"}:
            raise ValueError("JPX_MISSING_SECTOR")
        if code in result and result[code] != sector:
            raise ValueError("JPX_CONFLICTING_DUPLICATE")
        result[code] = sector
    if not result:
        raise ValueError("JPX_NO_ELIGIBLE_CODES")
    return result


def select_universe(eligible: dict[str, str], excluded: set[str], jpx_lock: RawLock,
                    implementation_sha: str, acquired_at_utc: str) -> tuple[list[str], dict[str, Any]]:
    from src.v13_feasibility import select_universe as frozen_select_universe
    eligible = dict(zip(_codes(eligible), eligible.values()))
    excluded = set(_codes(excluded))
    selected = frozen_select_universe(eligible, excluded, SEED)
    manifest = {"source_page": JPX_PAGE, "acquired_at_utc": acquired_at_utc,
                **jpx_lock.manifest(), "eligible_count": len(eligible),
                "eligible_sha256": code_hash(sorted(eligible)),
                "exclusion_count": len(excluded), "exclusion_sha256": code_hash(sorted(excluded)),
                "selection_seed": SEED, "ordering": ORDER, "selected_count": 500,
                "selected_sha256": digest("|".join(selected).encode("utf-8")),
                "implementation_sha": implementation_sha}
    return selected, manifest


def parse_yahoo(lock: RawLock, code: str, *, omit_close_above_high: bool = False,
                omit_provider_invalid_ohlc_ordering: bool = False) -> tuple[dict[date, dict[str, float]], dict[str, Any]]:
    """Parse a locked chart response; split factors exclude dividend adjustments."""
    if omit_close_above_high and omit_provider_invalid_ohlc_ordering:
        raise ValueError("YAHOO_OMISSION_MODE_CONFLICT")
    code = _codes([code])[0]
    # Compare the provider's JSON numbers exactly in both strict and opted-in
    # paths; normalized valid rows remain ordinary floats.
    root = json.loads(lock.raw, parse_float=Decimal)
    chart = root["chart"]
    if chart.get("error") is not None or len(chart["result"]) != 1:
        raise ValueError("YAHOO_CHART_ERROR")
    result = chart["result"][0]
    if result.get("meta", {}).get("symbol") != code + ".T":
        raise ValueError("YAHOO_SYMBOL_MISMATCH")
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    if not timestamps or any(len(quote[k]) != len(timestamps) for k in ("open", "high", "low", "close", "volume")):
        raise ValueError("YAHOO_LENGTH_MISMATCH")
    zone = ZoneInfo("Asia/Tokyo")
    observations: dict[date, dict[str, float]] = {}
    seen_days: set[date] = set()
    omitted_count = 0
    omitted_ordering_count = 0
    invalid_high_count = 0
    invalid_low_count = 0
    invalid_both_count = 0
    for i, timestamp in enumerate(timestamps):
        day = datetime.fromtimestamp(timestamp, zone).date()
        if not START <= day <= END:
            raise ValueError("YAHOO_DATE_OUT_OF_WINDOW")
        if day in seen_days:
            raise ValueError("YAHOO_DUPLICATE_SESSION")
        seen_days.add(day)
        raw_values = [quote[k][i] for k in ("open", "high", "low", "close", "volume")]
        if any(type(v) not in (float, int, Decimal) or not math.isfinite(v) or v < 0 for v in raw_values):
            raise ValueError("YAHOO_INVALID_OHLCV")
        normalized_values = tuple(map(float, raw_values))
        if not all(math.isfinite(v) for v in normalized_values) or min(normalized_values[:4]) <= 0:
            raise ValueError("YAHOO_INVALID_OHLCV")
        opening, high, low, close, volume = raw_values
        if (omit_close_above_high and close > high
                and high >= max(opening, low) and low <= min(opening, close)):
            omitted_count += 1
            continue
        high_invalid = high < max(opening, close, low)
        low_invalid = low > min(opening, close)
        if omit_provider_invalid_ohlc_ordering and (high_invalid or low_invalid):
            omitted_ordering_count += 1
            invalid_high_count += int(high_invalid)
            invalid_low_count += int(low_invalid)
            invalid_both_count += int(high_invalid and low_invalid)
            continue
        if high_invalid or low_invalid:
            raise ValueError("YAHOO_INVALID_OHLCV")
        opening, high, low, close, volume = normalized_values
        observations[day] = {"open": opening, "high": high, "low": low,
                             "close": close, "volume": volume, "traded_value": close * volume}
    split_events = result.get("events", {}).get("splits", {})
    splits: list[tuple[date, float]] = []
    for event in split_events.values():
        day = datetime.fromtimestamp(event["date"], zone).date()
        numerator, denominator = event["numerator"], event["denominator"]
        if not START <= day <= END or any(type(x) not in (int, float, Decimal) or not math.isfinite(x) or x <= 0 for x in (numerator, denominator)):
            raise ValueError("YAHOO_INVALID_SPLIT")
        splits.append((day, float(numerator) / float(denominator)))
    for day, row in observations.items():
        factor = math.prod(1 / ratio for split_day, ratio in splits if day < split_day)
        row["adj_open"] = row["open"] * factor
        row["adj_high"] = row["high"] * factor
        row["adj_low"] = row["low"] * factor
        row["adj_close"] = row["close"] * factor
    return observations, {**lock.manifest(), "observation_count": len(observations),
                          "omitted_close_above_high_count": omitted_count,
                          "omitted_provider_invalid_ohlc_ordering_count": omitted_ordering_count,
                          "provider_invalid_high_order_row_count": invalid_high_count,
                          "provider_invalid_low_order_row_count": invalid_low_count,
                          "provider_invalid_both_order_row_count": invalid_both_count,
                          "split_event_count": len(splits), "start": START.isoformat(),
                          "end_inclusive": END.isoformat(), "period2_exclusive": "2026-01-01"}


def parse_calendar(lock: RawLock) -> tuple[tuple[date, ...], dict[str, Any]]:
    """Offline ordered exchange-session list, one ISO date per line."""
    lines = lock.raw.decode("utf-8-sig").splitlines()
    if any(re.fullmatch(r"\d{4}-\d{2}-\d{2}", line) is None for line in lines):
        raise ValueError("CALENDAR_FORMAT_MISMATCH")
    sessions = tuple(date.fromisoformat(line) for line in lines)
    if not sessions or any(not START <= d <= END for d in sessions) or tuple(sorted(set(sessions))) != sessions:
        raise ValueError("CALENDAR_ORDER_OR_RANGE_MISMATCH")
    return sessions, {**lock.manifest(), "input_type": "ORDERED_EXCHANGE_SESSION_LIST",
                      "session_count": len(sessions), "session_sha256": code_hash(d.isoformat() for d in sessions),
                      "real_acquisition_scope_extension_required": False}


def session_offset(sessions: tuple[date, ...], signal: date, offset: int) -> date | None:
    if offset < 0:
        raise ValueError("NEGATIVE_OFFSET")
    try:
        position = sessions.index(signal) + offset
    except ValueError:
        return None
    return sessions[position] if position < len(sessions) else None


def retry_class(failure: str, *, complete_content_locked: bool) -> str:
    return ("PLUMBING_FAILURE_RETRIABLE" if not complete_content_locked and
            failure in {"PUBLIC_TRANSPORT", "PUBLIC_SETUP"} else "NO_RETRY_AUTHORITY")
