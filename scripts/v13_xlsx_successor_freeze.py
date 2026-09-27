"""Offline verification of the Issue #104 resolved candidate freeze.

This module reads repository artifacts only. It never opens the Phase-B
operation root or treats the candidate as an installed/current environment.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from scripts import check_current_protected_environment as current
from scripts.v10c_t0_ml_environment_contract import validate_wheel_manifest

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "V13_PROTECTED_XLSX_ENVIRONMENT_SUCCESSOR_LOCK_CANDIDATE.txt"
RECORD = ROOT / "docs/v13/V13_XLSX_SUCCESSOR_RESOLUTION_FREEZE_RECORD_CANDIDATE.json"
LOCK_SHA256 = "8be6d6ab9ab7602017d758ea828e9e27dc46342d0f27fb8ebe44565010e13aba"
MANIFEST_SHA256 = "5665dbd50d13dc445792d031db7866e4f9e8e71244ecbddbf4187464ccafa8c2"
DELTA = ["et-xmlfile==2.0.0", "openpyxl==3.1.5"]
SOURCE_CANDIDATE_SHA256 = "2df61d002a780c38a361dbd51db501bc9253766ff26007f75eab214540fb2251"
SOURCE_EVIDENCE_SHA256 = "d18b08c25a977a6b892300a268ca588e8b281ca9af9bdc0059774ddc354a0559"


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _blob(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def validate_freeze(*, lock_path: Path = LOCK, record_path: Path = RECORD) -> dict:
    authority = current.resolve_historical_v10c_authority()
    _require(authority["status"] == "PASS" and authority["package_count"] == 27,
             "CURRENT_AUTHORITY_INVALID")
    _require(authority["historical_predecessor_package_count"] == 20,
             "CURRENT_AUTHORITY_INVALID")
    lock = lock_path.read_bytes()
    if lock_path == LOCK:
        canonical = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{LOCK.name}"],
                                   capture_output=True, check=True).stdout
        worktree_blob = subprocess.run(
            ["git", "-C", str(ROOT), "hash-object", "--path", LOCK.name, "--", str(LOCK)],
            capture_output=True, check=True, text=True).stdout.strip()
        _require(worktree_blob == _blob(canonical), "CANDIDATE_WORKTREE_BLOB_MISMATCH")
        lock = canonical
    _require(_sha(lock) == LOCK_SHA256 and lock.endswith(b"\n") and b"\r" not in lock,
             "CANDIDATE_LOCK_MISMATCH")
    pins = lock.decode("ascii").splitlines()
    _require(len(pins) == 29 and len(set(pins)) == 29, "CANDIDATE_PACKAGE_COUNT")
    parsed = []
    for pin in pins:
        match = re.fullmatch(r"([a-z0-9]+(?:-[a-z0-9]+)*)==([^\s=]+)", pin)
        _require(match is not None, "CANDIDATE_PIN_INVALID")
        parsed.append((match[1], match[2]))
    _require(parsed == sorted(parsed), "CANDIDATE_ORDER_INVALID")
    packages = dict(parsed)
    _require(all(packages.get(name) == version for name, version in authority["package_map"].items()),
             "CURRENT_PIN_DRIFT")
    _require([f"{name}=={version}" for name, version in parsed
              if name not in authority["package_map"]] == DELTA,
             "SUCCESSOR_DELTA_INVALID")

    record = json.loads(record_path.read_bytes(), object_pairs_hook=_unique)
    _require(type(record) is dict, "FREEZE_RECORD_INVALID")
    expected = {
        "schema_version": "V13_XLSX_SUCCESSOR_RESOLUTION_FREEZE_RECORD_CANDIDATE_V1",
        "artifact_role": "RESOLVED_CANDIDATE_LOCK_FREEZE_NOT_CURRENT_AUTHORITY",
        "source_issue": 103, "source_gpt_result": "PASS",
        "source_gpt_reviewed_sha": "82218b13ecbe6c256d33bb35f2b270cbace9c758",
        "source_safe_result_comment_id": 5847356566,
        "source_phase_b_execution_head": "3430085b1cbb14fd2bceaf14b05db02da51c8ab0",
        "authorization_blob": "6826344839b5ba738c74e371bbccf9ab06346207",
        "authorization_consumed": True, "authorization_reusable": False,
        "source_candidate_sha256": SOURCE_CANDIDATE_SHA256,
        "source_safe_evidence_sha256": SOURCE_EVIDENCE_SHA256,
        "predecessor_lock": {
            "path": current.CURRENT_AUTHORITY_LOCK_PATH,
            "git_blob_sha1": current.CURRENT_AUTHORITY_LOCK_BLOB_SHA1,
            "sha256": current.CURRENT_AUTHORITY_LOCK_SHA256,
            "package_count": 27,
        },
        "candidate_lock": {"path": LOCK.name, "git_blob_sha1": _blob(lock),
                           "sha256": LOCK_SHA256, "package_count": 29},
        "successor_delta": DELTA, "successor_delta_package_count": 2,
        "artifact_count": 29,
        "historical_phase_b_package_index_request_count": 29,
        "historical_phase_b_wheel_download_count": 29,
        "repository_task_network_requests": 0,
        "repository_task_wheel_downloads": 0,
        "repository_task_package_installations": 0,
        "repository_task_environment_mutations": 0,
        "candidate_installed": False, "active_environment_mutated": False,
        "successor_promoted": False,
        "production_xlsx_readiness": "NOT_YET_PROVEN",
        "future_profitability_established": False,
    }
    _require(set(record) == set(expected) | {"resolved_wheels"}, "FREEZE_RECORD_KEYS_INVALID")
    for key, value in expected.items():
        _require(type(record[key]) is type(value) and record[key] == value,
                 f"FREEZE_BINDING_MISMATCH_{key.upper()}")
    wheels = validate_wheel_manifest(record["resolved_wheels"])
    _require(len(wheels) == 29 and [(w["name"], w["version"]) for w in wheels] == parsed,
             "WHEEL_PACKAGE_MISMATCH")
    manifest = "".join(f'{w["name"]}|{w["version"]}|{w["filename"]}|{w["sha256"]}\n'
                       for w in wheels).encode("ascii")
    _require(_sha(manifest) == MANIFEST_SHA256, "WHEEL_MANIFEST_MISMATCH")
    return {"status": "PASS", "candidate_package_count": 29, "artifact_count": 29,
            "current_authority_package_count": 27, "production_xlsx_readiness": "NOT_YET_PROVEN"}


if __name__ == "__main__":
    print(json.dumps(validate_freeze(), sort_keys=True))
