"""Synthetic, repository-only checks for Issue #110's safe checkpoint."""

import json

import pytest

from scripts import v13_xlsx_active_env_mutation_result as result


def test_safe_result_and_repository_bindings_pass():
    assert result.validate_result() == {
        "status": "PASS", "active_env_installed_package_count": 29,
        "current_authority_package_count": 27, "successor_promoted": False,
    }


@pytest.mark.parametrize("key,value", [
    ("source_issue", True),
    ("source_safe_result_comment_id", 1),
    ("source_remediation_gpt_review_comment_id", 1),
    ("source_issue108_remediated_gpt_review_comment_id", 1),
    ("human_promotion_approval_comment_id", 1),
    ("execution_head", "0" * 40),
    ("authorization_blob", "0" * 40),
    ("current_lock_sha256", "0" * 64),
    ("candidate_lock_sha256", "0" * 64),
    ("current_authority_package_count", 29),
    ("candidate_package_count", 27),
    ("successor_delta", ["openpyxl==3.1.4"]),
    ("wheel_manifest_sha256", "0" * 64),
    ("source_isolated_realization_status", "MUTATED_VALIDATED_NOT_YET_PROMOTED"),
    ("status", "PASS_CONSUMED"),
    ("active_env_installed_state", "27_PACKAGE_V10C"),
    ("repository_current_authority_declaration", "29_PACKAGE_XLSX"),
    ("authority_consumed", False),
    ("authorization_reusable", True),
    ("second_active_env_mutation_allowed", True),
    ("installed_package_count", 27),
    ("production_xlsx_readiness", "FAIL"),
    ("pdf_readiness", "FAIL"),
    ("network_requests", 1),
    ("wheel_downloads", 1),
    ("process_exit_code", 1),
    ("current_authority_changed", True),
    ("successor_promoted", True),
    ("model_fits", 1),
    ("backtests", 1),
    ("aq_execution", True),
    ("paper_trading", 1),
    ("real_trading", 1),
    ("future_profitability_established", True),
])
def test_changed_binding_fails(tmp_path, key, value):
    data = json.loads(result.RESULT.read_bytes())
    data[key] = value
    path = tmp_path / "safe.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="SAFE_RESULT_SCHEMA_OR_BINDING_MISMATCH"):
        result.validate_result(result_path=path)


@pytest.mark.parametrize("change", ["extra", "missing", "duplicate"])
def test_closed_schema(tmp_path, change):
    data = json.loads(result.RESULT.read_bytes())
    if change == "extra":
        data["machine_path"] = "forbidden"
    elif change == "missing":
        del data["future_profitability_established"]
    raw = json.dumps(data)
    if change == "duplicate":
        raw = raw.replace('"status": "MUTATED_VALIDATED_NOT_YET_PROMOTED"',
                          '"status": "MUTATED_VALIDATED_NOT_YET_PROMOTED", "status": "MUTATED_VALIDATED_NOT_YET_PROMOTED"')
    path = tmp_path / "safe.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        result.validate_result(result_path=path)
