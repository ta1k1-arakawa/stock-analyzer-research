"""Validate Issue #110's public safe receipt using repository artifacts only."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts import check_current_protected_environment as current
from scripts import v13_xlsx_successor_freeze as freeze
from scripts import v13_xlsx_successor_realization_result as isolated

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "docs/v13/V13_XLSX_SUCCESSOR_ACTIVE_ENV_MUTATION_SAFE_RESULT.json"
AUTH = ROOT / "docs/v13/V13_XLSX_SUCCESSOR_ACTIVE_ENV_MUTATION_AUTHORIZATION.json"
AUTH_BLOB = "ff00b49346153dfe7d506432d8358713bbd7fa87"
EXECUTION_HEAD = "3b351fe13ab8b81bb6f8b295b3d24f44c4bd693c"


def _unique(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _exact(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _exact(actual[key], item) for key, item in expected.items()
        )
    return actual == expected


def _git_blob(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def validate_result(*, result_path: Path = RESULT) -> dict:
    frozen = freeze.validate_freeze()
    if frozen["status"] != "PASS" or frozen["current_authority_package_count"] != 27 or frozen["candidate_package_count"] != 29:
        raise ValueError("FROZEN_LOCKS_INVALID")
    prior = isolated.validate_result()
    if prior["status"] != "PASS" or prior["successor_promoted"]:
        raise ValueError("ISOLATED_RESULT_INVALID")

    rel = AUTH.relative_to(ROOT).as_posix()
    raw = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{rel}"],
                         capture_output=True, check=True).stdout
    worktree_blob = subprocess.run(
        ["git", "-C", str(ROOT), "hash-object", "--path", rel, "--", str(AUTH)],
        capture_output=True, check=True, text=True).stdout.strip()
    if _git_blob(raw) != AUTH_BLOB or worktree_blob != AUTH_BLOB:
        raise ValueError("AUTHORIZATION_BLOB_MISMATCH")
    auth = json.loads(raw, object_pairs_hook=_unique)
    if not _exact(auth["current_authority_lock"], {
        "path": current.CURRENT_AUTHORITY_LOCK_PATH,
        "git_blob_sha1": current.CURRENT_AUTHORITY_LOCK_BLOB_SHA1,
        "sha256": current.CURRENT_AUTHORITY_LOCK_SHA256,
        "package_count": 27,
    }) or not _exact(auth["candidate_lock"], {
        "path": freeze.LOCK.name,
        "git_blob_sha1": "dfe440dc6398dc3b1a2dd31c81047e4209e61536",
        "sha256": freeze.LOCK_SHA256,
        "package_count": 29,
    }) or auth["wheel_manifest_sha256"] != freeze.MANIFEST_SHA256 or auth["successor_delta"] != freeze.DELTA or auth["human_promotion_approval_comment_id"] != 5851057309 or auth["safe_realization_result"]["status"] != "PASS_CONSUMED":
        raise ValueError("AUTHORIZATION_BINDING_MISMATCH")

    expected = {
        "schema_version": "V13_XLSX_SUCCESSOR_ACTIVE_ENV_MUTATION_SAFE_RESULT_V1",
        "artifact_role": "ACTIVE_ENV_MUTATION_RESULT_NOT_CURRENT_AUTHORITY_PROMOTION",
        "source_issue": 108,
        "source_safe_result_comment_id": 5851490615,
        "source_receipt_schema_version": "V13_XLSX_ACTIVE_MUTATION_RECEIPT_V1",
        "source_remediation_issue": 109,
        "source_remediation_gpt_result": "PASS",
        "source_remediation_gpt_review_comment_id": 5851289194,
        "source_issue108_remediated_gpt_result": "PASS",
        "source_issue108_remediated_gpt_review_comment_id": 5851291486,
        "human_promotion_approval_comment_id": 5851057309,
        "execution_head": EXECUTION_HEAD,
        "authorization_blob": AUTH_BLOB,
        "current_lock_sha256": current.CURRENT_AUTHORITY_LOCK_SHA256,
        "candidate_lock_sha256": freeze.LOCK_SHA256,
        "current_authority_package_count": 27,
        "candidate_package_count": 29,
        "successor_delta": freeze.DELTA,
        "successor_delta_package_count": 2,
        "wheel_manifest_sha256": freeze.MANIFEST_SHA256,
        "source_isolated_realization_status": "PASS_CONSUMED",
        "status": "MUTATED_VALIDATED_NOT_YET_PROMOTED",
        "active_env_installed_state": "29_PACKAGE_MUTATED_VALIDATED_NOT_YET_PROMOTED",
        "repository_current_authority_declaration": "27_PACKAGE_V10C",
        "authority_consumed": True,
        "authorization_reusable": False,
        "second_active_env_mutation_allowed": False,
        "installed_package_count": 29,
        "production_xlsx_readiness": "PASS",
        "pdf_readiness": "PASS",
        "network_requests": 0,
        "wheel_downloads": 0,
        "process_exit_code": 0,
        "current_authority_changed": False,
        "successor_promoted": False,
        "model_fits": 0,
        "backtests": 0,
        "aq_execution": False,
        "paper_trading": 0,
        "real_trading": 0,
        "future_profitability_established": False,
    }
    value = json.loads(result_path.read_bytes(), object_pairs_hook=_unique)
    if not _exact(value, expected):
        raise ValueError("SAFE_RESULT_SCHEMA_OR_BINDING_MISMATCH")
    return {"status": "PASS", "active_env_installed_package_count": 29,
            "current_authority_package_count": 27, "successor_promoted": False}


if __name__ == "__main__":
    print(json.dumps(validate_result(), sort_keys=True))
