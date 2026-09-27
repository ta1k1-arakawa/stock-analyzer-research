"""No-network tests for the V13 current protected-environment authority."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

import scripts.check_current_protected_environment as checker
import scripts.check_real_execution_env as historical_checker


def _real_lock_text() -> str:
    return checker.V13_FINAL_LOCK_PATH.read_text(encoding="utf-8")


def _distribution_records(package_map: dict[str, str]) -> list[SimpleNamespace]:
    return [SimpleNamespace(metadata={"Name": name}, version=version) for name, version in package_map.items()]


def _isolated_evidence(package_map: dict[str, str], **overrides) -> dict:
    evidence = {
        "schema_version": checker.ISOLATED_CHILD_SCHEMA,
        "status": "PASS",
        "isolated": True,
        "no_user_site": True,
        "pythonpath_env_absent": True,
        "bytecode_disabled": True,
        "python_implementation": "CPython",
        "python_version": "3.12.10",
        "executable": str(checker.CANONICAL_INTERPRETER.resolve(strict=False)),
        "platform_system": "Windows",
        "platform_machine": "AMD64",
        "sysconfig_platform": "win-amd64",
        "packages": [{"name": name, "version": version} for name, version in package_map.items()],
        "package_observation_status": "PASS",
        "package_failure": None,
        "pdf_probe": {
            "status": checker.PDF_PROBE_PASS,
            "fixture_sha256": checker.PDF_PROBE_EXPECTED_FIXTURE_SHA256,
            "pdfplumber_version": checker.PDF_PROBE_REQUIRED_PDFPLUMBER_VERSION,
            "page_count": checker.PDF_PROBE_EXPECTED_PAGE_COUNT,
        },
        "xlsx_probe": {"status": "PASS", "openpyxl_version": "3.1.5", "et_xmlfile_version": "2.0.0"},
    }
    evidence.update(overrides)
    return evidence


def test_current_authority_resolves_to_v13_29_package_chain() -> None:
    assert "V13_XLSX_FINAL_PROMOTION_REVIEW_STATUS=PASS" in checker.PROJECT_STATE_PATH.read_text(encoding="utf-8")
    result = checker.resolve_current_authority()
    assert result["status"] == "PASS"
    assert result["study"] == "V13_PROTECTED_XLSX_ENVIRONMENT_SUCCESSOR"
    assert result["reviewed_sha"] == checker.V13_REVIEWED_SHA
    assert result["package_count"] == 29
    assert result["historical_predecessor_package_count"] == 27
    assert checker.resolve_historical_v10c_authority()["package_count"] == 27


def test_final_lock_and_promotion_are_exactly_bound() -> None:
    candidate = checker._git_blob_bytes(checker.REPO_ROOT, checker.V13_LOCK_BLOB_SHA1)
    assert candidate is not None
    assert checker._working_blob_sha1(checker.REPO_ROOT, checker.V13_FINAL_LOCK_PATH.name, checker.V13_FINAL_LOCK_PATH) == checker.V13_LOCK_BLOB_SHA1
    assert checker._working_blob_sha1(checker.REPO_ROOT, checker.V13_CANDIDATE_LOCK_PATH.name, checker.V13_CANDIDATE_LOCK_PATH) == checker.V13_LOCK_BLOB_SHA1
    assert hashlib.sha256(candidate).hexdigest() == checker.V13_LOCK_SHA256
    assert len(checker._parse_pinned_lines(candidate.decode("ascii"))[0]) == 29
    assert checker.V13_DELTA == ["et-xmlfile==2.0.0", "openpyxl==3.1.5"]
    safe = checker._git_blob_bytes(checker.REPO_ROOT, f"{checker.V13_REVIEWED_SHA}:docs/v13/V13_XLSX_SUCCESSOR_ACTIVE_ENV_MUTATION_SAFE_RESULT.json")
    assert safe is not None and checker._git_blob_sha1(safe) == checker.V13_SAFE_RESULT_BLOB_SHA1
    assert json.loads(safe)["status"] == "MUTATED_VALIDATED_NOT_YET_PROMOTED"


def test_promotion_artifact_drift_fails_closed(tmp_path: Path) -> None:
    altered = json.loads(checker.V13_PROMOTION_PATH.read_text(encoding="utf-8"))
    altered["source_pdf_readiness"] = "FAIL"
    path = tmp_path / "promotion.json"
    path.write_text(json.dumps(altered), encoding="utf-8")
    result = checker.resolve_current_authority(promotion_path=path)
    assert result == {"status": "FAIL", "reason": "V13_AUTHORITY_WORKING_BLOB_MISMATCH", "artifact": "promotion"}


def test_historical_fifteen_package_checker_remains_independently_bound() -> None:
    assert historical_checker.REVIEWED_PACKAGE_COUNT == 15
    blob = historical_checker._git_blob_bytes(
        historical_checker.REPO_ROOT, historical_checker.REVIEWED_LOCK_GIT_BLOB_SHA1
    )
    assert blob is not None
    assert len(historical_checker._parse_pinned_lock_lines(blob.decode("utf-8"))) == 15
    assert historical_checker.REVIEWED_LOCK_SHA256 != checker.CURRENT_AUTHORITY_LOCK_SHA256


def test_current_checker_binds_reviewed_safe_result(monkeypatch) -> None:
    calls: list[str] = []
    real_reader = checker._git_blob_bytes

    def recording_reader(repo_root: Path, git_ref: str):
        calls.append(git_ref)
        return real_reader(repo_root, git_ref)

    result = checker.resolve_current_authority(git_blob_reader=recording_reader)
    assert result["status"] == "PASS"
    assert f"{checker.V13_REVIEWED_SHA}:docs/v13/V13_XLSX_SUCCESSOR_ACTIVE_ENV_MUTATION_SAFE_RESULT.json" in calls
    assert checker.V13_PROMOTION_BLOB_SHA1 in calls


def test_parser_probe_uses_issue_121_reviewed_git_object_and_worktree_blob(monkeypatch) -> None:
    parser_path = "src/v13_public_data_lock.py"
    reviewed_sha = "fbfe886254cf1ac053270857b7f188e83d948a75"
    reviewed_blob = "aa18f8f31b524d3e8543cf6b9a86c1d980087b7b"
    assert checker.REVIEWED_PROBE_BLOBS[parser_path] == (reviewed_sha, reviewed_blob)
    calls: list[str] = []

    def recording_reader(repo_root: Path, git_ref: str):
        calls.append(git_ref)
        return checker._git_blob_bytes(repo_root, git_ref)

    assert checker.resolve_current_authority(git_blob_reader=recording_reader)["status"] == "PASS"
    assert f"{reviewed_sha}:{parser_path}" in calls
    for path, (sha, blob) in checker.REVIEWED_PROBE_BLOBS.items():
        assert f"{sha}:{path}" in calls
        assert checker._git_blob_sha1(checker._git_blob_bytes(checker.REPO_ROOT, f"{sha}:{path}")) == blob

    original = checker._working_blob_sha1

    def wrong_parser(repo_root: Path, relative_name: str, path: Path) -> str | None:
        if relative_name == parser_path:
            return "0" * 40
        return original(repo_root, relative_name, path)

    monkeypatch.setattr(checker, "_working_blob_sha1", wrong_parser)
    assert checker.resolve_current_authority() == {
        "status": "FAIL", "reason": "V13_WORKING_PROBE_BLOB_MISMATCH", "artifact": parser_path,
    }


def test_current_package_set_matches_the_resolved_29_package_lock() -> None:
    authority = checker.resolve_current_authority()
    result = checker.check_live_package_set(
        authority["package_map"], _distribution_records(authority["package_map"])
    )
    assert result == {"status": "PASS", "package_count": 29}


def test_current_package_observer_uses_exact_installed_metadata() -> None:
    authority = checker.resolve_current_authority()
    result = checker.check_live_package_set(
        authority["package_map"], _distribution_records(authority["package_map"])
    )
    assert result == {"status": "PASS", "package_count": 29}


def test_direct_reference_pip_freeze_presentation_does_not_control_acceptance(monkeypatch) -> None:
    authority = checker.resolve_current_authority()
    child_output = json.dumps(_isolated_evidence(authority["package_map"]))
    fake_result = SimpleNamespace(returncode=0, stdout=child_output, stderr="")
    monkeypatch.setenv("PYTHONPATH", "C:\\ambient\\untrusted")
    with mock.patch.object(checker.subprocess, "run", return_value=fake_result) as run:
        result = checker._run_isolated_observer()
    assert result["status"] == "PASS"
    child_environment = run.call_args.kwargs["env"]
    assert all(key.upper() != "PYTHONPATH" for key in child_environment)
    assert "-I" in run.call_args.args[0]
    assert "pip freeze" not in run.call_args.args[0][4]


def test_missing_extra_and_version_drift_metadata_fail_closed() -> None:
    authority = checker.resolve_current_authority()
    package_map = dict(authority["package_map"])
    package_map.pop("scipy")
    package_map["unexpected-package"] = "1.0.0"
    package_map["lightgbm"] = "4.5.0"
    result = checker.check_live_package_set(
        authority["package_map"], _distribution_records(package_map)
    )
    assert result["status"] == "FAIL"
    assert result["reason"] == "CURRENT_AUTHORITY_PACKAGE_SET_MISMATCH"
    assert result["missing_packages"] == ["scipy"]
    assert result["extra_packages"] == ["unexpected-package"]
    assert result["version_mismatches"] == ["lightgbm"]


def test_duplicate_normalized_metadata_fails_closed() -> None:
    authority = checker.resolve_current_authority()
    records = _distribution_records(authority["package_map"])
    records.append(SimpleNamespace(metadata={"Name": "pandas.market_calendars"}, version="2.1.4"))
    result = checker.check_live_package_set(authority["package_map"], records)
    assert result == {
        "status": "FAIL",
        "reason": "CURRENT_AUTHORITY_INSTALLED_METADATA_DUPLICATE",
    }


def test_malformed_metadata_fails_closed() -> None:
    authority = checker.resolve_current_authority()
    records = _distribution_records(authority["package_map"])
    records[0] = SimpleNamespace(metadata={}, version="1.0.0")
    result = checker.check_live_package_set(authority["package_map"], records)
    assert result == {
        "status": "FAIL",
        "reason": "CURRENT_AUTHORITY_INSTALLED_METADATA_MALFORMED",
    }


def test_missing_current_authority_fails_closed(tmp_path: Path) -> None:
    state = checker.PROJECT_STATE_PATH.read_text(encoding="utf-8").replace(
        "CURRENT_PROTECTED_ENVIRONMENT_STUDY=V13_PROTECTED_XLSX_ENVIRONMENT_SUCCESSOR",
        "CURRENT_PROTECTED_ENVIRONMENT_STUDY=",
        1,
    )
    state_path = tmp_path / "PROJECT_STATE.md"
    state_path.write_text(state, encoding="utf-8")
    result = checker.resolve_current_authority(state_path=state_path)
    assert result["status"] == "FAIL"
    assert result["reason"] == "CURRENT_AUTHORITY_STATE_VALUE_MISMATCH"


def test_stale_promotion_review_status_fails_closed(tmp_path: Path) -> None:
    state = checker.PROJECT_STATE_PATH.read_text(encoding="utf-8").replace(
        "V13_XLSX_FINAL_PROMOTION_REVIEW_STATUS=PASS",
        "V13_XLSX_FINAL_PROMOTION_REVIEW_STATUS=AWAITING_GPT_EXACT_SHA_REVIEW",
        1,
    )
    state_path = tmp_path / "PROJECT_STATE.md"
    state_path.write_text(state, encoding="utf-8")
    assert checker.resolve_current_authority(state_path=state_path) == {
        "status": "FAIL", "reason": "CURRENT_AUTHORITY_STATE_VALUE_MISMATCH",
    }


def test_ambiguous_current_authority_fails_closed(tmp_path: Path) -> None:
    state_path = tmp_path / "PROJECT_STATE.md"
    state_path.write_text(
        checker.PROJECT_STATE_PATH.read_text(encoding="utf-8")
        + "\nCURRENT_PROTECTED_ENVIRONMENT_STUDY=V13_PROTECTED_XLSX_ENVIRONMENT_SUCCESSOR\n",
        encoding="utf-8",
    )
    result = checker.resolve_current_authority(state_path=state_path)
    assert result["status"] == "FAIL"
    assert result["reason"] == "CURRENT_AUTHORITY_STATE_KEY_AMBIGUOUS"


def test_current_lock_drift_fails_closed(tmp_path: Path) -> None:
    lock_path = tmp_path / checker.V13_FINAL_LOCK_PATH.name
    lock_path.write_text(_real_lock_text().replace("scipy==1.18.1", "scipy==1.18.0"), encoding="utf-8")
    result = checker.resolve_current_authority(lock_path=lock_path)
    assert result["status"] == "FAIL"
    assert result["reason"] == "V13_AUTHORITY_WORKING_BLOB_MISMATCH"


def test_current_artifact_normalized_identity_is_required(monkeypatch) -> None:
    original = checker._working_blob_sha1

    def wrong_lock(repo_root: Path, relative_name: str, path: Path) -> str | None:
        if relative_name == checker.V13_FINAL_LOCK_PATH.name:
            return "0" * 40
        return original(repo_root, relative_name, path)

    monkeypatch.setattr(checker, "_working_blob_sha1", wrong_lock)
    result = checker.resolve_current_authority()
    assert result == {"status": "FAIL", "reason": "V13_AUTHORITY_WORKING_BLOB_MISMATCH",
                      "artifact": "final_lock"}


def test_wrong_interpreter_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(checker.sys, "executable", str(checker.REPO_ROOT / ".venv" / "Scripts" / "python.exe"))
    result = checker.check_interpreter_identity()
    assert result["status"] == "FAIL"
    assert result["failure_class"] == "PRE_GATE_WRONG_PYTHON_ENVIRONMENT"


def test_wrong_python_patch_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(checker.sys, "version_info", (3, 13, 0))
    result = checker.check_interpreter_identity()
    assert result["status"] == "FAIL"
    assert result["python_patch_match"] is False
    assert result["failure_class"] == "PRE_GATE_WRONG_PYTHON_ENVIRONMENT"


def test_wrong_platform_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(checker.platform, "system", lambda: "Linux")
    result = checker.check_interpreter_identity()
    assert result["status"] == "FAIL"
    assert result["platform_match"] is False
    assert result["failure_class"] == "PRE_GATE_WRONG_PYTHON_ENVIRONMENT"


def test_package_drift_fails_closed() -> None:
    packages = checker.resolve_current_authority()["package_map"]
    drifted = dict(packages)
    drifted["lightgbm"] = "4.5.0"
    result = checker.check_live_package_set(packages, _distribution_records(drifted))
    assert result["status"] == "FAIL"
    assert result["reason"] == "CURRENT_AUTHORITY_PACKAGE_SET_MISMATCH"
    assert "lightgbm" in result["version_mismatches"]


def test_exact_29_package_isolated_observation_passes() -> None:
    packages = checker.resolve_current_authority()["package_map"]
    result = checker._validate_child_package_set(packages, _isolated_evidence(packages))
    assert result == {"status": "PASS", "package_count": 29}


def test_isolated_child_command_binds_canonical_interpreter_and_isolation(monkeypatch) -> None:
    packages = checker.resolve_current_authority()["package_map"]
    fake_result = SimpleNamespace(
        returncode=0,
        stdout=json.dumps(_isolated_evidence(packages)),
        stderr="",
    )
    with mock.patch.object(checker.subprocess, "run", return_value=fake_result) as run:
        result = checker._run_isolated_observer()
    command = run.call_args.args[0]
    assert command[0] == str(checker.CANONICAL_INTERPRETER)
    assert "-I" in command
    assert "-B" in command
    assert command[command.index("-c") + 1] == checker._isolated_child_script()
    assert "spec_from_file_location" in command[command.index("-c") + 1]


def test_isolated_child_launch_nonzero_and_malformed_output_fail_closed() -> None:
    with mock.patch.object(checker.subprocess, "run", side_effect=OSError("missing")):
        assert checker._run_isolated_observer() == {
            "status": "FAIL",
            "reason": "CURRENT_AUTHORITY_CHILD_LAUNCH_FAILED",
        }
    with mock.patch.object(
        checker.subprocess,
        "run",
        return_value=SimpleNamespace(returncode=1, stdout="", stderr=""),
    ):
        assert checker._run_isolated_observer()["reason"] == "CURRENT_AUTHORITY_CHILD_NONZERO_EXIT"
    with mock.patch.object(
        checker.subprocess,
        "run",
        return_value=SimpleNamespace(returncode=0, stdout="not-json", stderr=""),
    ):
        assert checker._run_isolated_observer()["reason"] == "CURRENT_AUTHORITY_CHILD_JSON_INVALID"


def test_documented_direct_cli_does_not_require_repository_root_on_sys_path(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, str(checker.REPO_ROOT / "scripts" / "check_current_protected_environment.py")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "ModuleNotFoundError" not in result.stderr
    assert "No module named 'scripts'" not in result.stderr


def test_child_json_extra_or_missing_fields_fails_closed() -> None:
    packages = checker.resolve_current_authority()["package_map"]
    evidence = _isolated_evidence(packages)
    evidence.pop("pdf_probe")
    assert checker._validate_isolated_child_json(evidence)[1] == "CURRENT_AUTHORITY_CHILD_JSON_SCHEMA_INVALID"
    evidence = _isolated_evidence(packages)
    evidence["unexpected"] = True
    assert checker._validate_isolated_child_json(evidence)[1] == "CURRENT_AUTHORITY_CHILD_JSON_SCHEMA_INVALID"


def test_child_package_missing_extra_version_duplicate_and_malformed_fail_closed() -> None:
    packages = checker.resolve_current_authority()["package_map"]
    missing = dict(packages)
    missing.pop("scipy")
    assert checker._validate_child_package_set(packages, _isolated_evidence(missing))["reason"] == "CURRENT_AUTHORITY_PACKAGE_SET_MISMATCH"
    extra = dict(packages)
    extra["unexpected-package"] = "1.0.0"
    assert checker._validate_child_package_set(packages, _isolated_evidence(extra))["reason"] == "CURRENT_AUTHORITY_PACKAGE_SET_MISMATCH"
    drift = dict(packages)
    drift["lightgbm"] = "4.5.0"
    assert checker._validate_child_package_set(packages, _isolated_evidence(drift))["reason"] == "CURRENT_AUTHORITY_PACKAGE_SET_MISMATCH"
    duplicate = _isolated_evidence(packages)
    duplicate["packages"].append({"name": "pandas.market_calendars", "version": "2.1.4"})
    assert checker._validate_child_package_set(packages, duplicate)["reason"] == "CURRENT_AUTHORITY_INSTALLED_METADATA_DUPLICATE"
    malformed = _isolated_evidence(packages, package_observation_status="FAIL", package_failure="MALFORMED_METADATA")
    assert checker._validate_child_package_set(packages, malformed)["reason"] == "MALFORMED_METADATA"


def test_current_readiness_does_not_run_pip_when_authority_or_interpreter_fails(monkeypatch) -> None:
    monkeypatch.setattr(checker, "resolve_current_authority", lambda: {"status": "FAIL", "reason": "ambiguous"})
    monkeypatch.setattr(checker, "check_interpreter_identity", lambda: {"status": "FAIL"})
    with mock.patch.object(checker.subprocess, "run") as run:
        result = checker.run_current_readiness()
    assert result["CURRENT_ENVIRONMENT_READY"] is False
    run.assert_not_called()


def test_pdf_probe_pass_is_required_for_current_readiness(monkeypatch) -> None:
    authority = checker.resolve_current_authority()
    monkeypatch.setattr(checker, "resolve_current_authority", lambda: authority)
    monkeypatch.setattr(checker, "check_interpreter_identity", lambda: {"status": "PASS"})
    evidence = _isolated_evidence(authority["package_map"])
    evidence["status"] = "FAIL"
    evidence["pdf_probe"]["status"] = "BROKEN"
    monkeypatch.setattr(checker, "_run_isolated_observer", lambda: {"status": "PASS", "evidence": evidence})
    result = checker.run_current_readiness()
    assert result["PDF_OPERATIONAL_PROBE"]["status"] == "FAIL"
    assert result["CURRENT_ENVIRONMENT_READY"] is False


def test_pdf_probe_pass_allows_current_readiness(monkeypatch) -> None:
    authority = checker.resolve_current_authority()
    monkeypatch.setattr(checker, "resolve_current_authority", lambda: authority)
    monkeypatch.setattr(checker, "check_interpreter_identity", lambda: {"status": "PASS"})
    evidence = _isolated_evidence(authority["package_map"])
    monkeypatch.setattr(checker, "_run_isolated_observer", lambda: {"status": "PASS", "evidence": evidence})
    result = checker.run_current_readiness()
    assert result["CURRENT_ENVIRONMENT_READY"] is True
    assert result["PRODUCTION_XLSX_OPERATIONAL_PROBE"]["status"] == "PASS"


def test_xlsx_probe_failure_and_version_drift_fail_closed(monkeypatch) -> None:
    authority = checker.resolve_current_authority()
    monkeypatch.setattr(checker, "resolve_current_authority", lambda: authority)
    monkeypatch.setattr(checker, "check_interpreter_identity", lambda: {"status": "PASS"})
    for changed in ({"status": "FAIL"}, {"openpyxl_version": "3.1.4"}, {"et_xmlfile_version": "1.0.0"}):
        evidence = _isolated_evidence(authority["package_map"])
        evidence["xlsx_probe"].update(changed)
        monkeypatch.setattr(checker, "_run_isolated_observer", lambda evidence=evidence: {"status": "PASS", "evidence": evidence})
        result = checker.run_current_readiness()
        assert result["CURRENT_ENVIRONMENT_READY"] is False
        assert result["PRODUCTION_XLSX_OPERATIONAL_PROBE"]["status"] == "FAIL"


def test_current_readiness_contains_no_model_training_path() -> None:
    child = checker._isolated_child_script()
    assert ".fit(" not in child
    assert "v13_xlsx_readiness.py" in child
    assert "probe_production_xlsx_route()" in child


def test_pdf_probe_failure_exception_wrong_fixture_and_wrong_version_fail_closed() -> None:
    packages = checker.resolve_current_authority()["package_map"]
    failed = _isolated_evidence(packages)
    failed["pdf_probe"]["status"] = "BROKEN"
    assert checker._validate_child_pdf_probe(failed)["status"] == "FAIL"
    wrong_fixture = _isolated_evidence(packages)
    wrong_fixture["pdf_probe"]["fixture_sha256"] = "0" * 64
    assert checker._validate_child_pdf_probe(wrong_fixture)["reason"] == "CURRENT_AUTHORITY_PDF_PROBE_FIXTURE_IDENTITY_MISMATCH"
    wrong_version = _isolated_evidence(packages)
    wrong_version["pdf_probe"]["pdfplumber_version"] = "0.0.0"
    assert checker._validate_child_pdf_probe(wrong_version)["reason"] == "CURRENT_AUTHORITY_PDF_PROBE_VERSION_MISMATCH"
    exception_evidence = _isolated_evidence(packages)
    exception_evidence["pdf_probe"] = {"status": "FAIL", "fixture_sha256": None, "pdfplumber_version": None, "page_count": None}
    assert checker._validate_child_pdf_probe(exception_evidence)["status"] == "FAIL"
