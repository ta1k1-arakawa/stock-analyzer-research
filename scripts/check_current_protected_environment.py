"""Resolve and validate the current protected real-execution environment.

This checker is deliberately separate from ``check_real_execution_env.py``.
The latter remains the historical V9_014 generic 15-package checker and is
kept independently testable for provenance and regression purposes.  This
module retains the reviewed V10C 27-package chain as predecessor provenance
and resolves the V13 29-package final promotion as current authority.

The checker is no-network, no-private-data, and read-only. It launches an
isolated child through the exact canonical interpreter; that child observes
installed package identity through ``importlib.metadata`` and runs the
reviewed synthetic PDF and production XLSX operational probes. It never installs packages, opens
research payloads, or consumes a gate. A missing, ambiguous, stale, or
contradictory authority fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_STATE_PATH = REPO_ROOT / "PROJECT_STATE.md"
CURRENT_LOCK_PATH = REPO_ROOT / "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR_LOCK.txt"
FINAL_FREEZE_RECORD_PATH = (
    REPO_ROOT / "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR_FINAL_FREEZE_RECORD_CANDIDATE.json"
)
FINAL_FREEZE_EVIDENCE_PATH = (
    REPO_ROOT / "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR_FINAL_FREEZE_SAFE_EVIDENCE.json"
)
RESOLUTION_PROMOTION_PATH = (
    REPO_ROOT / "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR_RESOLUTION_PROMOTION.json"
)
V13_FINAL_LOCK_PATH = REPO_ROOT / "V13_PROTECTED_XLSX_ENVIRONMENT_SUCCESSOR_LOCK.txt"
V13_CANDIDATE_LOCK_PATH = REPO_ROOT / "V13_PROTECTED_XLSX_ENVIRONMENT_SUCCESSOR_LOCK_CANDIDATE.txt"
V13_PROMOTION_PATH = REPO_ROOT / "docs/v13/V13_XLSX_SUCCESSOR_FINAL_CURRENT_AUTHORITY_PROMOTION.json"
V13_SAFE_RESULT_PATH = REPO_ROOT / "docs/v13/V13_XLSX_SUCCESSOR_ACTIVE_ENV_MUTATION_SAFE_RESULT.json"
V13_AUTHORIZATION_PATH = REPO_ROOT / "docs/v13/V13_XLSX_SUCCESSOR_ACTIVE_ENV_MUTATION_AUTHORIZATION.json"
V13_REVIEWED_SHA = "2adbb7d6d182b62d97ab59f2af3d7a13776f48ee"
V13_REVIEWED_PARENT_SHA = "3b351fe13ab8b81bb6f8b295b3d24f44c4bd693c"
V13_LOCK_BLOB_SHA1 = "dfe440dc6398dc3b1a2dd31c81047e4209e61536"
V13_LOCK_SHA256 = "8be6d6ab9ab7602017d758ea828e9e27dc46342d0f27fb8ebe44565010e13aba"
V13_PROMOTION_BLOB_SHA1 = "1f68d9c819ce1b7daab59babb8929885de622ef9"
V13_SAFE_RESULT_BLOB_SHA1 = "a90b3e3e2738c4c304755c16221a96e48336010c"
V13_AUTHORIZATION_BLOB_SHA1 = "ff00b49346153dfe7d506432d8358713bbd7fa87"
V13_DELTA = ["et-xmlfile==2.0.0", "openpyxl==3.1.5"]
REVIEWED_PROBE_BLOBS = {
    "scripts/v13_xlsx_readiness.py": "e7c1da8c15f4c74dbdccd2686219653d66b6c2ab",
    "src/v13_public_data_lock.py": "06b634e4f5f95b167a7b9ed595ae38544d8ddb8c",
    "scripts/v9_014_pdf_env_successor.py": "0f60c6ad8519f89c51984231c6248d28e785271e",
    "tests/fixtures/v9_014_synthetic_pdf_env_probe.pdf": "96b5c60b9b8b63eeb3241f04f184edae7f14ccbf",
}

CURRENT_AUTHORITY_REVIEWED_SHA = "92cc4a964af798f9543155e32eb83a12e7352151"
CURRENT_AUTHORITY_REVIEWED_PARENT_SHA = "d574015cb148f9e172d73b2ad74b5f99e02ff5ea"
CURRENT_AUTHORITY_STUDY = "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR"
CURRENT_AUTHORITY_STATE = "CANONICAL_FROZEN"
CURRENT_AUTHORITY_LOCK_BLOB_SHA1 = "13636e58fbe40071be04cbfa57c3990c1d8ff2e0"
CURRENT_AUTHORITY_LOCK_SHA256 = "f38dd4c7319465bb7e6ff429e8dff4a476d9966c744b19e50264dcc0b18e8300"
CURRENT_AUTHORITY_LOCK_PACKAGE_COUNT = 27
CURRENT_AUTHORITY_LOCK_PATH = "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR_LOCK.txt"
CURRENT_AUTHORITY_RECORD_BLOB_SHA1 = "23d2f8c5b1dc12f22aed262a918b0ba18fceeaf1"
CURRENT_AUTHORITY_EVIDENCE_BLOB_SHA1 = "bffa5180ebe2930fca5279eac76e3cba83cea855"
CURRENT_AUTHORITY_PROMOTION_BLOB_SHA1 = "b866e6d77508d6366569ee6a229587c59c3c8be2"
CURRENT_AUTHORITY_PREDECESSOR_LOCK_BLOB_SHA1 = "99395e7a5be752fb3ea92fd31be0334f38792261"
CURRENT_AUTHORITY_PREDECESSOR_LOCK_SHA256 = "eb325ac5e3417e6407400b18c8d90ca734a32e852056926e5bcd2a635e43c444"
CURRENT_AUTHORITY_PREDECESSOR_PACKAGE_COUNT = 20
CURRENT_AUTHORITY_SAFE_EVIDENCE_SHA256 = "b83d02921e571545511e477d4783ed408b8700b790d52c1f7d51d93d850d8ba3"

CANONICAL_VENV_DIR = REPO_ROOT / ".venv-real-execution"
CANONICAL_INTERPRETER = CANONICAL_VENV_DIR / "Scripts" / "python.exe"
CANONICAL_PYTHON_VERSION = (3, 12, 10)

PDF_PROBE_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "v9_014_synthetic_pdf_env_probe.pdf"
PDF_PROBE_EXPECTED_FIXTURE_SHA256 = "5eecb758a50e829af16bd42833f89a8329bfaaaa561aee209fbd2249b507b413"
PDF_PROBE_REQUIRED_PDFPLUMBER_VERSION = "0.11.10"
PDF_PROBE_EXPECTED_PAGE_COUNT = 1
PDF_PROBE_PASS = "SYNTHETIC_PDF_PROBE_PASS"
ISOLATED_CHILD_SCHEMA = "V13_CURRENT_PROTECTED_ENVIRONMENT_ISOLATED_OBSERVER_V1"
ISOLATED_CHILD_TOP_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "isolated",
        "no_user_site",
        "pythonpath_env_absent",
        "bytecode_disabled",
        "python_implementation",
        "python_version",
        "executable",
        "platform_system",
        "platform_machine",
        "sysconfig_platform",
        "packages",
        "package_observation_status",
        "package_failure",
        "pdf_probe",
        "xlsx_probe",
    }
)
ISOLATED_CHILD_PDF_KEYS = frozenset(
    {"status", "fixture_sha256", "pdfplumber_version", "page_count"}
)
ISOLATED_CHILD_XLSX_KEYS = frozenset({"status", "openpyxl_version", "et_xmlfile_version"})

_PINNED_LINE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)==(?P<version>[^\s#]+)$")
_KEY_LINE = re.compile(r"^(?P<key>[A-Z0-9_]+)=(?P<value>.*)$")

GitBlobReader = Callable[[Path, str], bytes | None]


def _git_blob_bytes(repo_root: Path, git_ref: str) -> bytes | None:
    """Read one already-present Git object; this function never fetches."""

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "blob", git_ref],
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _git_blob_sha1(blob_bytes: bytes) -> str:
    header = f"blob {len(blob_bytes)}\0".encode("ascii")
    return hashlib.sha1(header + blob_bytes).hexdigest()


def _working_blob_sha1(repo_root: Path, relative_name: str, path: Path) -> str | None:
    """Hash a tracked worktree artifact using its Git path's clean rules."""

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "hash-object", "--path", relative_name,
             "--", str(path)],
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    blob = result.stdout.decode("ascii", errors="replace").strip()
    return blob if re.fullmatch(r"[0-9a-f]{40}", blob) else None


def _git_commit_parent(repo_root: Path, commit_sha: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "show", "-s", "--format=%P", commit_sha],
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    parents = result.stdout.decode("ascii", errors="strict").strip().split()
    return parents[0] if len(parents) == 1 else None


def _normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_pinned_lines(text: str) -> tuple[dict[str, str], list[str], list[str]]:
    packages: dict[str, str] = {}
    invalid: list[str] = []
    duplicates: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _PINNED_LINE.fullmatch(line)
        if match is None:
            invalid.append(raw_line)
            continue
        normalized = _normalize_package_name(match.group("name"))
        if normalized in packages:
            duplicates.append(raw_line)
            continue
        packages[normalized] = match.group("version")
    return packages, invalid, duplicates


def _state_values(state_text: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for line in state_text.splitlines():
        match = _KEY_LINE.fullmatch(line.strip())
        if match is None:
            continue
        values.setdefault(match.group("key"), []).append(match.group("value"))
    return values


def _one_state_value(values: dict[str, list[str]], key: str) -> tuple[str | None, str | None]:
    matches = values.get(key, [])
    if not matches:
        return None, "CURRENT_AUTHORITY_STATE_KEY_MISSING"
    if len(matches) != 1:
        return None, "CURRENT_AUTHORITY_STATE_KEY_AMBIGUOUS"
    return matches[0], None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _current_chain_state_ok(values: dict[str, list[str]]) -> tuple[bool, str | None]:
    expected = {
        "V10C_T0_CANONICAL_ML_ENVIRONMENT_STATE": "CANONICAL_FROZEN",
        "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR_PROMOTED": "true",
        "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR_ENVIRONMENT_FROZEN": "true",
        "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR_ENVIRONMENT_STATE": "CANONICAL_FROZEN",
        "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR_GLOBAL_T0_READINESS": "NO",
        "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR_HISTORICAL_EVALUATION_AUTHORIZED": "false",
        "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR_PRIVATE_SEALED_ACCESS_AUTHORIZED": "false",
        "V10C_T0_CANONICAL_ML_ENVIRONMENT_SUCCESSOR_FUTURE_PROFITABILITY_ESTABLISHED": "false",
        "V10C_T0_ML_RESOLUTION_PROMOTION": "GPT_REVIEWED_PASS",
        "V10C_T0_ML_SUCCESSOR_LOCK_PROMOTED": "true",
        "V10C_T0_ML_SUCCESSOR_FINAL_FREEZE_F9_REVIEWED_SHA": CURRENT_AUTHORITY_REVIEWED_SHA,
        "V10C_T0_ML_SUCCESSOR_FINAL_FREEZE_F9_REVIEW_RESULT": "PASS_CRITICAL_0_HIGH_0_MEDIUM_0_LOW_0",
        "V10C_T0_ML_SUCCESSOR_FINAL_FREEZE_F9_PARENT_SHA": CURRENT_AUTHORITY_REVIEWED_PARENT_SHA,
        "V10C_T0_ML_SUCCESSOR_FINAL_FREEZE_F9_SAFE_EVIDENCE_REVIEW": "PASS",
    }
    for key, expected_value in expected.items():
        actual, reason = _one_state_value(values, key)
        if reason is not None:
            return False, reason
        if actual != expected_value:
            return False, "CURRENT_AUTHORITY_STATE_VALUE_MISMATCH"
    return True, None


def resolve_historical_v10c_authority(
    *,
    repo_root: Path = REPO_ROOT,
    state_path: Path = PROJECT_STATE_PATH,
    lock_path: Path = CURRENT_LOCK_PATH,
    record_path: Path = FINAL_FREEZE_RECORD_PATH,
    evidence_path: Path = FINAL_FREEZE_EVIDENCE_PATH,
    promotion_path: Path = RESOLUTION_PROMOTION_PATH,
    git_blob_reader: GitBlobReader = _git_blob_bytes,
) -> dict[str, Any]:
    """Resolve exactly one reviewed current authority, failing closed."""

    try:
        state_values = _state_values(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_STATE_UNREADABLE"}

    state_ok, state_reason = _current_chain_state_ok(state_values)
    if not state_ok:
        return {"status": "FAIL", "reason": state_reason}

    if _git_commit_parent(repo_root, CURRENT_AUTHORITY_REVIEWED_SHA) != CURRENT_AUTHORITY_REVIEWED_PARENT_SHA:
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_REVIEW_COMMIT_PARENT_MISMATCH"}

    artifact_paths = {
        "lock": (CURRENT_AUTHORITY_LOCK_PATH, lock_path, CURRENT_AUTHORITY_LOCK_BLOB_SHA1),
        "final_freeze_record": (str(FINAL_FREEZE_RECORD_PATH.name), record_path, CURRENT_AUTHORITY_RECORD_BLOB_SHA1),
        "final_freeze_evidence": (str(FINAL_FREEZE_EVIDENCE_PATH.name), evidence_path, CURRENT_AUTHORITY_EVIDENCE_BLOB_SHA1),
        "resolution_promotion": (str(RESOLUTION_PROMOTION_PATH.name), promotion_path, CURRENT_AUTHORITY_PROMOTION_BLOB_SHA1),
    }
    artifacts: dict[str, bytes] = {}
    for label, (relative_name, path, expected_blob) in artifact_paths.items():
        reviewed = git_blob_reader(repo_root, f"{CURRENT_AUTHORITY_REVIEWED_SHA}:{relative_name}")
        if reviewed is None or _git_blob_sha1(reviewed) != expected_blob:
            return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_REVIEWED_ARTIFACT_UNAVAILABLE", "artifact": label}
        if not path.is_file():
            return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_WORKING_ARTIFACT_UNREADABLE", "artifact": label}
        if _working_blob_sha1(repo_root, relative_name, path) != expected_blob:
            return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_WORKING_ARTIFACT_MISMATCH", "artifact": label}
        artifacts[label] = reviewed

    lock_text = artifacts["lock"].decode("utf-8")
    package_map, invalid_lines, duplicate_lines = _parse_pinned_lines(lock_text)
    if invalid_lines or duplicate_lines or len(package_map) != CURRENT_AUTHORITY_LOCK_PACKAGE_COUNT:
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_LOCK_SCHEMA_INVALID"}
    if hashlib.sha256(artifacts["lock"]).hexdigest() != CURRENT_AUTHORITY_LOCK_SHA256:
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_LOCK_SHA256_MISMATCH"}

    record = json.loads(artifacts["final_freeze_record"].decode("utf-8"))
    promotion = json.loads(artifacts["resolution_promotion"].decode("utf-8"))
    evidence = json.loads(artifacts["final_freeze_evidence"].decode("utf-8"))
    if not isinstance(record, dict) or not isinstance(promotion, dict) or not isinstance(evidence, dict):
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_ARTIFACT_SCHEMA_INVALID"}
    if (
        record.get("study") != CURRENT_AUTHORITY_STUDY
        or record.get("successor_lock_git_blob_sha1") != CURRENT_AUTHORITY_LOCK_BLOB_SHA1
        or record.get("successor_lock_sha256") != CURRENT_AUTHORITY_LOCK_SHA256
        or record.get("successor_package_count") != CURRENT_AUTHORITY_LOCK_PACKAGE_COUNT
        or record.get("predecessor_lock_git_blob_sha1") != CURRENT_AUTHORITY_PREDECESSOR_LOCK_BLOB_SHA1
        or record.get("predecessor_lock_sha256") != CURRENT_AUTHORITY_PREDECESSOR_LOCK_SHA256
        or record.get("predecessor_package_count") != CURRENT_AUTHORITY_PREDECESSOR_PACKAGE_COUNT
        or record.get("environment_state") != "MUTATED_VALIDATED_NOT_FROZEN"
        or record.get("environment_frozen") is not False
    ):
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_FINAL_FREEZE_BINDING_MISMATCH"}
    if (
        promotion.get("successor_lock_sha256") != CURRENT_AUTHORITY_LOCK_SHA256
        or promotion.get("successor_lock_package_count") != CURRENT_AUTHORITY_LOCK_PACKAGE_COUNT
        or promotion.get("predecessor_package_count") != CURRENT_AUTHORITY_PREDECESSOR_PACKAGE_COUNT
        or promotion.get("successor_lock_file") != CURRENT_AUTHORITY_LOCK_PATH
    ):
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_PROMOTION_BINDING_MISMATCH"}
    if (
        evidence.get("study") != CURRENT_AUTHORITY_STUDY
        or evidence.get("package_count") != CURRENT_AUTHORITY_LOCK_PACKAGE_COUNT
        or evidence.get("canonical_environment_promoted") is not False
        or evidence.get("environment_frozen") is not False
        or evidence.get("global_t0_readiness") != "NO"
        or evidence.get("t0_authorized") is not False
        or evidence.get("future_profitability_established") is not False
        or hashlib.sha256(artifacts["final_freeze_evidence"]).hexdigest() != CURRENT_AUTHORITY_SAFE_EVIDENCE_SHA256
    ):
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_FINAL_FREEZE_EVIDENCE_MISMATCH"}

    return {
        "status": "PASS",
        "study": CURRENT_AUTHORITY_STUDY,
        "authority_state": CURRENT_AUTHORITY_STATE,
        "reviewed_sha": CURRENT_AUTHORITY_REVIEWED_SHA,
        "lock_path": CURRENT_AUTHORITY_LOCK_PATH,
        "lock_sha256": CURRENT_AUTHORITY_LOCK_SHA256,
        "package_count": CURRENT_AUTHORITY_LOCK_PACKAGE_COUNT,
        "package_map": package_map,
        "historical_predecessor_package_count": CURRENT_AUTHORITY_PREDECESSOR_PACKAGE_COUNT,
        "historical_predecessor_lock_blob_sha1": CURRENT_AUTHORITY_PREDECESSOR_LOCK_BLOB_SHA1,
    }


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def resolve_current_authority(
    *,
    repo_root: Path = REPO_ROOT,
    state_path: Path = PROJECT_STATE_PATH,
    lock_path: Path = V13_FINAL_LOCK_PATH,
    promotion_path: Path = V13_PROMOTION_PATH,
    git_blob_reader: GitBlobReader = _git_blob_bytes,
) -> dict[str, Any]:
    """Bind V13 to the reviewed V10C predecessor and exact #110 safe result."""

    predecessor = resolve_historical_v10c_authority(repo_root=repo_root, state_path=state_path)
    if predecessor["status"] != "PASS" or predecessor["package_count"] != 27:
        return {"status": "FAIL", "reason": "HISTORICAL_PREDECESSOR_INVALID"}
    if _git_commit_parent(repo_root, V13_REVIEWED_SHA) != V13_REVIEWED_PARENT_SHA:
        return {"status": "FAIL", "reason": "V13_REVIEWED_PARENT_MISMATCH"}
    try:
        values = _state_values(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_STATE_UNREADABLE"}
    expected_state = {
        "CURRENT_PROTECTED_ENVIRONMENT_STUDY": "V13_PROTECTED_XLSX_ENVIRONMENT_SUCCESSOR",
        "CURRENT_PROTECTED_ENVIRONMENT_PACKAGE_COUNT": "29",
        "CURRENT_PROTECTED_ENVIRONMENT_LOCK_BLOB": V13_LOCK_BLOB_SHA1,
        "CURRENT_PROTECTED_ENVIRONMENT_PROMOTION_BLOB": V13_PROMOTION_BLOB_SHA1,
        "V13_XLSX_SUCCESSOR_PROMOTED": "true",
        "V13_XLSX_PREDECESSOR_27_PACKAGE_AUTHORITY_HISTORICAL": "true",
        "V13_XLSX_ISSUE110_GPT_REVIEWED_SHA": V13_REVIEWED_SHA,
        "V13_XLSX_ISSUE110_GPT_REVIEW_COMMENT_ID": "5851650708",
        "V13_XLSX_FINAL_PROMOTION_REVIEW_STATUS": "AWAITING_GPT_EXACT_SHA_REVIEW",
        "V13_XLSX_FUTURE_PROFITABILITY_ESTABLISHED": "false",
    }
    for key, expected in expected_state.items():
        actual, reason = _one_state_value(values, key)
        if reason or actual != expected:
            return {"status": "FAIL", "reason": reason or "CURRENT_AUTHORITY_STATE_VALUE_MISMATCH"}

    paths = {
        "predecessor_lock": (CURRENT_AUTHORITY_LOCK_PATH, CURRENT_LOCK_PATH, CURRENT_AUTHORITY_LOCK_BLOB_SHA1),
        "candidate_lock": (V13_CANDIDATE_LOCK_PATH.name, V13_CANDIDATE_LOCK_PATH, V13_LOCK_BLOB_SHA1),
        "final_lock": (V13_FINAL_LOCK_PATH.name, lock_path, V13_LOCK_BLOB_SHA1),
        "promotion": (V13_PROMOTION_PATH.relative_to(REPO_ROOT).as_posix(), promotion_path, V13_PROMOTION_BLOB_SHA1),
        "safe_result": (V13_SAFE_RESULT_PATH.relative_to(REPO_ROOT).as_posix(), V13_SAFE_RESULT_PATH, V13_SAFE_RESULT_BLOB_SHA1),
        "authorization": (V13_AUTHORIZATION_PATH.relative_to(REPO_ROOT).as_posix(), V13_AUTHORIZATION_PATH, V13_AUTHORIZATION_BLOB_SHA1),
    }
    raw: dict[str, bytes] = {}
    for label, (relative_name, path, expected_blob) in paths.items():
        ref = f"{V13_REVIEWED_SHA}:{relative_name}" if label in {"safe_result", "authorization", "candidate_lock", "predecessor_lock"} else expected_blob
        blob = git_blob_reader(repo_root, ref)
        if blob is None or _git_blob_sha1(blob) != expected_blob:
            return {"status": "FAIL", "reason": "V13_AUTHORITY_GIT_BLOB_MISMATCH", "artifact": label}
        if not path.is_file() or _working_blob_sha1(repo_root, relative_name, path) != expected_blob:
            return {"status": "FAIL", "reason": "V13_AUTHORITY_WORKING_BLOB_MISMATCH", "artifact": label}
        raw[label] = blob
    for relative_name, expected_blob in REVIEWED_PROBE_BLOBS.items():
        blob = git_blob_reader(repo_root, f"{V13_REVIEWED_SHA}:{relative_name}")
        if blob is None or _git_blob_sha1(blob) != expected_blob:
            return {"status": "FAIL", "reason": "V13_REVIEWED_PROBE_BLOB_MISMATCH", "artifact": relative_name}
        if _working_blob_sha1(repo_root, relative_name, repo_root / relative_name) != expected_blob:
            return {"status": "FAIL", "reason": "V13_WORKING_PROBE_BLOB_MISMATCH", "artifact": relative_name}
    if raw["candidate_lock"] != raw["final_lock"] or hashlib.sha256(raw["final_lock"]).hexdigest() != V13_LOCK_SHA256:
        return {"status": "FAIL", "reason": "V13_FINAL_LOCK_IDENTITY_MISMATCH"}
    try:
        final_map, invalid, duplicates = _parse_pinned_lines(raw["final_lock"].decode("ascii"))
        promotion = json.loads(raw["promotion"], object_pairs_hook=_unique_json_pairs)
        safe = json.loads(raw["safe_result"], object_pairs_hook=_unique_json_pairs)
    except (UnicodeError, ValueError, TypeError):
        return {"status": "FAIL", "reason": "V13_AUTHORITY_SCHEMA_INVALID"}
    if invalid or duplicates or len(final_map) != 29 or any(final_map.get(k) != v for k, v in predecessor["package_map"].items()):
        return {"status": "FAIL", "reason": "V13_FINAL_PACKAGE_SET_INVALID"}
    delta = sorted(f"{key}=={value}" for key, value in final_map.items() if key not in predecessor["package_map"])
    if delta != V13_DELTA or final_map.get("openpyxl") != "3.1.5" or final_map.get("et-xmlfile") != "2.0.0":
        return {"status": "FAIL", "reason": "V13_SUCCESSOR_DELTA_INVALID"}
    lock_binding = lambda name, blob, sha, count: {"path": name, "git_blob_sha1": blob, "sha256": sha, "package_count": count}
    required = {
        "schema_version": "V13_XLSX_SUCCESSOR_FINAL_CURRENT_AUTHORITY_PROMOTION_V1",
        "artifact_role": "FINAL_CURRENT_PROTECTED_ENVIRONMENT_AUTHORITY_PROMOTION",
        "authoritative_branch": "v13-conditional-cross-sectional-short-horizon",
        "github_issue": 111,
        "starting_head": V13_REVIEWED_SHA,
        "predecessor_issue": 110,
        "predecessor_gpt_result": "PASS",
        "predecessor_gpt_reviewed_sha": V13_REVIEWED_SHA,
        "predecessor_gpt_review_comment_id": 5851650708,
        "source_safe_result_comment_id": 5851490615,
        "source_safe_result_path": paths["safe_result"][0],
        "source_safe_result_git_blob_sha1": V13_SAFE_RESULT_BLOB_SHA1,
        "human_promotion_approval_comment_id": 5851057309,
        "active_mutation_authorization_blob": V13_AUTHORIZATION_BLOB_SHA1,
        "predecessor_lock": lock_binding(CURRENT_AUTHORITY_LOCK_PATH, CURRENT_AUTHORITY_LOCK_BLOB_SHA1, CURRENT_AUTHORITY_LOCK_SHA256, 27),
        "candidate_lock": lock_binding(V13_CANDIDATE_LOCK_PATH.name, V13_LOCK_BLOB_SHA1, V13_LOCK_SHA256, 29),
        "final_lock": lock_binding(V13_FINAL_LOCK_PATH.name, V13_LOCK_BLOB_SHA1, V13_LOCK_SHA256, 29),
        "candidate_final_lock_bytes_identical": True,
        "successor_delta": V13_DELTA,
        "successor_delta_package_count": 2,
        "wheel_manifest_sha256": "5665dbd50d13dc445792d031db7866e4f9e8e71244ecbddbf4187464ccafa8c2",
        "source_mutation_status": "MUTATED_VALIDATED_NOT_YET_PROMOTED",
        "source_mutation_authority_consumed": True,
        "source_mutation_authorization_reusable": False,
        "source_installed_package_count": 29,
        "source_pdf_readiness": "PASS",
        "source_production_xlsx_readiness": "PASS",
        "predecessor_authority_historical": True,
        "current_authority_changed": True,
        "successor_promoted": True,
        "promotion_status_at_creation": "AWAITING_GPT_EXACT_SHA_REVIEW",
        "promotion_effective_only_after_gpt_exact_sha_pass": True,
        "downstream_research_trading_authorized": False,
        "future_profitability_established": False,
    }
    zero_fields = [
        "network_requests", "package_index_requests", "wheel_downloads", "package_installations",
        "active_environment_mutations", "machine_local_receipt_reads", "phase_b_reads",
        "realized_candidate_reads", "private_reads", "jpx_yahoo_requests", "model_fits", "backtests",
    ]
    required.update({f"repository_task_{key}": 0 for key in zero_fields})
    required.update({f"repository_task_{key}": False for key in ("selected500", "aq_execution", "paper_trading", "real_trading")})
    if type(promotion) is not dict or set(promotion) != set(required) or any(type(promotion[k]) is not type(v) or promotion[k] != v for k, v in required.items()):
        return {"status": "FAIL", "reason": "V13_PROMOTION_BINDING_MISMATCH"}
    if not isinstance(safe, dict) or safe.get("status") != "MUTATED_VALIDATED_NOT_YET_PROMOTED" or safe.get("authority_consumed") is not True or safe.get("authorization_reusable") is not False or safe.get("installed_package_count") != 29 or safe.get("pdf_readiness") != "PASS" or safe.get("production_xlsx_readiness") != "PASS" or safe.get("successor_promoted") is not False:
        return {"status": "FAIL", "reason": "V13_SAFE_RESULT_BINDING_MISMATCH"}
    return {"status": "PASS", "study": "V13_PROTECTED_XLSX_ENVIRONMENT_SUCCESSOR", "authority_state": "CANONICAL_FROZEN_AFTER_GPT_PASS", "reviewed_sha": V13_REVIEWED_SHA, "lock_path": V13_FINAL_LOCK_PATH.name, "lock_sha256": V13_LOCK_SHA256, "package_count": 29, "package_map": final_map, "historical_predecessor_package_count": 27, "historical_predecessor_lock_blob_sha1": CURRENT_AUTHORITY_LOCK_BLOB_SHA1}


def check_interpreter_identity() -> dict[str, Any]:
    actual = Path(sys.executable).resolve(strict=False)
    expected = CANONICAL_INTERPRETER.resolve(strict=False)
    interpreter_match = os.path.normcase(str(actual)) == os.path.normcase(str(expected))
    version = tuple(sys.version_info[:3])
    version_match = version == CANONICAL_PYTHON_VERSION
    platform_match = (
        os.name == "nt"
        and platform.python_implementation() == "CPython"
        and platform.system() == "Windows"
        and platform.machine() == "AMD64"
        and sysconfig.get_platform() == "win-amd64"
    )
    identity_match = interpreter_match and version_match and platform_match
    return {
        "status": "PASS" if identity_match else "FAIL",
        "interpreter_match": interpreter_match,
        "python_version": ".".join(str(item) for item in version),
        "python_patch_match": version_match,
        "platform_match": platform_match,
        "failure_class": None if identity_match else "PRE_GATE_WRONG_PYTHON_ENVIRONMENT",
    }


def _package_map_from_installed_metadata(distributions: Any) -> tuple[dict[str, str] | None, str | None]:
    actual: dict[str, str] = {}
    try:
        for distribution in distributions:
            name = distribution.metadata.get("Name")
            version = distribution.version
            if not isinstance(name, str) or not isinstance(version, str) or not name or not version:
                return None, "CURRENT_AUTHORITY_INSTALLED_METADATA_MALFORMED"
            normalized = _normalize_package_name(name)
            if normalized in actual:
                return None, "CURRENT_AUTHORITY_INSTALLED_METADATA_DUPLICATE"
            actual[normalized] = version
    except Exception:
        return None, "CURRENT_AUTHORITY_INSTALLED_METADATA_OBSERVATION_FAILED"
    return actual, None


def check_live_package_set(
    expected_packages: dict[str, str], observed_distributions: Any = None
) -> dict[str, Any]:
    """Validate injected metadata records; production uses the isolated child."""

    if observed_distributions is None:
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_ISOLATED_CHILD_REQUIRED"}
    actual, observation_reason = _package_map_from_installed_metadata(observed_distributions)
    if observation_reason is not None or actual is None:
        return {"status": "FAIL", "reason": observation_reason}
    if actual != expected_packages:
        return {
            "status": "FAIL",
            "reason": "CURRENT_AUTHORITY_PACKAGE_SET_MISMATCH",
            "missing_packages": sorted(set(expected_packages) - set(actual)),
            "extra_packages": sorted(set(actual) - set(expected_packages)),
            "version_mismatches": sorted(
                key for key in set(expected_packages) & set(actual) if expected_packages[key] != actual[key]
            ),
        }
    return {"status": "PASS", "package_count": len(actual)}


def _isolated_child_script() -> str:
    """Return the reviewed-F6-style isolated observer program."""

    return r'''
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import sys
import sysconfig
from pathlib import Path

SCHEMA = "V13_CURRENT_PROTECTED_ENVIRONMENT_ISOLATED_OBSERVER_V1"
PDF_PASS = "SYNTHETIC_PDF_PROBE_PASS"


def emit(status, packages, package_status, package_failure, pdf_probe, xlsx_probe):
    result = {
        "schema_version": SCHEMA,
        "status": status,
        "isolated": type(sys.flags.isolated) is int and sys.flags.isolated == 1,
        "no_user_site": type(sys.flags.no_user_site) is int and sys.flags.no_user_site == 1,
        "pythonpath_env_absent": "PYTHONPATH" not in os.environ,
        "bytecode_disabled": sys.dont_write_bytecode is True,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "executable": str(Path(sys.executable).resolve(strict=False)),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "sysconfig_platform": sysconfig.get_platform(),
        "packages": packages,
        "package_observation_status": package_status,
        "package_failure": package_failure,
        "pdf_probe": pdf_probe,
        "xlsx_probe": xlsx_probe,
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


def empty_pdf_probe():
    return {"status": "FAIL", "fixture_sha256": None, "pdfplumber_version": None, "page_count": None}


def empty_xlsx_probe():
    return {"status": "FAIL", "openpyxl_version": None, "et_xmlfile_version": None}


packages = []
package_status = "PASS"
package_failure = None
pdf_probe = empty_pdf_probe()
xlsx_probe = empty_xlsx_probe()
try:
    if len(sys.argv) != 2:
        raise ValueError("REPOSITORY_ROOT_ARGUMENT_INVALID")
    repository_root = Path(sys.argv[1]).resolve(strict=True)
    probe_module_path = repository_root / "scripts" / "v9_014_pdf_env_successor.py"
    fixture_path = repository_root / "tests" / "fixtures" / "v9_014_synthetic_pdf_env_probe.pdf"
    if not probe_module_path.is_file() or not fixture_path.is_file():
        raise OSError("REVIEWED_PROBE_ARTIFACT_MISSING")

    names = set()
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        version = distribution.version
        if not isinstance(name, str) or not isinstance(version, str) or not name or not version:
            package_status = "FAIL"
            package_failure = "MALFORMED_METADATA"
            break
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        if normalized in names:
            package_status = "FAIL"
            package_failure = "DUPLICATE_NORMALIZED_METADATA"
            break
        names.add(normalized)
        packages.append({"name": name, "version": version})

    module_spec = importlib.util.spec_from_file_location("_v12_reviewed_pdf_probe", probe_module_path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError("REVIEWED_PROBE_LOAD_FAILED")
    probe_module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = probe_module
    module_spec.loader.exec_module(probe_module)
    probe_result = probe_module.run_synthetic_pdf_operational_probe(fixture_path=fixture_path)
    pdf_probe = {
        "status": getattr(probe_result, "status", None),
        "fixture_sha256": getattr(probe_result, "observed_fixture_sha256", None),
        "pdfplumber_version": getattr(probe_result, "observed_pdfplumber_version", None),
        "page_count": getattr(probe_result, "observed_page_count", None),
    }
    xlsx_module_path = repository_root / "scripts" / "v13_xlsx_readiness.py"
    if not xlsx_module_path.is_file():
        raise OSError("REVIEWED_XLSX_PROBE_MISSING")
    xlsx_spec = importlib.util.spec_from_file_location("_v13_reviewed_xlsx_probe", xlsx_module_path)
    if xlsx_spec is None or xlsx_spec.loader is None:
        raise ImportError("REVIEWED_XLSX_PROBE_LOAD_FAILED")
    xlsx_module = importlib.util.module_from_spec(xlsx_spec)
    sys.modules[xlsx_spec.name] = xlsx_module
    xlsx_spec.loader.exec_module(xlsx_module)
    sys.path.insert(0, str(repository_root))
    openpyxl_version = importlib.metadata.version("openpyxl")
    et_xmlfile_version = importlib.metadata.version("et-xmlfile")
    xlsx_probe = {
        "status": "PASS" if xlsx_module.probe_production_xlsx_route() else "FAIL",
        "openpyxl_version": openpyxl_version,
        "et_xmlfile_version": et_xmlfile_version,
    }
except Exception:
    if package_status == "PASS":
        package_status = "FAIL"
        package_failure = "ISOLATED_OBSERVER_EXCEPTION"
    if pdf_probe["status"] == "FAIL" and pdf_probe["fixture_sha256"] is None:
        pdf_probe = empty_pdf_probe()
    if xlsx_probe["status"] == "FAIL":
        xlsx_probe = empty_xlsx_probe()

identity_pass = (
    platform.python_implementation() == "CPython"
    and platform.python_version() == "3.12.10"
    and platform.system() == "Windows"
    and platform.machine() == "AMD64"
    and sysconfig.get_platform() == "win-amd64"
)
overall_status = "PASS" if identity_pass and package_status == "PASS" and pdf_probe["status"] == PDF_PASS and xlsx_probe == {"status": "PASS", "openpyxl_version": "3.1.5", "et_xmlfile_version": "2.0.0"} else "FAIL"
emit(overall_status, packages, package_status, package_failure, pdf_probe, xlsx_probe)
'''


def _controlled_child_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"PYTHONPATH", "PYTHONHOME"}
    }
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        }
    )
    return environment


def _validate_isolated_child_json(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(value, dict) or set(value) != ISOLATED_CHILD_TOP_KEYS:
        return None, "CURRENT_AUTHORITY_CHILD_JSON_SCHEMA_INVALID"
    if value.get("schema_version") != ISOLATED_CHILD_SCHEMA:
        return None, "CURRENT_AUTHORITY_CHILD_JSON_SCHEMA_INVALID"
    for key in ("isolated", "no_user_site", "pythonpath_env_absent", "bytecode_disabled"):
        if type(value.get(key)) is not bool:
            return None, "CURRENT_AUTHORITY_CHILD_JSON_TYPES_INVALID"
    for key in (
        "status",
        "python_implementation",
        "python_version",
        "executable",
        "platform_system",
        "platform_machine",
        "sysconfig_platform",
        "package_observation_status",
    ):
        if not isinstance(value.get(key), str):
            return None, "CURRENT_AUTHORITY_CHILD_JSON_TYPES_INVALID"
    if value.get("status") not in {"PASS", "FAIL"} or value.get("package_observation_status") not in {"PASS", "FAIL"}:
        return None, "CURRENT_AUTHORITY_CHILD_JSON_ENUM_INVALID"
    if value.get("package_failure") is not None and not isinstance(value.get("package_failure"), str):
        return None, "CURRENT_AUTHORITY_CHILD_JSON_TYPES_INVALID"
    packages = value.get("packages")
    if not isinstance(packages, list):
        return None, "CURRENT_AUTHORITY_CHILD_JSON_TYPES_INVALID"
    for package in packages:
        if not isinstance(package, dict) or set(package) != {"name", "version"}:
            return None, "CURRENT_AUTHORITY_CHILD_PACKAGE_SCHEMA_INVALID"
        if not isinstance(package["name"], str) or not package["name"] or not isinstance(package["version"], str) or not package["version"]:
            return None, "CURRENT_AUTHORITY_CHILD_PACKAGE_TYPES_INVALID"
    pdf_probe = value.get("pdf_probe")
    if not isinstance(pdf_probe, dict) or set(pdf_probe) != ISOLATED_CHILD_PDF_KEYS:
        return None, "CURRENT_AUTHORITY_CHILD_PDF_SCHEMA_INVALID"
    if not isinstance(pdf_probe["status"], str):
        return None, "CURRENT_AUTHORITY_CHILD_PDF_TYPES_INVALID"
    for key in ("fixture_sha256", "pdfplumber_version"):
        if pdf_probe[key] is not None and not isinstance(pdf_probe[key], str):
            return None, "CURRENT_AUTHORITY_CHILD_PDF_TYPES_INVALID"
    if pdf_probe["page_count"] is not None and (type(pdf_probe["page_count"]) is not int or isinstance(pdf_probe["page_count"], bool)):
        return None, "CURRENT_AUTHORITY_CHILD_PDF_TYPES_INVALID"
    xlsx_probe = value.get("xlsx_probe")
    if not isinstance(xlsx_probe, dict) or set(xlsx_probe) != ISOLATED_CHILD_XLSX_KEYS:
        return None, "CURRENT_AUTHORITY_CHILD_XLSX_SCHEMA_INVALID"
    if not isinstance(xlsx_probe["status"], str):
        return None, "CURRENT_AUTHORITY_CHILD_XLSX_TYPES_INVALID"
    for key in ("openpyxl_version", "et_xmlfile_version"):
        if xlsx_probe[key] is not None and not isinstance(xlsx_probe[key], str):
            return None, "CURRENT_AUTHORITY_CHILD_XLSX_TYPES_INVALID"
    return value, None


def _run_isolated_observer() -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                str(CANONICAL_INTERPRETER),
                "-I",
                "-B",
                "-c",
                _isolated_child_script(),
                str(REPO_ROOT),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=_controlled_child_environment(),
        )
    except OSError:
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_CHILD_LAUNCH_FAILED"}
    if result.returncode != 0:
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_CHILD_NONZERO_EXIT"}
    if result.stderr.strip():
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_CHILD_STDERR_NOT_EMPTY"}
    try:
        value = json.loads(result.stdout)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_CHILD_JSON_INVALID"}
    validated, reason = _validate_isolated_child_json(value)
    if reason is not None or validated is None:
        return {"status": "FAIL", "reason": reason}
    return {"status": "PASS", "evidence": validated}


def _validate_child_identity(evidence: dict[str, Any]) -> dict[str, Any]:
    try:
        executable_match = os.path.normcase(str(Path(evidence["executable"]).resolve(strict=False))) == os.path.normcase(
            str(CANONICAL_INTERPRETER.resolve(strict=False))
        )
    except OSError:
        executable_match = False
    passed = (
        evidence["status"] == "PASS"
        and evidence["isolated"] is True
        and evidence["no_user_site"] is True
        and evidence["pythonpath_env_absent"] is True
        and evidence["bytecode_disabled"] is True
        and evidence["python_implementation"] == "CPython"
        and evidence["python_version"] == "3.12.10"
        and evidence["platform_system"] == "Windows"
        and evidence["platform_machine"] == "AMD64"
        and evidence["sysconfig_platform"] == "win-amd64"
        and executable_match
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "reason": None if passed else "CURRENT_AUTHORITY_CHILD_IDENTITY_MISMATCH",
    }


def _package_map_from_records(records: list[dict[str, str]]) -> tuple[dict[str, str] | None, str | None]:
    actual: dict[str, str] = {}
    for record in records:
        normalized = _normalize_package_name(record["name"])
        if normalized in actual:
            return None, "CURRENT_AUTHORITY_INSTALLED_METADATA_DUPLICATE"
        actual[normalized] = record["version"]
    return actual, None


def _validate_child_package_set(expected_packages: dict[str, str], evidence: dict[str, Any]) -> dict[str, Any]:
    if evidence["package_observation_status"] != "PASS":
        return {
            "status": "FAIL",
            "reason": evidence["package_failure"] or "CURRENT_AUTHORITY_INSTALLED_METADATA_OBSERVATION_FAILED",
        }
    actual, reason = _package_map_from_records(evidence["packages"])
    if reason is not None or actual is None:
        return {"status": "FAIL", "reason": reason}
    if actual != expected_packages:
        return {
            "status": "FAIL",
            "reason": "CURRENT_AUTHORITY_PACKAGE_SET_MISMATCH",
            "missing_packages": sorted(set(expected_packages) - set(actual)),
            "extra_packages": sorted(set(actual) - set(expected_packages)),
            "version_mismatches": sorted(
                key for key in set(expected_packages) & set(actual) if expected_packages[key] != actual[key]
            ),
        }
    return {"status": "PASS", "package_count": len(actual)}


def _validate_child_pdf_probe(evidence: dict[str, Any]) -> dict[str, Any]:
    probe = evidence["pdf_probe"]
    if probe["status"] != PDF_PROBE_PASS:
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_PDF_PROBE_FAILED"}
    if probe["fixture_sha256"] != PDF_PROBE_EXPECTED_FIXTURE_SHA256:
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_PDF_PROBE_FIXTURE_IDENTITY_MISMATCH"}
    if probe["pdfplumber_version"] != PDF_PROBE_REQUIRED_PDFPLUMBER_VERSION:
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_PDF_PROBE_VERSION_MISMATCH"}
    if probe["page_count"] != PDF_PROBE_EXPECTED_PAGE_COUNT:
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_PDF_PROBE_PAGE_COUNT_MISMATCH"}
    return {
        "status": "PASS",
        "fixture_sha256": probe["fixture_sha256"],
        "pdfplumber_version": probe["pdfplumber_version"],
        "page_count": probe["page_count"],
    }


def _validate_child_xlsx_probe(evidence: dict[str, Any]) -> dict[str, Any]:
    probe = evidence["xlsx_probe"]
    if probe != {"status": "PASS", "openpyxl_version": "3.1.5", "et_xmlfile_version": "2.0.0"}:
        return {"status": "FAIL", "reason": "CURRENT_AUTHORITY_XLSX_PROBE_FAILED"}
    return {"status": "PASS", "openpyxl_version": "3.1.5", "et_xmlfile_version": "2.0.0"}


def run_current_readiness() -> dict[str, Any]:
    authority = resolve_current_authority()
    interpreter = check_interpreter_identity()
    isolated = (
        _run_isolated_observer()
        if authority["status"] == "PASS" and interpreter["status"] == "PASS"
        else {"status": "NOT_RUN", "reason": "CURRENT_AUTHORITY_PRECONDITION_FAILED"}
    )
    if isolated["status"] == "PASS":
        evidence = isolated["evidence"]
        child_identity = _validate_child_identity(evidence)
        packages = _validate_child_package_set(authority["package_map"], evidence)
        pdf_probe = _validate_child_pdf_probe(evidence)
        xlsx_probe = _validate_child_xlsx_probe(evidence)
    else:
        child_identity = {"status": "NOT_RUN", "reason": isolated["reason"]}
        packages = {"status": "NOT_RUN", "reason": isolated["reason"]}
        pdf_probe = {"status": "NOT_RUN", "reason": isolated["reason"]}
        xlsx_probe = {"status": "NOT_RUN", "reason": isolated["reason"]}
    ready = (
        authority["status"] == "PASS"
        and interpreter["status"] == "PASS"
        and isolated["status"] == "PASS"
        and child_identity["status"] == "PASS"
        and packages["status"] == "PASS"
        and pdf_probe["status"] == "PASS"
        and xlsx_probe["status"] == "PASS"
    )
    return {
        "CURRENT_PROTECTED_ENVIRONMENT_AUTHORITY": authority,
        "INTERPRETER": interpreter,
        "ISOLATED_RUNTIME": {"status": isolated["status"], "reason": isolated.get("reason")},
        "ISOLATED_CHILD_IDENTITY": child_identity,
        "LIVE_PACKAGE_SET": packages,
        "PDF_OPERATIONAL_PROBE": pdf_probe,
        "PRODUCTION_XLSX_OPERATIONAL_PROBE": xlsx_probe,
        "CURRENT_ENVIRONMENT_READY": ready,
        "REAL_NETWORK_REQUESTS": 0,
        "PRIVATE_READS": 0,
        "ENVIRONMENT_MUTATIONS": 0,
        "PACKAGE_INSTALLATIONS": 0,
        "GATES_CONSUMED": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve and validate the current protected environment")
    parser.parse_args()
    result = run_current_readiness()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["CURRENT_ENVIRONMENT_READY"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
