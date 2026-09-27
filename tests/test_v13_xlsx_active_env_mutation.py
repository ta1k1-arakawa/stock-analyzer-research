"""Synthetic repository-only tests; never touch the active or candidate venv."""
import ast
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import v13_xlsx_active_env_mutation as m


def test_closed_authorization_and_exact_bindings():
    actual = json.loads(m.AUTH.read_bytes(), object_pairs_hook=m.realization.unique)
    assert actual == m.expected_authorization()
    assert actual["active_environment_mutation_allowed"] is False
    assert actual["active_environment_mutation_one_shot"] is True
    assert actual["active_environment_mutation_consumed"] is False
    assert actual["human_promotion_approval_comment_id"] == 5851057309
    assert actual["predecessor_gpt_review_comment_id"] == 5848157902
    assert all(actual[k] is False for k in (
        "successor_promoted", "current_authority_changed", "package_index_reaccess_allowed",
        "dependency_reresolution_allowed", "new_wheel_download_allowed",
        "second_isolated_candidate_realization_allowed",
        "jpx_yahoo_private_selected500_model_backtest_aq_paper_live_allowed"))


def test_lock_delta_and_safe_result_are_frozen_repository_evidence():
    assert m.freeze.validate_freeze()["status"] == "PASS"
    assert m.realization_result.validate_result()["status"] == "PASS"
    current = dict(line.split("==", 1) for line in m.current.CURRENT_LOCK_PATH.read_text().splitlines())
    candidate = dict(line.split("==", 1) for line in m.freeze.LOCK.read_text().splitlines())
    assert len(current) == 27 and len(candidate) == 29
    assert {k: v for k, v in candidate.items() if k not in current} == m.DELTA
    assert all(candidate[k] == v for k, v in current.items())


def test_wrong_process_interpreter_fails_pre_gate():
    with patch.object(m.realization, "canonical_process_interpreter", side_effect=ValueError("WRONG")):
        with pytest.raises(ValueError, match="WRONG"):
            m.canonical_interpreter()


def test_fixed_attempt_root_and_one_shot():
    with tempfile.TemporaryDirectory(dir=m.ROOT.parent) as folder, patch.object(
            m.phase_b, "_local_state_base", return_value=Path(folder)):
        root = m.attempt_root()
        assert root.name == m.ATTEMPT_NAME
        assert "v13-xlsx-active-mutation" in root.parts
        m.precheck_attempt(root)
        root.parent.mkdir(parents=True)
        root.mkdir()
        with pytest.raises(ValueError, match="ONE_SHOT_ALREADY_STARTED"):
            m.precheck_attempt(root)


def test_delta_selection_and_extra_wheel_rejection():
    wheels = tuple({"name": name, "version": version, "filename": name + ".whl"}
                   for name, version in m.DELTA.items())
    assert tuple(path.name for path in m.delta_wheels(m.ROOT, wheels)) == (
        "et-xmlfile.whl", "openpyxl.whl")
    tampered = (dict(wheels[0], version="9.9"), wheels[1])
    with pytest.raises(ValueError, match="DELTA_WHEELS_INVALID"):
        m.delta_wheels(m.ROOT, tampered)
    with pytest.raises(Exception):
        m.verify_wheelhouse(m.ROOT / "nonexistent-wheelhouse", [])


def test_exact_29_metadata_and_pdf_gate():
    pins = dict(line.split("==", 1) for line in m.freeze.LOCK.read_text().splitlines())
    records = [{"name": name, "version": version} for name, version in pins.items()]
    child = {"package_observation_status": "PASS", "packages": records}
    assert m.current._validate_child_package_set(pins, child)["status"] == "PASS"
    for bad in (records[:-1], records + [records[0]],
                [dict(records[0], version="0"), *records[1:]]):
        assert m.current._validate_child_package_set(pins, dict(child, packages=bad))["status"] == "FAIL"
    probe = {"status": m.current.PDF_PROBE_PASS,
             "fixture_sha256": m.current.PDF_PROBE_EXPECTED_FIXTURE_SHA256,
             "pdfplumber_version": m.current.PDF_PROBE_REQUIRED_PDFPLUMBER_VERSION,
             "page_count": m.current.PDF_PROBE_EXPECTED_PAGE_COUNT}
    assert m.current._validate_child_pdf_probe({"pdf_probe": probe})["status"] == "PASS"
    assert "probe_production_xlsx_route" in m.realization.CHILD


def test_postvalidation_keeps_package_pdf_and_production_xlsx_without_training():
    source = Path(m.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                   "training" in node.name.lower() for node in ast.walk(tree))
    assert "ML_CHILD" not in source and ".fit(" not in source
    assert '"ml_readiness"' not in source
    assert ".fit(" not in m.realization.CHILD
    assert "probe_production_xlsx_route" in m.realization.CHILD
    package_map = dict(line.split("==", 1) for line in m.freeze.LOCK.read_text().splitlines())
    child = {"packages": [{"name": name, "version": version}
                          for name, version in package_map.items()]}
    with patch.object(m.current, "_run_isolated_observer", return_value={"status": "PASS", "evidence": child}), \
         patch.object(m.current, "_validate_child_identity", return_value={"status": "PASS"}) as identity, \
         patch.object(m.current, "_validate_child_package_set", return_value={"status": "PASS"}) as packages, \
         patch.object(m.current, "_validate_child_pdf_probe", return_value={"status": "PASS"}) as pdf, \
         patch.object(m.realization, "inspect_candidate") as xlsx, \
         patch.object(m.subprocess, "run", side_effect=AssertionError("unexpected child")):
        m.postvalidate()
    identity.assert_called_once_with(child)
    packages.assert_called_once_with(package_map, child)
    pdf.assert_called_once_with(child)
    xlsx.assert_called_once_with(m.current.CANONICAL_INTERPRETER, package_map)


def test_no_caller_selected_source_or_target_and_no_network_pip_flags():
    source = Path(m.__file__).read_text(encoding="utf-8")
    assert 'parser.add_argument("--execution-head")' in source
    assert 'parser.add_argument("--execute"' in source
    assert 'parser.add_argument("--wheelhouse"' not in source
    assert 'parser.add_argument("--target"' not in source
    assert 'parser.add_argument("--attempt-root"' not in source
    assert '"--no-index"' in source and '"--no-deps"' in source
    assert '"--no-cache-dir"' in source
    assert 'root.mkdir(exist_ok=False)' in source
    assert '"MUTATED_VALIDATED_NOT_YET_PROMOTED"' in source


@pytest.mark.parametrize("root_exists,expected", [
    (False, "PRE_GATE_FAILURE"),
    (True, "CONSUMED_ACTIVE_ENV_MUTATION_FAILURE"),
])
def test_boundary_failure_classification(root_exists, expected, capsys):
    with patch.object(m.sys, "argv", ["runner", "--execute", "--execution-head", "a" * 40]), \
         patch.object(m.sys, "platform", "win32"), \
         patch.object(m, "mutate", side_effect=ValueError("SYNTHETIC_FAILURE")), \
         patch.object(m, "attempt_root", return_value=Path("C:/synthetic/fixed-attempt")), \
         patch.object(m.os.path, "lexists", return_value=root_exists):
        assert m.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["failure_class"] == expected
    assert result["authorization_reusable"] is (not root_exists)
