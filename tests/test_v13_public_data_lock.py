from __future__ import annotations

import hashlib
import io
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src import v13_public_data_lock as p
from src.v13_feasibility import select_universe as frozen_select
from scripts import v13_resolve_jquants_t1_exclusion_state as producer
from scripts import v13_public_data_lock_execute as runner


def _t1():
    return [f"{n:04d}" for n in range(1000, 1300)]


def _state(codes):
    return {"schema": "V13_JQUANTS_T1_EXCLUSION_STATE_V1",
            "source_schema": p.SOURCE_SCHEMA, "source_contract": p.SOURCE_CONTRACT,
            "source_commit": p.SOURCE_COMMIT, "source_blob": p.SOURCE_BLOB,
            "eligible_count": 3110, "eligible_sha256": p.ELIGIBLE_SHA256,
            "t1_ticker_list_sha256": p.code_hash(codes), "t1_count": 300,
            "known_definitely_acquired_prefix_count": 297,
            "exclusion_disposition": "EXCLUDE_FULL_RECOVERED_T1_BLOCK", "t1_membership": codes}


def test_t1_contract_and_exclusions():
    assert (p.SOURCE_SCHEMA, p.SOURCE_CONTRACT, p.SOURCE_COMMIT, p.SOURCE_BLOB,
            p.ELIGIBLE_SHA256, p.T1_SHA256) == (
                producer.SCHEMA, producer.CONTRACT, producer.SOURCE_COMMIT,
                producer.SOURCE_BLOB, producer.ELIGIBLE_SHA, producer.T1_SHA)
    codes = _t1()
    state = _state(codes)
    assert p.validate_t1_state(state, expected_hash=p.code_hash(codes)) == tuple(codes)
    for change in ({"schema": "V13_V8_T1_IDENTITY_STATE_V1"},
                   {"source_schema": "wrong"}, {"source_contract": "wrong"},
                   {"source_commit": "wrong"}, {"source_blob": "wrong"},
                   {"eligible_count": 3109}, {"eligible_sha256": "wrong"},
                   {"t1_count": True}, {"t1_count": 299},
                   {"t1_ticker_list_sha256": "wrong"},
                   {"known_definitely_acquired_prefix_count": 296},
                   {"exclusion_disposition": "wrong"},
                   {"t1_membership": codes[:-1] + [codes[0]]},
                   {"t1_membership": codes[:-1] + ["@BAD"]},
                   {"t1_membership": codes[::-1]},
                   {"extra": "wrong"}):
        with pytest.raises(ValueError):
            p.validate_t1_state({**state, **change}, expected_hash=p.code_hash(codes))
    with pytest.raises(ValueError):
        p.validate_t1_state({k: v for k, v in state.items() if k != "source_blob"}, expected_hash=p.code_hash(codes))
    v4 = [f"{n:04d}" for n in range(1200, 1500)]
    excluded, manifest = p.build_exclusions(v4, codes)
    assert len(excluded) == 507  # 100 T1/V4 overlap plus seven legacy codes
    assert manifest["exclusion_sha256"] == p.code_hash(sorted(excluded))
    assert set(manifest) == {"exclusion_count", "exclusion_sha256", "v4_count",
                             "legacy_outside_v4_count", "t1_count", "t1_sha256"}


def test_v4_csv_and_universe_selector(tmp_path: Path):
    v4 = b"ticker,market,industry\n" + b"".join(f"{n:04d},Prime,Sector\n".encode() for n in range(1000, 1300))
    assert len(p.read_v4_codes(v4)) == 300
    eligible = {f"{n:04d}": "Sector" for n in range(1000, 1900)}
    lock = p.lock_payload(b"synthetic jpx", tmp_path / "jpx.raw")
    chosen, manifest = p.select_universe(eligible, set(_t1()), lock, "a" * 40, "2026-09-25T00:00:00Z")
    assert chosen == frozen_select(eligible, set(_t1()), p.SEED)
    assert len(chosen) == 500 and manifest["selected_sha256"] == p.digest("|".join(chosen).encode())
    assert "selected" not in manifest and "eligible" not in manifest


def test_selector_mixed_codes_deterministic_and_numeric_compatible(monkeypatch):
    numeric = [f"{n:04d}" for n in range(1000, 1600)]
    mixed = numeric + ["130A", "130B", "1A30"]
    seed = p.SEED
    expected_numeric = sorted(numeric, key=lambda c: (hashlib.sha256((seed + "|" + c).encode()).hexdigest(), int(c)))[:500]
    assert frozen_select(numeric, [], seed) == expected_numeric
    expected_mixed = sorted(mixed, key=lambda c: (hashlib.sha256((seed + "|" + c).encode()).hexdigest(), c))[:500]
    assert frozen_select(reversed(mixed), [], seed) == frozen_select(mixed, [], seed) == expected_mixed
    assert any(code in expected_mixed for code in ("130A", "130B", "1A30"))
    assert frozen_select([c.lower() for c in mixed], [], seed) == expected_mixed
    monkeypatch.setattr("src.v13_feasibility.sha256_text", lambda value: "same")
    assert frozen_select(mixed, [], seed) == sorted(mixed)[:500]


def test_jpx_filter_sector_and_lock(tmp_path: Path):
    raw = ("コード,市場・区分,33業種区分\n"
           "1000,プライム（内国株式）,機械\n"
           "1001,Standard Domestic Stocks,Services\n"
           "1002,グロース（内国株式）,機械\n"
           "1003,Prime Foreign Stocks,機械\n"
           "100a,Prime Domestic Stocks,機械\n"
           "1005,Prime Domestic Stocks ETF,機械\n"
           "1004,Prime ETF,機械\n").encode()
    lock = p.lock_payload(raw, tmp_path / "jpx.raw")
    assert (tmp_path / "jpx.raw").read_bytes() == raw
    assert lock.sha256 == hashlib.sha256(raw).hexdigest()
    assert p.parse_jpx(lock) == {"1000": "機械", "1001": "Services", "100A": "機械"}
    with pytest.raises(FileExistsError):
        p.lock_payload(raw, tmp_path / "jpx.raw")


def test_existing_offline_jpx_workbook_fixture():
    source = Path(__file__).parent / "fixtures" / "synthetic_jpx_source_snapshot.xls"
    eligible = p.parse_jpx(p.RawLock.from_bytes(source.read_bytes()))
    assert eligible == {"ZZA1": "SYNTHETIC_SECTOR_A", "ZZB2": "SYNTHETIC_SECTOR_A",
                        "ZZC3": "SYNTHETIC_SECTOR_B", "ZZD4": "SYNTHETIC_SECTOR_B",
                        "ZZE5": "SYNTHETIC_SECTOR_C"}


def _timestamp(day):
    return int(datetime(day.year, day.month, day.day, 15, tzinfo=ZoneInfo("Asia/Tokyo")).timestamp())


def _yahoo(days, code="1000"):
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": code + ".T"}, "timestamp": [_timestamp(d) for d in days],
        "indicators": {"quote": [{"open": [100.0, 51.0], "high": [110.0, 55.0],
                                  "low": [95.0, 49.0], "close": [100.0, 50.0],
                                  "volume": [1000, 2000]}],
                       "adjclose": [{"adjclose": [40.0, 49.0]}]},
        "events": {"splits": {"one": {"date": _timestamp(days[1]), "numerator": 2,
                                      "denominator": 1}},
                   "dividends": {"one": {"date": _timestamp(days[1]), "amount": 10}}}
    }]}}


def test_yahoo_split_only_raw_execution_and_2026_rejection(tmp_path: Path):
    days = [date(2025, 12, 29), date(2025, 12, 30)]
    raw = json.dumps(_yahoo(days)).encode()
    lock = p.lock_payload(raw, tmp_path / "yahoo.raw")
    rows, manifest = p.parse_yahoo(lock, "1000")
    assert rows[days[0]]["open"] == 100.0
    assert rows[days[0]]["adj_open"] == 50.0
    assert rows[days[1]]["adj_close"] == 50.0
    assert rows[days[0]]["traded_value"] == 100000.0
    assert manifest["split_event_count"] == 1 and manifest["raw_sha256"] == p.digest(raw)
    assert "1000" not in json.dumps(manifest) and "dividends" not in json.dumps(manifest)
    bad = _yahoo([date(2025, 12, 31), date(2026, 1, 2)])
    with pytest.raises(ValueError, match="OUT_OF_WINDOW"):
        p.parse_yahoo(p.RawLock.from_bytes(json.dumps(bad).encode()), "1000")
    alpha = p.RawLock.from_bytes(json.dumps(_yahoo(days, "130A")).encode())
    alpha_rows, _ = p.parse_yahoo(alpha, "130a")
    assert len(alpha_rows) == 2


def test_yahoo_exact_close_above_high_is_missing_only_with_explicit_opt_in(tmp_path):
    days = [date(2025, 12, 29), date(2025, 12, 30)]
    payload = _yahoo(days)
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["high"][0] = 100.0
    quote["close"][0] = 101.0
    raw = json.dumps(payload).encode()
    lock = p.lock_payload(raw, tmp_path / "yahoo.raw")
    with pytest.raises(ValueError, match="YAHOO_INVALID_OHLCV"):
        p.parse_yahoo(lock, "1000")
    rows, manifest = p.parse_yahoo(lock, "1000", omit_close_above_high=True)
    assert days[0] not in rows
    assert set(rows) == {days[1]}
    assert rows[days[1]]["close"] == 50.0
    assert rows[days[1]]["adj_close"] == 50.0
    assert manifest["observation_count"] == 1
    assert manifest["omitted_close_above_high_count"] == 1
    assert manifest["omitted_provider_invalid_ohlc_ordering_count"] == 0
    assert lock.raw == raw == (tmp_path / "yahoo.raw").read_bytes()
    assert all(row["close"] != 101.0 for row in rows.values())
    valid_lock = p.RawLock.from_bytes(json.dumps(_yahoo(days)).encode())
    strict_valid, _ = p.parse_yahoo(valid_lock, "1000")
    opted_valid, valid_manifest = p.parse_yahoo(valid_lock, "1000",
                                               omit_close_above_high=True)
    assert opted_valid == strict_valid
    assert valid_manifest["omitted_close_above_high_count"] == 0
    assert valid_manifest["omitted_provider_invalid_ohlc_ordering_count"] == 0


@pytest.mark.parametrize(("changes", "high_count", "low_count", "both_count"), [
    ({"high": 99, "low": 95}, 1, 0, 0),
    ({"high": 110, "low": 101}, 0, 1, 0),
    ({"high": 99, "low": 101}, 1, 1, 1),
])
def test_successor_ordering_invalid_rows_are_missing(changes, high_count, low_count, both_count):
    days = [date(2025, 12, 29), date(2025, 12, 30)]
    payload = _yahoo(days)
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    for field, value in changes.items():
        quote[field][0] = value
    lock = p.RawLock.from_bytes(json.dumps(payload).encode())
    with pytest.raises(ValueError, match="YAHOO_INVALID_OHLCV"):
        p.parse_yahoo(lock, "1000")
    with pytest.raises(ValueError, match="YAHOO_INVALID_OHLCV"):
        p.parse_yahoo(lock, "1000", omit_close_above_high=True)
    rows, manifest = p.parse_yahoo(lock, "1000", omit_provider_invalid_ohlc_ordering=True)
    assert set(rows) == {days[1]}
    assert manifest["omitted_close_above_high_count"] == 0
    assert manifest["omitted_provider_invalid_ohlc_ordering_count"] == 1
    assert manifest["provider_invalid_high_order_row_count"] == high_count
    assert manifest["provider_invalid_low_order_row_count"] == low_count
    assert manifest["provider_invalid_both_order_row_count"] == both_count


def test_successor_mode_conflict_and_historical_derived_equality(tmp_path):
    days = [date(2025, 12, 29), date(2025, 12, 30)]
    payload = _yahoo(days)
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["high"][0], quote["close"][0] = 100, 101
    lock = p.RawLock.from_bytes(json.dumps(payload).encode())
    with pytest.raises(ValueError, match="^YAHOO_OMISSION_MODE_CONFLICT$"):
        p.parse_yahoo(lock, "1000", omit_close_above_high=True,
                      omit_provider_invalid_ohlc_ordering=True)
    historical, old_manifest = p.parse_yahoo(lock, "1000", omit_close_above_high=True)
    successor, new_manifest = p.parse_yahoo(lock, "1000",
                                              omit_provider_invalid_ohlc_ordering=True)
    assert historical == successor
    assert old_manifest["omitted_close_above_high_count"] == 1
    assert new_manifest["omitted_close_above_high_count"] == 0
    assert new_manifest["omitted_provider_invalid_ohlc_ordering_count"] == 1
    derived = tmp_path / "price.private.json"
    old_bytes = runner._json_bytes({day.isoformat(): row for day, row in historical.items()})
    derived.write_bytes(old_bytes)
    runner._bound_json(derived, {day.isoformat(): row for day, row in successor.items()})
    assert derived.read_bytes() == old_bytes


@pytest.mark.parametrize("value", [None, "bad", -1, 0, float("inf")])
def test_successor_preserves_numeric_failures(value):
    payload = _yahoo([date(2025, 12, 29), date(2025, 12, 30)])
    payload["chart"]["result"][0]["indicators"]["quote"][0]["high"][0] = value
    with pytest.raises(ValueError, match="YAHOO_INVALID_OHLCV"):
        p.parse_yahoo(p.RawLock.from_bytes(json.dumps(payload).encode()), "1000",
                      omit_provider_invalid_ohlc_ordering=True)


def test_successor_exact_decimal_and_invalid_split_fail_closed():
    days = [date(2025, 12, 29), date(2025, 12, 30)]
    raw = json.dumps(_yahoo(days), separators=(",", ":")).encode()
    raw = raw.replace(b'"high":[110.0,55.0]', b'"high":[100.000000000000000000,55.0]')
    raw = raw.replace(b'"close":[100.0,50.0]', b'"close":[100.000000000000000001,50.0]')
    rows, manifest = p.parse_yahoo(p.RawLock.from_bytes(raw), "1000",
                                    omit_provider_invalid_ohlc_ordering=True)
    assert set(rows) == {days[1]}
    assert manifest["provider_invalid_high_order_row_count"] == 1
    payload = _yahoo(days)
    payload["chart"]["result"][0]["indicators"]["quote"][0]["high"][0] = 99
    payload["chart"]["result"][0]["events"]["splits"]["one"]["denominator"] = 0
    with pytest.raises(ValueError, match="YAHOO_INVALID_SPLIT"):
        p.parse_yahoo(p.RawLock.from_bytes(json.dumps(payload).encode()), "1000",
                      omit_provider_invalid_ohlc_ordering=True)
    raw = json.dumps(_yahoo(days), separators=(",", ":")).encode()
    raw = raw.replace(b'"high":[110.0,55.0]', b'"high":[1e400,55.0]')
    with pytest.raises(ValueError, match="YAHOO_INVALID_OHLCV"):
        p.parse_yahoo(p.RawLock.from_bytes(raw), "1000",
                      omit_provider_invalid_ohlc_ordering=True)


def test_successor_structure_and_duplicate_fail_closed():
    days = [date(2025, 12, 29), date(2025, 12, 30)]
    payload = _yahoo(days)
    payload["chart"]["result"][0]["timestamp"][1] = _timestamp(days[0])
    with pytest.raises(ValueError, match="YAHOO_DUPLICATE_SESSION"):
        p.parse_yahoo(p.RawLock.from_bytes(json.dumps(payload).encode()), "1000",
                      omit_provider_invalid_ohlc_ordering=True)
    payload = _yahoo(days)
    payload["chart"]["result"][0]["meta"]["symbol"] = "OTHER.T"
    with pytest.raises(ValueError, match="YAHOO_SYMBOL_MISMATCH"):
        p.parse_yahoo(p.RawLock.from_bytes(json.dumps(payload).encode()), "1000",
                      omit_provider_invalid_ohlc_ordering=True)
    payload = _yahoo(days)
    payload["chart"]["result"][0]["indicators"]["quote"][0]["high"].pop()
    with pytest.raises(ValueError, match="YAHOO_LENGTH_MISMATCH"):
        p.parse_yahoo(p.RawLock.from_bytes(json.dumps(payload).encode()), "1000",
                      omit_provider_invalid_ohlc_ordering=True)
    payload = _yahoo(days)
    payload["chart"]["error"] = "synthetic"
    with pytest.raises(ValueError, match="YAHOO_CHART_ERROR"):
        p.parse_yahoo(p.RawLock.from_bytes(json.dumps(payload).encode()), "1000",
                      omit_provider_invalid_ohlc_ordering=True)


@pytest.mark.parametrize("changes", [
    {"open": 120.0, "high": 100.0, "close": 101.0},
    {"low": 105.0, "high": 100.0, "close": 101.0},
    {"close": 0.0},
    {"volume": -1},
    {"high": 99.0, "close": 100.0, "low": 101.0},
])
def test_yahoo_other_invalid_shapes_stay_strict(changes):
    payload = _yahoo([date(2025, 12, 29), date(2025, 12, 30)])
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    for field, value in changes.items():
        quote[field][0] = value
    with pytest.raises(ValueError, match="YAHOO_INVALID_OHLCV"):
        p.parse_yahoo(p.RawLock.from_bytes(json.dumps(payload).encode()), "1000",
                      omit_close_above_high=True)


def test_yahoo_exact_decimal_comparison_and_duplicate_omitted_session():
    days = [date(2025, 12, 29), date(2025, 12, 30)]
    raw = json.dumps(_yahoo(days), separators=(",", ":")).encode()
    raw = raw.replace(b'"high":[110.0,55.0]', b'"high":[100.000000000000000000,55.0]')
    raw = raw.replace(b'"close":[100.0,50.0]', b'"close":[100.000000000000000001,50.0]')
    with pytest.raises(ValueError, match="YAHOO_INVALID_OHLCV"):
        p.parse_yahoo(p.RawLock.from_bytes(raw), "1000")
    rows, manifest = p.parse_yahoo(p.RawLock.from_bytes(raw), "1000",
                                   omit_close_above_high=True)
    assert set(rows) == {days[1]}
    assert manifest["omitted_close_above_high_count"] == 1
    payload = _yahoo([days[0], days[0]])
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["high"][0] = 100.0
    quote["close"][0] = 101.0
    with pytest.raises(ValueError, match="YAHOO_DUPLICATE_SESSION"):
        p.parse_yahoo(p.RawLock.from_bytes(json.dumps(payload).encode()), "1000",
                      omit_close_above_high=True)


def test_calendar_exact_offsets_and_retry(tmp_path: Path):
    raw = b"2025-12-26\n2025-12-29\n2025-12-30\n2025-12-31\n"
    sessions, manifest = p.parse_calendar(p.lock_payload(raw, tmp_path / "calendar.raw"))
    assert p.session_offset(sessions, date(2025, 12, 26), 1) == date(2025, 12, 29)
    assert p.session_offset(sessions, date(2025, 12, 26), 3) == date(2025, 12, 31)
    assert p.session_offset(sessions, date(2025, 12, 29), 3) is None
    assert manifest["real_acquisition_scope_extension_required"] is False
    assert p.retry_class("PUBLIC_TRANSPORT", complete_content_locked=False) == "PLUMBING_FAILURE_RETRIABLE"
    for failure, locked in (("PUBLIC_TRANSPORT", True), ("SEMANTIC", False), ("MODEL", False)):
        assert p.retry_class(failure, complete_content_locked=locked) == "NO_RETRY_AUTHORITY"


def test_frozen_calendar_result_binding(monkeypatch):
    result_path = Path(__file__).resolve().parents[1] / "docs/v13/V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT.json"
    raw = result_path.read_bytes()
    assert p._git_blob_sha1(raw) == p.MASTER_CALENDAR_SAFE_RESULT_BLOB
    p.validate_generated_calendar_result(raw)
    result = json.loads(raw)
    for key, value in (("schema", "bad"), ("status", "FAIL"), ("gate_consumed", False),
                       ("source_identity", "OTHER"), ("session_count", 2686),
                       ("anchor_2020_10_01", "ELIGIBLE"),
                       ("calendar_sha256", "0" * 64)):
        altered = {**result, key: value}
        with pytest.raises(ValueError):
            p.validate_generated_calendar_result(json.dumps(altered).encode())
    with pytest.raises(ValueError, match="CALENDAR_LOCK_MISMATCH"):
        p.validate_generated_calendar(b"synthetic", "0" * 64)
    monkeypatch.setattr(p, "digest", lambda raw: p.MASTER_CALENDAR_SHA256)
    monkeypatch.setattr(p, "parse_canonical_calendar",
                        lambda lock: ((date(2020, 10, 2),), {}))
    with pytest.raises(ValueError, match="COUNT_OR_SPAN"):
        p.validate_generated_calendar(b"synthetic", p.MASTER_CALENDAR_SHA256)
    monkeypatch.setattr(p, "parse_canonical_calendar",
                        lambda lock: ((date(2020, 10, 1), date(2020, 10, 2)), {}))
    with pytest.raises(ValueError, match="ANCHOR"):
        p.validate_generated_calendar(b"synthetic", p.MASTER_CALENDAR_SHA256)


def _synthetic_run(tmp_path, monkeypatch):
    calendar = tmp_path / "calendar.txt"
    calendar.write_text("synthetic")
    t1 = tmp_path / "t1.json"
    t1.write_text("{}")
    v4 = tmp_path / "v4.csv"
    v4.write_text("synthetic")
    monkeypatch.setattr(p, "validate_generated_calendar",
                        lambda raw, sha: ((date(2025, 12, 30),),
                                          {"session_count": 2687, "session_sha256": p.MASTER_CALENDAR_SHA256,
                                           "real_acquisition_scope_extension_required": False}))
    monkeypatch.setattr(p, "validate_t1_state", lambda state: tuple(_t1()))
    monkeypatch.setattr(p, "read_v4_codes", lambda raw: tuple(f"{n:04d}" for n in range(1200, 1500)))
    output = tmp_path / "output"
    args = {"t1_state": t1, "v4_csv": v4, "calendar_lock": calendar,
            "calendar_sha256": p.MASTER_CALENDAR_SHA256, "output": output,
            "implementation_sha": "a" * 40}
    counts = {}
    fail_code = [None]
    semantic_code = [None]
    def fetch(url):
        counts[url] = counts.get(url, 0) + 1
        if "jpx.co.jp" in url:
            if url == p.JPX_PAGE:
                return io.BytesIO(b'<a href="/data_j.xls">listed</a>')
            return io.BytesIO(("コード,市場・区分,33業種区分\n" +
                    "".join(f"{n:04d},Prime Domestic Stocks,Sector\n" for n in range(2000, 2600))).encode())
        code = url.split("/chart/")[1].split(".T")[0]
        if code == fail_code[0]:
            raise OSError("synthetic transport")
        if code == semantic_code[0]:
            return io.BytesIO(b'{"chart":{"error":"synthetic","result":[]}}')
        timestamp = _timestamp(date(2025, 12, 30))
        return io.BytesIO(json.dumps({"chart": {"error": None, "result": [{
            "meta": {"symbol": code + ".T"}, "timestamp": [timestamp],
            "indicators": {"quote": [{"open": [10], "high": [11],
                                      "low": [9], "close": [10], "volume": [100]}]}
        }]}}).encode())
    return args, output, counts, fail_code, semantic_code, fetch


@pytest.mark.parametrize("filename", ["data_j.xls", "data_j.xlsx"])
def test_official_jpx_listed_issue_filename_forms(filename):
    href = f"/markets/statistics-equities/misc/{filename}"
    links = runner._OfficialLinks()
    links.feed(f'<a href="{href}">listed</a>')
    assert links.links == [href]


@pytest.mark.parametrize("filename", [
    "data_j.xlsm", "data_j.csv", "data_j.xlsx.bak", "other_data_j.xlsx",
    "unrelated.xlsx", "data_j.xls-extra",
])
def test_official_jpx_listed_issue_lookalikes_rejected(filename):
    links = runner._OfficialLinks()
    links.feed(f'<a href="/markets/statistics-equities/misc/{filename}">listed</a>')
    assert links.links == []


@pytest.mark.parametrize("hrefs", [
    [],
    ["/first/data_j.xlsx", "/second/data_j.xls"],
    ["https://example.com/data_j.xlsx"],
    ["https://www.jpx.co.jp.evil.example/data_j.xlsx"],
])
def test_jpx_candidate_ambiguity_and_exact_host_fail_closed(tmp_path, monkeypatch, hrefs):
    args, _, counts, _, _, _ = _synthetic_run(tmp_path, monkeypatch)
    page = "".join(f'<a href="{href}">listed</a>' for href in hrefs).encode()

    def fetch(url):
        counts[url] = counts.get(url, 0) + 1
        assert url == p.JPX_PAGE
        return io.BytesIO(page)

    with pytest.raises(ValueError, match="JPX_SOURCE_AMBIGUOUS"):
        runner.execute(**args, fetch=fetch)
    assert counts == {p.JPX_PAGE: 1}


def test_locked_xlsx_page_resume_does_not_refetch_page(tmp_path, monkeypatch):
    args, output, counts, _, _, _ = _synthetic_run(tmp_path, monkeypatch)
    href = "/markets/statistics-equities/misc/data_j.xlsx"
    listed_url = "https://www.jpx.co.jp" + href
    page = f'<a href="{href}">listed</a>'.encode()

    def first_fetch(url):
        counts[url] = counts.get(url, 0) + 1
        if url == p.JPX_PAGE:
            return io.BytesIO(page)
        assert url == listed_url
        raise OSError("synthetic listed issues transport")

    with pytest.raises(OSError, match="synthetic listed issues transport"):
        runner.execute(**args, fetch=first_fetch)
    assert (output / "jpx-page.raw").read_bytes() == page
    assert counts == {p.JPX_PAGE: 1, listed_url: 1}

    def resumed_fetch(url):
        assert url == listed_url
        counts[url] += 1
        return io.BytesIO(b"invalid synthetic workbook")

    with pytest.raises(ValueError):
        runner.execute(**args, fetch=resumed_fetch)
    assert counts == {p.JPX_PAGE: 1, listed_url: 2}
    assert (output / "jpx-page.raw").read_bytes() == page


def test_resume_only_fetches_missing_payloads(tmp_path, monkeypatch, capsys):
    args, output, counts, fail_code, _, fetch = _synthetic_run(tmp_path, monkeypatch)
    selected = frozen_select({f"{n:04d}": "Sector" for n in range(2000, 2600)},
                             set(_t1()) | set(f"{n:04d}" for n in range(1200, 1500))
                             | p.LEGACY_OUTSIDE_V4, p.SEED)
    fail_code[0] = selected[4]
    with pytest.raises(OSError):
        runner.execute(**args, fetch=fetch)
    before = dict(counts)
    assert len(before) == 7  # two JPX and five Yahoo attempts
    fail_code[0] = None
    safe = runner.execute(**args, fetch=fetch)
    assert safe["yahoo_payload_count"] == 500
    for url, count in before.items():
        assert counts[url] == (count + 1 if selected[4] in url else count)
    assert counts[p.JPX_PAGE] == 1
    assert sum(counts.values()) == 502 + 1
    assert "selected" not in safe and "t1_membership" not in json.dumps(safe)
    assert selected[0] not in json.dumps(safe)
    assert capsys.readouterr().out == ""
    previous = dict(counts)
    runner.execute(**args, fetch=fetch)
    assert counts == previous
    missing = output / f"price-{selected[0]}.private.json"
    missing.unlink()
    runner.execute(**args, fetch=fetch)
    assert missing.exists() and counts == previous
    selected_state = output / "selected.private.json"
    selected_state.write_text(json.dumps({"selected": selected[::-1]}))
    with pytest.raises(ValueError, match="DURABLE_STATE_MISMATCH"):
        runner.execute(**args, fetch=fetch)
    assert counts == previous


def test_runner_successor_aggregates_ordering_omissions_without_cap(tmp_path, monkeypatch):
    args, output, _, _, _, base_fetch = _synthetic_run(tmp_path, monkeypatch)
    selected = frozen_select({f"{n:04d}": "Sector" for n in range(2000, 2600)},
                             set(_t1()) | set(f"{n:04d}" for n in range(1200, 1500))
                             | p.LEGACY_OUTSIDE_V4, p.SEED)
    invalid_codes = {selected[0]: {"close": 12},
                     selected[1]: {"high": 13, "low": 12},
                     selected[2]: {"high": 9, "low": 12}}
    locked_payloads = {}

    def fetch(url):
        raw = base_fetch(url).read()
        if "/chart/" in url:
            code = url.split("/chart/")[1].split(".T")[0]
            if code in invalid_codes:
                payload = json.loads(raw)
                result = payload["chart"]["result"][0]
                quote = result["indicators"]["quote"][0]
                for field, value in invalid_codes[code].items():
                    quote[field][0] = value
                if code == selected[0]:
                    result["timestamp"].append(_timestamp(date(2025, 12, 29)))
                    for field, value in (("open", 10), ("high", 11), ("low", 9),
                                         ("close", 12), ("volume", 100)):
                        quote[field].append(value)
                raw = json.dumps(payload).encode()
                locked_payloads[code] = raw
        return io.BytesIO(raw)

    safe = runner.execute(**args, fetch=fetch)
    assert safe["schema"] == "V13_PUBLIC_DATALOCK_SAFE_MANIFEST_V2"
    assert safe["yahoo_payload_count"] == 500
    assert safe["provider_invalid_ohlc_ordering_omitted_count"] == 4
    assert safe["provider_invalid_ohlc_ordering_payload_count"] == 3
    assert safe["provider_invalid_high_order_row_count"] == 3
    assert safe["provider_invalid_low_order_row_count"] == 2
    assert safe["provider_invalid_both_order_row_count"] == 1
    assert (safe["model_fits"], safe["backtests"], safe["outcome_calculations"]) == (0, 0, 0)
    for code in selected[:3]:
        assert code not in json.dumps(safe)
        assert json.loads((output / f"price-{code}.private.json").read_text()) == {}
    assert (output / f"yahoo-{selected[0]}.raw").read_bytes() == locked_payloads[selected[0]]
    assert len(json.loads((output / f"price-{selected[3]}.private.json").read_text())) == 1
    before = {code: (output / f"yahoo-{code}.raw").read_bytes() for code in selected[:3]}
    runner.execute(**args, fetch=lambda _url: (_ for _ in ()).throw(AssertionError("refetch")))
    assert all((output / f"yahoo-{code}.raw").read_bytes() == raw for code, raw in before.items())
    price = output / f"price-{selected[0]}.private.json"
    price.write_text('{"tampered":true}')
    with pytest.raises(ValueError, match="DURABLE_STATE_MISMATCH"):
        runner.execute(**args, fetch=lambda _url: (_ for _ in ()).throw(AssertionError("refetch")))
    assert price.read_text() == '{"tampered":true}'


def test_semantic_failure_and_pending_fail_closed(tmp_path, monkeypatch):
    args, output, counts, _, semantic_code, fetch = _synthetic_run(tmp_path, monkeypatch)
    selected = frozen_select({f"{n:04d}": "Sector" for n in range(2000, 2600)},
                             set(_t1()) | set(f"{n:04d}" for n in range(1200, 1500))
                             | p.LEGACY_OUTSIDE_V4, p.SEED)
    semantic_code[0] = selected[0]
    with pytest.raises(ValueError, match="YAHOO_CHART_ERROR"):
        runner.execute(**args, fetch=fetch)
    semantic_code[0] = None
    previous = dict(counts)
    with pytest.raises(ValueError, match="YAHOO_CHART_ERROR"):
        runner.execute(**args, fetch=fetch)
    assert counts == previous
    raw = output / f"yahoo-{selected[0]}.raw"
    pending = raw.with_name(raw.name + ".pending")
    pending.write_bytes(b"ambiguous")
    with pytest.raises(ValueError, match="AMBIGUOUS_PENDING_RAW_LOCK"):
        runner.execute(**args, fetch=fetch)
    assert pending.exists() and counts == previous


def test_runner_rejects_calendar_drift_before_network(tmp_path, monkeypatch):
    args, output, counts, _, _, fetch = _synthetic_run(tmp_path, monkeypatch)
    def validate(raw, sha):
        if sha != p.MASTER_CALENDAR_SHA256:
            raise ValueError("CALENDAR_LOCK_MISMATCH")
        return ((), {"session_count": 2687})
    monkeypatch.setattr(p, "validate_generated_calendar", validate)
    result = tmp_path / "wrong-result.json"
    original = Path(__file__).resolve().parents[1] / "docs/v13/V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT.json"
    changed = json.loads(original.read_bytes())
    changed["source_identity"] = "OTHER"
    result.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="CALENDAR_RESULT_BLOB_MISMATCH"):
        runner.execute(**args, fetch=fetch, safe_result_path=result)
    with pytest.raises(ValueError, match="CALENDAR_LOCK_MISMATCH"):
        runner.execute(**{**args, "calendar_sha256": "0" * 64}, fetch=fetch)
    assert not output.exists() and counts == {}


def test_empty_complete_response_is_locked(tmp_path: Path):
    destination = tmp_path / "empty.raw"
    lock = p.lock_payload(b"", destination)
    assert lock.byte_count == 0 and destination.exists()
    assert p.existing_raw_lock(destination).raw == b""
    with pytest.raises(FileExistsError):
        p.lock_payload(b"later", destination)


def test_streamed_complete_response_has_pending_before_final_publish(tmp_path, monkeypatch):
    destination = tmp_path / "stream.raw"
    pending = tmp_path / "stream.raw.pending"
    payload = b"synthetic response" * 5000
    opens = []

    class Response(io.BytesIO):
        def read(self, size=-1):
            assert pending.exists()
            return super().read(size)

    def fetch(_url):
        assert pending.exists() and pending.read_bytes() == b""
        opens.append(1)
        return Response(payload)

    real_replace = p.os.replace

    def interrupted_publish(source, target):
        assert source == pending and target == destination
        assert pending.read_bytes() == payload
        raise OSError("synthetic interruption after EOF")

    monkeypatch.setattr(p.os, "replace", interrupted_publish)
    with pytest.raises(OSError, match="synthetic interruption"):
        runner._raw("synthetic", destination, fetch)
    assert pending.read_bytes() == payload and not destination.exists()
    monkeypatch.setattr(p.os, "replace", real_replace)
    with pytest.raises(ValueError, match="AMBIGUOUS_PENDING_RAW_LOCK"):
        runner._raw("synthetic", destination, fetch)
    assert len(opens) == 1


def test_streamed_setup_failure_retries_and_final_lock_precedes_parse(tmp_path):
    destination = tmp_path / "stream.raw"
    attempts = []

    def setup_failure(_url):
        attempts.append(1)
        raise OSError("synthetic pre-response setup failure")

    with pytest.raises(OSError, match="pre-response"):
        runner._raw("synthetic", destination, setup_failure)
    assert not destination.exists()
    assert not (tmp_path / "stream.raw.pending").exists()

    def complete(_url):
        attempts.append(1)
        return io.BytesIO(b"semantically invalid")

    lock = runner._raw("synthetic", destination, complete)
    assert destination.read_bytes() == lock.raw == b"semantically invalid"
    with pytest.raises(ValueError):
        p.parse_yahoo(lock, "1000")
    assert runner._raw("synthetic", destination, setup_failure).raw == lock.raw
    assert len(attempts) == 2


def test_stream_exception_retains_ambiguous_attempt(tmp_path):
    destination = tmp_path / "interrupted.raw"
    pending = tmp_path / "interrupted.raw.pending"
    opens = []

    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise OSError("synthetic stream interruption")
            return super().read(4)

    def fetch(_url):
        opens.append(1)
        assert pending.exists()
        return Interrupted(b"synthetic payload")

    with pytest.raises(OSError, match="stream interruption"):
        runner._raw("synthetic", destination, fetch)
    assert pending.read_bytes() == b"synt"
    with pytest.raises(ValueError, match="AMBIGUOUS_PENDING_RAW_LOCK"):
        runner._raw("synthetic", destination, fetch)
    assert len(opens) == 1


def test_short_response_length_never_publishes_final_lock(tmp_path):
    destination = tmp_path / "short.raw"

    class ShortResponse(io.BytesIO):
        headers = {"Content-Length": "10"}

    with pytest.raises(ValueError, match="INCOMPLETE_RESPONSE_LENGTH"):
        runner._raw("synthetic", destination, lambda _url: ShortResponse(b"short"))
    assert not destination.exists()
    assert (tmp_path / "short.raw.pending").read_bytes() == b"short"
