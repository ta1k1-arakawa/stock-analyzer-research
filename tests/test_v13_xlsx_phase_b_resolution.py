"""Offline authorization and one-shot resolution boundary checks."""

import json
import hashlib
import subprocess
from pathlib import Path

import pytest

from scripts import check_current_protected_environment as current
from scripts import v13_xlsx_phase_b_resolution as phase_b
from scripts import v13_xlsx_successor_contract as successor


def test_approval_exact_and_frozen_bindings() -> None:
    record = json.loads((phase_b.ROOT / phase_b.AUTH).read_text(encoding="utf-8"))
    assert phase_b._blob((phase_b.ROOT / phase_b.AUTH).read_bytes()) == phase_b.AUTH_BLOB
    phase_b._approval(record)
    assert phase_b._bound_file(phase_b.PHASE_A, record["current_authority_lock"])
    assert phase_b._bound_file(phase_b.PHASE_A, record["successor_direct_spec"])
    assert record["one_shot"] and not record["consumed"]
    assert not record["candidate_installation_allowed"]
    assert record["official_index_url"] == "https://pypi.org/simple"
    changed = dict(record, consumed=True)
    with pytest.raises(ValueError, match="AUTH_SCOPE_INVALID"):
        phase_b._approval(changed)


@pytest.mark.parametrize("name", [current.CURRENT_AUTHORITY_LOCK_PATH, successor.SPEC.name])
def test_bound_file_accepts_only_git_normalized_identity(tmp_path: Path, monkeypatch, name: str) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitattributes").write_text(f"{name} text\n", encoding="ascii")
    canonical = b"package==1.0\nother==2.0\n"
    worktree = tmp_path / name
    worktree.write_bytes(canonical.replace(b"\n", b"\r\n"))
    expected = phase_b._blob(canonical)
    binding = {"path": name, "git_blob_sha1": expected,
               "sha256": hashlib.sha256(canonical).hexdigest()}
    assert worktree.read_bytes() != canonical

    def fake_git(*args: str) -> bytes:
        if args[0] == "show":
            return canonical
        return subprocess.run(["git", "-C", str(tmp_path), *args],
                              capture_output=True, check=True).stdout

    monkeypatch.setattr(phase_b, "ROOT", tmp_path)
    monkeypatch.setattr(phase_b, "_git", fake_git)
    assert phase_b._bound_file("a" * 40, binding) == canonical
    assert current._working_blob_sha1(tmp_path, name, worktree) == expected

    worktree.write_bytes(b"package==1.1\r\nother==2.0\r\n")
    with pytest.raises(ValueError, match="WORKTREE_BLOB_MISMATCH"):
        phase_b._bound_file("a" * 40, binding)
    assert current._working_blob_sha1(tmp_path, name, worktree) != expected


def test_current_authority_and_unresolved_successor_spec() -> None:
    authority = current.resolve_historical_v10c_authority()
    assert authority["status"] == "PASS"
    assert authority["package_count"] == 27
    base = successor.validate_direct_spec()
    assert len(base) == 27
    assert "openpyxl" not in base
    assert "et-xmlfile" not in base


def test_rehearsal_has_no_side_effects(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["phase_b"])
    monkeypatch.setattr(phase_b, "preflight", lambda *a, **k: pytest.fail("preflight called"))
    monkeypatch.setattr(phase_b.subprocess, "run", lambda *a, **k: pytest.fail("subprocess called"))
    assert phase_b.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["package_index_requests"] == result["wheel_downloads"] == 0
    assert result["environment_mutations"] == 0


def test_canonical_operation_identity_and_consumption(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(phase_b.sys, "platform", "win32")
    monkeypatch.setattr(phase_b, "_local_state_base", lambda: tmp_path)
    monkeypatch.setattr(phase_b, "preflight", lambda *a, **k: {"authorization_blob": phase_b.AUTH_BLOB})
    root = phase_b._canonical_root(phase_b.AUTH_BLOB)
    assert root == phase_b._canonical_root(phase_b.AUTH_BLOB)
    assert root.parent == tmp_path / "stock-analyzer" / "protected-execution" / "v13-xlsx-phase-b"

    calls = []

    def resolver_boundary(*args, **kwargs):
        calls.append(1)
        attempt = json.loads((root / "attempt.json").read_text(encoding="utf-8"))
        assert attempt["status"] == "CONSUMED_PENDING"
        assert attempt["authorization_blob"] == phase_b.AUTH_BLOB
        raise RuntimeError("synthetic resolver stop")

    monkeypatch.setattr(phase_b.subprocess, "run", resolver_boundary)
    with pytest.raises(RuntimeError, match="synthetic resolver stop"):
        phase_b.execute("b" * 40)
    assert calls == [1]
    assert root.is_dir()
    monkeypatch.setattr(phase_b.subprocess, "run", lambda *a, **k: pytest.fail("resolver called twice"))
    with pytest.raises(ValueError, match="ONE_SHOT_ALREADY_STARTED"):
        phase_b.execute("b" * 40)
    assert calls == [1]


@pytest.mark.parametrize("state", ["empty", "malformed", "completed"])
def test_existing_canonical_state_blocks_without_deletion(tmp_path: Path, monkeypatch, state: str) -> None:
    monkeypatch.setattr(phase_b.sys, "platform", "win32")
    monkeypatch.setattr(phase_b, "_local_state_base", lambda: tmp_path)
    monkeypatch.setattr(phase_b, "preflight", lambda *a, **k: {"authorization_blob": phase_b.AUTH_BLOB})
    root = phase_b._canonical_root(phase_b.AUTH_BLOB)
    root.parent.mkdir(parents=True)
    root.mkdir()
    if state != "empty":
        (root / "receipt.json").write_text("{" if state == "malformed" else '{"status":"PASS_CONSUMED"}', encoding="utf-8")
    with pytest.raises(ValueError, match="ONE_SHOT_ALREADY_STARTED"):
        phase_b.execute("b" * 40)
    assert root.exists()
    assert (root / "receipt.json").exists() == (state != "empty")


def test_caller_cannot_select_another_root(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(phase_b, "_local_state_base", lambda: tmp_path)
    original = phase_b._canonical_root(phase_b.AUTH_BLOB)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "alternate"))
    assert phase_b._canonical_root(phase_b.AUTH_BLOB) == original
    with pytest.raises(TypeError):
        phase_b.execute("b" * 40, tmp_path / "alternate")
    monkeypatch.setattr("sys.argv", ["phase_b", "--execute", "--execution-head", "b" * 40,
                                    "--operation-root", str(tmp_path / "alternate")])
    assert phase_b.main() == 1
    output = capsys.readouterr()
    assert json.loads(output.out) == {"status": "FAIL", "reason": "ARGUMENTS_INVALID"}
    assert str(tmp_path) not in output.out + output.err
    wrapper = (phase_b.ROOT / "scripts/run_v13_xlsx_phase_b_resolution_direct_windows.ps1").read_text(encoding="utf-8")
    assert "OperationRoot" not in wrapper and "--operation-root" not in wrapper


def test_unsafe_local_state_fails_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(phase_b, "_local_state_base", lambda: Path("relative-local"))
    with pytest.raises(ValueError, match="LOCAL_STATE_BASE_INVALID"):
        phase_b._canonical_root(phase_b.AUTH_BLOB)
    monkeypatch.setattr(phase_b, "_local_state_base", lambda: tmp_path)
    with pytest.raises(ValueError, match="AUTH_ARTIFACT_IDENTITY_MISMATCH"):
        phase_b._canonical_root("a" * 40)
    root = phase_b._canonical_root(phase_b.AUTH_BLOB)
    root.parent.parent.mkdir(parents=True)
    root.parent.write_text("ambiguous", encoding="utf-8")
    with pytest.raises(ValueError, match="LOCAL_STATE_PATH_INVALID"):
        phase_b._prepare_operation_parent(root)
    assert root.parent.read_text(encoding="utf-8") == "ambiguous"
    monkeypatch.setattr(phase_b, "_local_state_base", lambda: phase_b.ROOT)
    with pytest.raises(ValueError, match="GOVERNED_PATH_OVERLAP"):
        phase_b._prepare_operation_parent(phase_b._canonical_root(phase_b.AUTH_BLOB))


def test_resolver_command_is_download_only() -> None:
    source = (phase_b.ROOT / "scripts/v13_xlsx_phase_b_resolution.py").read_text(encoding="utf-8")
    assert '"-m", "pip", "download"' in source
    assert '"--index-url", INDEX' in source
    assert '"--constraint", str(ROOT / current.CURRENT_AUTHORITY_LOCK_PATH)' in source
    assert '"pip", "install"' not in source


def test_dirty_tree_blocks_before_remote_or_review(monkeypatch) -> None:
    observed = []

    def fake_git(*args):
        observed.append(args)
        if args == ("branch", "--show-current"):
            return (phase_b.BRANCH + "\n").encode()
        if args == ("rev-parse", "HEAD"):
            return ("a" * 40 + "\n").encode()
        if args == ("status", "--porcelain", "--untracked-files=all"):
            return b" M PROJECT_STATE.md\n"
        pytest.fail("later Git operation reached")

    monkeypatch.setattr(phase_b, "_git", fake_git)
    monkeypatch.setattr(phase_b, "_review_pass", lambda head: pytest.fail("review lookup reached"))
    with pytest.raises(ValueError, match="DIRTY_WORKTREE"):
        phase_b.preflight("a" * 40)
    assert observed == [("branch", "--show-current"), ("rev-parse", "HEAD"),
                        ("status", "--porcelain", "--untracked-files=all")]


@pytest.mark.parametrize("stage,code", [
    ("branch", "BRANCH_MISMATCH"),
    ("head", "HEAD_MISMATCH"),
    ("remote", "REMOTE_HEAD_MISMATCH"),
    ("review", "AUTHORIZATION_COMMIT_GPT_PASS_MISSING"),
])
def test_repository_and_review_gates_fail_closed(monkeypatch, stage: str, code: str) -> None:
    head = "a" * 40
    responses = {
        ("branch", "--show-current"): (phase_b.BRANCH + "\n").encode(),
        ("rev-parse", "HEAD"): (head + "\n").encode(),
        ("status", "--porcelain", "--untracked-files=all"): b"",
        ("ls-remote", "origin", f"refs/heads/{phase_b.BRANCH}"):
            (f"{head}\trefs/heads/{phase_b.BRANCH}\n").encode(),
        ("merge-base", phase_b.PHASE_A, head): (phase_b.PHASE_A + "\n").encode(),
    }
    if stage == "branch":
        responses[("branch", "--show-current")] = b"other\n"
    elif stage == "head":
        responses[("rev-parse", "HEAD")] = ("b" * 40 + "\n").encode()
    elif stage == "remote":
        responses[("ls-remote", "origin", f"refs/heads/{phase_b.BRANCH}")] = b""

    def fake_git(*args: str) -> bytes:
        if args not in responses:
            pytest.fail("artifact access reached")
        return responses[args]

    monkeypatch.setattr(phase_b, "_git", fake_git)
    monkeypatch.setattr(phase_b, "_review_pass", lambda reviewed: stage != "review")
    with pytest.raises(ValueError, match=code):
        phase_b.preflight(head)


def test_review_pass_requires_exact_sha_and_issue(monkeypatch) -> None:
    class Result:
        stdout = json.dumps({"comments": [{"author": {"login": "ta1k1-arakawa"},
            "body": "MODEL=GPT-5.6_SOL\nMODE=GPT_EXACT_SHA_INDEPENDENT_REVIEW\n"
                    "GITHUB_ISSUE=100\nREVIEWED_SHA=" + "a" * 40 + "\nRESULT=PASS"}]}).encode()

    monkeypatch.setattr(phase_b.subprocess, "run", lambda *a, **k: Result())
    assert phase_b._review_pass("a" * 40)
    assert not phase_b._review_pass("b" * 40)
