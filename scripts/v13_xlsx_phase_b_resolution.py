"""One-shot, Direct-Windows-only XLSX successor wheel resolution.

The default command is an offline rehearsal. No candidate is installed here.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from pathlib import Path

from scripts import check_current_protected_environment as current
from scripts import v13_xlsx_successor_contract as successor
from scripts.v10c_t0_ml_environment_contract import (
    ContractValidationError, _inspect_wheel_file_metadata, _marker_applies,
    _parse_requirement, _version_satisfies, validate_wheel_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "v13-conditional-cross-sectional-short-horizon"
PHASE_A = "5280e95915c9b194147a61f1156fb045e0abc48e"
AUTH = Path("docs/v13/V13_XLSX_SUCCESSOR_PHASE_B_RESOLUTION_AUTHORIZATION.json")
INDEX = "https://pypi.org/simple"
SHA = re.compile(r"[0-9a-f]{40}\Z")
AUTH_BLOB = "6826344839b5ba738c74e371bbccf9ab06346207"


def _git(*args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True)
    return result.stdout


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _blob(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def _bound_file(head: str, binding: dict) -> bytes:
    path = binding["path"]
    _require(path in {current.CURRENT_AUTHORITY_LOCK_PATH, successor.SPEC.name}, "BOUND_PATH_INVALID")
    canonical = _git("show", f"{head}:{path}")
    worktree_blob = _git("hash-object", "--path", path, "--", str(ROOT / path)).decode("ascii").strip()
    _require(worktree_blob == _blob(canonical), "WORKTREE_BLOB_MISMATCH")
    _require(_blob(canonical) == binding["git_blob_sha1"], "GIT_BLOB_MISMATCH")
    _require(hashlib.sha256(canonical).hexdigest() == binding["sha256"], "SHA256_MISMATCH")
    _require(canonical == _git("show", f"{PHASE_A}:{path}"), "PHASE_A_FILE_MISMATCH")
    return canonical


def _review_pass(head: str) -> bool:
    result = subprocess.run(
        ["gh", "issue", "view", "100", "--repo", "ta1k1-arakawa/stock-analyzer",
         "--json", "comments"], capture_output=True, check=True,
    )
    comments = json.loads(result.stdout)["comments"]
    for comment in comments:
        body = comment.get("body", "")
        lines = set(body.splitlines())
        if (comment.get("author", {}).get("login") == "ta1k1-arakawa"
                and "MODEL=GPT-5.6_SOL" in lines
                and "MODE=GPT_EXACT_SHA_INDEPENDENT_REVIEW" in lines
                and "GITHUB_ISSUE=100" in lines
                and f"REVIEWED_SHA={head}" in lines
                and "RESULT=PASS" in lines):
            return True
    return False


def _approval(record: dict) -> None:
    expected = {
        "schema_version": "V13_XLSX_PHASE_B_RESOLUTION_AUTHORIZATION_V1",
        "status": "AUTHORIZED", "authoritative_branch": BRANCH,
        "github_issue": 100, "predecessor_issue": 99, "predecessor_gpt_result": "PASS",
        "approved_phase_a_sha": PHASE_A,
        "human_approval_text": "V13 XLSX successor Phase B の1回限りの package-index resolution を承認します．",
        "historical_20_package_authority_current": False,
        "one_shot": True, "consumed": False,
        "authorization_reusable_after_success": False,
        "package_index_resolution_approved": True,
        "official_index_url": INDEX,
        "metadata_distribution_wheel_retrieval_and_content_lock_allowed": True,
        "current_27_direct_pins_preserved_exactly": True,
        "openpyxl_direct_version": "UNRESOLVED_BY_RESOLVER",
        "transitive_closure": "RESOLVER_DERIVED_ONLY",
        "candidate_installation_allowed": False,
        "active_venv_real_execution_mutation_allowed": False,
        "successor_promotion_allowed": False,
        "jpx_yahoo_public_data_lock_execution_allowed": False,
        "private_read_allowed": False,
        "selected_500_construction_allowed": False,
        "model_fit_backtest_aq_paper_live_trading_allowed": False,
        "locked_jpx_listed_sha256": "fff94dd14057c8bfa36a3fbabd8e228bbed63751c7ecd10c1a8281f5385fcb78",
        "locked_jpx_refetch_allowed": False, "locked_jpx_reuse_required": True,
        "public_datalock_reauthorization_required": False,
        "production_xlsx_readiness": "NOT_YET_PROVEN",
    }
    _require(set(record) == set(expected) | {"current_authority_lock", "successor_direct_spec"}, "AUTH_SCHEMA_INVALID")
    _require(all(type(record[k]) is type(v) and record[k] == v for k, v in expected.items()), "AUTH_SCOPE_INVALID")
    _require(record["current_authority_lock"] == {
        "path": current.CURRENT_AUTHORITY_LOCK_PATH,
        "git_blob_sha1": current.CURRENT_AUTHORITY_LOCK_BLOB_SHA1,
        "sha256": "f38dd4c7319465bb7e6ff429e8dff4a476d9966c744b19e50264dcc0b18e8300",
        "package_count": 27,
    }, "AUTH_LOCK_INVALID")
    _require(record["successor_direct_spec"] == {
        "path": successor.SPEC.name,
        "git_blob_sha1": "a238aef7c30ef3ba2632a12b4d746203d55bc138",
        "sha256": "c3373c96db07587e947f816504ff72383542e706e4b1cbb34ac38cbe710d918a",
    }, "AUTH_SPEC_INVALID")


def preflight(head: str, *, remote: bool = True) -> dict[str, str]:
    _require(bool(SHA.fullmatch(head)), "EXECUTION_HEAD_INVALID")
    _require(_git("branch", "--show-current").decode().strip() == BRANCH, "BRANCH_MISMATCH")
    _require(_git("rev-parse", "HEAD").decode().strip() == head, "HEAD_MISMATCH")
    _require(_git("status", "--porcelain", "--untracked-files=all") == b"", "DIRTY_WORKTREE")
    if remote:
        remote_line = _git("ls-remote", "origin", f"refs/heads/{BRANCH}").decode().strip()
        _require(remote_line == f"{head}\trefs/heads/{BRANCH}", "REMOTE_HEAD_MISMATCH")
    _require(_git("merge-base", PHASE_A, head).decode().strip() == PHASE_A, "PHASE_A_NOT_ANCESTOR")
    if remote:
        _require(_review_pass(head), "AUTHORIZATION_COMMIT_GPT_PASS_MISSING")
    auth_raw = _git("show", f"{head}:{AUTH.as_posix()}")
    _require(_blob(auth_raw) == AUTH_BLOB, "AUTH_ARTIFACT_IDENTITY_MISMATCH")
    _require((ROOT / AUTH).is_file(), "AUTH_ARTIFACT_MISSING")
    _require(_git("hash-object", "--", str(ROOT / AUTH)).decode().strip() == _blob(auth_raw),
             "AUTH_ARTIFACT_MISMATCH")
    record = json.loads(auth_raw)
    _approval(record)
    _bound_file(head, record["current_authority_lock"])
    _bound_file(head, record["successor_direct_spec"])
    authority = current.resolve_historical_v10c_authority()
    _require(authority["status"] == "PASS" and authority["package_count"] == 27, "CURRENT_AUTHORITY_INVALID")
    _require(len(successor.validate_direct_spec()) == 27, "DIRECT_SPEC_INVALID")
    _require(current.run_current_readiness()["CURRENT_ENVIRONMENT_READY"], "CURRENT_ENVIRONMENT_INVALID")
    return {"authorization_blob": _blob(auth_raw), "execution_head": head}


def _local_state_base() -> Path:
    # Query the Windows current-user known folder directly. LOCALAPPDATA is
    # process-controlled and could otherwise produce a second one-shot root.
    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    identity = GUID.from_buffer_copy(uuid.UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le)
    path = ctypes.c_wchar_p()
    api = ctypes.windll.shell32.SHGetKnownFolderPath
    api.argtypes = [ctypes.POINTER(GUID), ctypes.c_uint32, ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_wchar_p)]
    api.restype = ctypes.c_long
    result = api(ctypes.byref(identity), 0, None, ctypes.byref(path))
    _require(result == 0 and bool(path.value), "LOCAL_STATE_BASE_INVALID")
    try:
        return Path(path.value)
    finally:
        free = ctypes.windll.ole32.CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = None
        free(ctypes.cast(path, ctypes.c_void_p))


def _canonical_root(authorization_blob: str) -> Path:
    _require(authorization_blob == AUTH_BLOB, "AUTH_ARTIFACT_IDENTITY_MISMATCH")
    base = _local_state_base()
    _require(base.is_absolute() and not base.drive.startswith("\\\\"), "LOCAL_STATE_BASE_INVALID")
    _require(".." not in base.parts and "." not in base.parts, "LOCAL_STATE_BASE_AMBIGUOUS")
    _require(base.is_dir(), "LOCAL_STATE_BASE_INVALID")
    return base / "stock-analyzer" / "protected-execution" / "v13-xlsx-phase-b" / authorization_blob


def _safe_root(root: Path) -> None:
    _require(root.is_absolute() and ".." not in root.parts and "." not in root.parts,
             "OPERATION_ROOT_INVALID")
    _require(not os.path.lexists(root), "ONE_SHOT_ALREADY_STARTED")
    node = root.parent
    while True:
        if os.path.lexists(node):
            mode = os.lstat(node)
            _require(not stat.S_ISLNK(mode.st_mode) and not (getattr(mode, "st_file_attributes", 0) & 0x400),
                     "REPARSE_PATH_BLOCKED")
            _require(stat.S_ISDIR(mode.st_mode), "LOCAL_STATE_PATH_INVALID")
        if node == node.parent:
            break
        node = node.parent
    real = Path(os.path.realpath(root))
    repo = Path(os.path.realpath(ROOT))
    _require(not real.is_relative_to(repo) and not repo.is_relative_to(real), "GOVERNED_PATH_OVERLAP")


def _prepare_operation_parent(root: Path) -> None:
    # Parent directories are safe to create before the one-shot boundary.
    _safe_root(root)
    missing = []
    node = root.parent
    while not os.path.lexists(node):
        missing.append(node)
        node = node.parent
    for node in reversed(missing):
        node.mkdir()
        _safe_root(root)


def _write_json(path: Path, value: dict) -> None:
    raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def inspect_wheels(wheelhouse: Path, base: dict[str, str]) -> dict:
    files = list(wheelhouse.iterdir())
    _require(bool(files) and all(f.is_file() and not f.is_symlink() and f.suffix == ".whl" for f in files), "WHEELHOUSE_INVALID")
    wheels = sorted((_inspect_wheel_file_metadata(f) for f in files), key=lambda w: w["name"])
    validate_wheel_manifest([{k: w[k] for k in ("name", "version", "filename", "sha256")} for w in wheels])
    packages = {w["name"]: w["version"] for w in wheels}
    _require(len(packages) == len(wheels), "DUPLICATE_DISTRIBUTION")
    _require(all(packages.get(k) == v for k, v in base.items()), "CURRENT_PIN_DRIFT")
    _require("openpyxl" in packages, "OPENPYXL_MISSING")
    reachable, pending = set(), sorted(set(base) | {"openpyxl"})
    metadata = {w["name"]: w for w in wheels}
    while pending:
        name = pending.pop(0)
        if name in reachable:
            continue
        _require(name in metadata, "DEPENDENCY_MISSING")
        reachable.add(name)
        wheel = metadata[name]
        if wheel["requires_python"]:
            _require(_version_satisfies("3.12.10", wheel["requires_python"]), "PYTHON_VERSION_MISMATCH")
        for raw in wheel["requires_dist"]:
            dep, spec, marker, extras = _parse_requirement(raw)
            if not _marker_applies(marker):
                continue
            _require(extras is None and dep in packages, "DEPENDENCY_MISSING")
            _require(not spec or _version_satisfies(packages[dep], spec), "DEPENDENCY_VERSION_MISMATCH")
            pending.append(dep)
    _require(reachable == set(packages), "UNREACHABLE_DISTRIBUTION")
    return {
        "schema_version": "V13_XLSX_PHASE_B_CANDIDATE_V1",
        "status": "RESOLVED_NOT_INSTALLED",
        "resolved_package_count": len(packages), "artifact_count": len(wheels),
        "resolved_packages": [{"name": n, "version": packages[n]} for n in sorted(packages)],
        "resolved_wheels": [{k: w[k] for k in ("name", "version", "filename", "sha256")} for w in wheels],
        "dependency_metadata": [{"name": w["name"], "requires_dist": list(w["requires_dist"]), "requires_python": w["requires_python"]} for w in wheels],
    }


def execute(head: str) -> dict:
    _require(sys.platform == "win32", "DIRECT_WINDOWS_REQUIRED")
    binding = preflight(head)
    operation_root = _canonical_root(binding["authorization_blob"])
    _prepare_operation_parent(operation_root)
    _safe_root(operation_root)
    # mkdir is exclusive. If the process dies before attempt.json is durable,
    # the existing canonical root is still a non-reusable consumed state.
    operation_root.mkdir()
    _write_json(operation_root / "attempt.json", {
        "schema_version": "V13_XLSX_PHASE_B_ATTEMPT_V1", "status": "CONSUMED_PENDING",
        "execution_head": head, "authorization_blob": binding["authorization_blob"],
        "one_shot": True, "reusable": False, "package_installations": 0,
    })
    wheelhouse = operation_root / "wheelhouse"
    wheelhouse.mkdir()
    pip_log = operation_root / "resolver_pip.local.log"
    argv = [str(current.CANONICAL_INTERPRETER), "-m", "pip", "download", "--dest", str(wheelhouse),
            "--only-binary=:all:", "--no-cache-dir", "--disable-pip-version-check", "--no-input",
            "--progress-bar", "off", "--retries", "0", "--timeout", "15", "-vv", "--log", str(pip_log),
            "--index-url", INDEX, "--requirement", str(ROOT / successor.SPEC.name),
            "--constraint", str(ROOT / current.CURRENT_AUTHORITY_LOCK_PATH)]
    child_env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PIP_")}
    child_env["PIP_CONFIG_FILE"] = "NUL"
    with (operation_root / "resolver_stdout.local.txt").open("wb") as out, (operation_root / "resolver_stderr.local.txt").open("wb") as err:
        code = subprocess.run(argv, env=child_env, stdout=out, stderr=err, check=False).returncode
    _require(code == 0, "RESOLVER_FAILED_ONE_SHOT_CONSUMED")
    request_count = len(re.findall(rb'pypi\.org:443 "GET /simple/', pip_log.read_bytes()))
    _require(request_count > 0, "REQUEST_COUNT_UNOBSERVABLE")
    base = successor.validate_direct_spec()
    candidate = inspect_wheels(wheelhouse, base)
    candidate.update(execution_head=head, approved_phase_a_sha=PHASE_A,
                     authorization_blob=binding["authorization_blob"],
                     official_index_url=INDEX, resolver="pip download --only-binary=:all:",
                     package_index_request_count=request_count,
                     wheel_download_count=candidate["artifact_count"],
                     package_installations=0, active_environment_mutated=False,
                     successor_promoted=False, jpx_yahoo_requests=0, private_reads=0,
                     selected_500_constructed=False, model_fits=0, backtests=0,
                     aq_executions=0, trades=0)
    _write_json(operation_root / "candidate.json", candidate)
    raw = (operation_root / "candidate.json").read_bytes()
    receipt = {"schema_version": "V13_XLSX_PHASE_B_RECEIPT_V1", "status": "PASS_CONSUMED",
               "execution_head": head, "authorization_blob": binding["authorization_blob"],
               "candidate_sha256": hashlib.sha256(raw).hexdigest(),
               "package_count": candidate["resolved_package_count"], "artifact_count": candidate["artifact_count"],
               "package_index_request_count": request_count,
               "wheel_download_count": candidate["artifact_count"],
               "package_installations": 0, "active_environment_mutated": False,
               "successor_promoted": False, "reusable": False}
    _write_json(operation_root / "receipt.json", receipt)
    return receipt


def main() -> int:
    class SafeArgumentParser(argparse.ArgumentParser):
        def error(self, message: str) -> None:
            raise ValueError("ARGUMENTS_INVALID")

    parser = SafeArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--execution-head")
    try:
        args = parser.parse_args()
        if not args.execute:
            print(json.dumps({"rehearsal": True, "package_index_requests": 0, "wheel_downloads": 0,
                              "environment_mutations": 0, "private_reads": 0, "jpx_yahoo_requests": 0}))
            return 0
        _require(args.execution_head is not None, "EXPLICIT_INPUT_REQUIRED")
        print(json.dumps(execute(args.execution_head), sort_keys=True))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, ContractValidationError, KeyError, json.JSONDecodeError) as error:
        reason = str(error) if type(error) is ValueError else type(error).__name__
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", reason):
            reason = "EXECUTION_FAILED"
        print(json.dumps({"status": "FAIL", "reason": reason}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
