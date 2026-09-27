"""Issue 108 offline, one-shot in-place successor mutation. Inert on import."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import sysconfig
from pathlib import Path

from scripts import check_current_protected_environment as current
from scripts import v13_xlsx_phase_b_candidate_evidence as evidence
from scripts import v13_xlsx_phase_b_resolution as phase_b
from scripts import v13_xlsx_successor_freeze as freeze
from scripts import v13_xlsx_successor_isolated_realization as realization
from scripts import v13_xlsx_successor_realization_result as realization_result
from scripts.v10c_t0_ml_environment_contract import verify_wheelhouse

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "v13-conditional-cross-sectional-short-horizon"
PARENT = "8ff8811373696c723d1530d3bd5cf307c147450d"
AUTH = ROOT / "docs/v13/V13_XLSX_SUCCESSOR_ACTIVE_ENV_MUTATION_AUTHORIZATION.json"
SAFE = ROOT / "docs/v13/V13_XLSX_SUCCESSOR_ISOLATED_REALIZATION_SAFE_RESULT.json"
ATTEMPT_NAME = "V13_XLSX_ACTIVE_ENV_MUTATION_ATTEMPT_1"
APPROVAL_TEXT = ("V13 XLSX 29-package successor を current protected environment authority へ promotion する方針を承認します．"
                 "package-index再アクセス・新規wheel download・JPX/Yahoo/private access・selected500・model fit・backtest・A-Q・paper/live trading は承認しません．"
                 "active .venv-real-execution の変更がpromotionに必要な場合は，GPT review済みのpromotion手順に限定して承認します．")
DELTA = {"et-xmlfile": "2.0.0", "openpyxl": "3.1.5"}


def require(ok: bool, code: str) -> None:
    if not ok:
        raise ValueError(code)


def git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                            check=True, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    return result.stdout.strip()


def blob(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def reviewed(path: Path, expected_blob: str | None = None, expected_sha: str | None = None) -> bytes:
    rel = path.relative_to(ROOT).as_posix()
    raw = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{rel}"],
                         capture_output=True, check=True).stdout
    work = git("hash-object", "--path", rel, "--", str(path))
    require(work == blob(raw) and (expected_blob is None or work == expected_blob) and
            (expected_sha is None or hashlib.sha256(raw).hexdigest() == expected_sha),
            "REVIEWED_ARTIFACT_MISMATCH")
    return raw


def comment(comment_id: int, required: set[str]) -> None:
    result = subprocess.run(["gh", "api", f"repos/ta1k1-arakawa/stock-analyzer/issues/comments/{comment_id}"],
                            capture_output=True, check=True)
    value = json.loads(result.stdout, object_pairs_hook=realization.unique)
    require(value.get("user", {}).get("login") == "ta1k1-arakawa" and
            required <= set(value.get("body", "").splitlines()), "GITHUB_AUTHORITY_MISSING")


def expected_authorization() -> dict:
    return {
        "schema_version": "V13_XLSX_SUCCESSOR_ACTIVE_ENV_MUTATION_AUTHORIZATION_V1",
        "status": "AWAITING_GPT_EXACT_SHA_PASS", "authoritative_branch": BRANCH,
        "github_issue": 108, "predecessor_issue": 107, "predecessor_gpt_result": "PASS",
        "predecessor_gpt_reviewed_sha": PARENT, "predecessor_gpt_review_comment_id": 5848157902,
        "human_promotion_approval_comment_id": 5851057309, "human_promotion_approval_text": APPROVAL_TEXT,
        "current_authority_lock": {"path": current.CURRENT_AUTHORITY_LOCK_PATH,
            "git_blob_sha1": current.CURRENT_AUTHORITY_LOCK_BLOB_SHA1,
            "sha256": current.CURRENT_AUTHORITY_LOCK_SHA256, "package_count": 27},
        "candidate_lock": {"path": freeze.LOCK.name,
            "git_blob_sha1": "dfe440dc6398dc3b1a2dd31c81047e4209e61536",
            "sha256": freeze.LOCK_SHA256, "package_count": 29},
        "successor_delta": freeze.DELTA, "successor_delta_package_count": 2,
        "safe_realization_result": {"path": SAFE.relative_to(ROOT).as_posix(),
            "git_blob_sha1": "dabfd9868296be0caad660229a6988f518da646c",
            "status": "PASS_CONSUMED", "installed_package_count": 29,
            "production_xlsx_readiness": "PASS"},
        "wheel_manifest_sha256": freeze.MANIFEST_SHA256,
        "promotion_policy_approved": True,
        "active_environment_mutation_allowed": False,
        "active_environment_mutation_allowed_only_after_this_issue_gpt_exact_sha_pass": True,
        "active_environment_mutation_one_shot": True,
        "active_environment_mutation_consumed": False, "successor_promoted": False,
        "current_authority_changed": False, "package_index_reaccess_allowed": False,
        "dependency_reresolution_allowed": False, "new_wheel_download_allowed": False,
        "second_isolated_candidate_realization_allowed": False,
        "jpx_yahoo_private_selected500_model_backtest_aq_paper_live_allowed": False,
        "final_authority_promotion_requires_later_safe_result_and_gpt_reviewed_freeze": True,
    }


def authorization() -> dict:
    value = json.loads(reviewed(AUTH), object_pairs_hook=realization.unique)
    require(value == expected_authorization() and
            all(type(value[k]) is type(v) for k, v in expected_authorization().items()),
            "AUTHORIZATION_INVALID")
    for key, path in (("current_authority_lock", current.CURRENT_LOCK_PATH),
                      ("candidate_lock", freeze.LOCK), ("safe_realization_result", SAFE)):
        binding = value[key]
        reviewed(path, binding["git_blob_sha1"], binding.get("sha256"))
    realization_result.validate_result()
    safe = json.loads(reviewed(SAFE), object_pairs_hook=realization.unique)
    require(safe["status"] == "PASS_CONSUMED" and safe["authorization_consumed"] is True and
            safe["authorization_reusable"] is False and safe["installed_package_count"] == 29 and
            safe["production_xlsx_readiness"] == "PASS" and
            safe["wheel_manifest_sha256"] == freeze.MANIFEST_SHA256 and
            safe["active_environment_mutated"] is False and safe["successor_promoted"] is False,
            "SAFE_REALIZATION_RESULT_INVALID")
    freeze.validate_freeze()
    return value


def canonical_interpreter() -> None:
    realization.canonical_process_interpreter()
    require(sys.platform == "win32" and sys.version_info[:3] == (3, 12, 10) and
            sysconfig.get_platform() == "win-amd64", "DIRECT_WINDOWS_CANONICAL_PYTHON_REQUIRED")


def preflight(head: str) -> dict:
    canonical_interpreter()
    require(re.fullmatch(r"[0-9a-f]{40}", head) is not None, "EXECUTION_HEAD_INVALID")
    require(git("remote", "get-url", "origin").rstrip("/") in {
        "https://github.com/ta1k1-arakawa/stock-analyzer.git",
        "https://github.com/ta1k1-arakawa/stock-analyzer",
        "git@github.com:ta1k1-arakawa/stock-analyzer.git"}, "REPOSITORY_MISMATCH")
    require(git("branch", "--show-current") == BRANCH and git("rev-parse", "HEAD") == head and
            git("ls-remote", "origin", f"refs/heads/{BRANCH}") ==
            f"{head}\trefs/heads/{BRANCH}" and
            git("status", "--porcelain", "--untracked-files=all") == "" and
            git("merge-base", PARENT, head) == PARENT, "REPOSITORY_IDENTITY_INVALID")
    require(reviewed(Path(__file__)) == Path(__file__).read_bytes(), "HELPER_BLOB_MISMATCH")
    comment(5848157902, {"GITHUB_ISSUE=107", f"REVIEWED_SHA={PARENT}", "RESULT=PASS"})
    comment(5851057309, {"HUMAN_POINT_OF_USE_PROMOTION_APPROVAL=RECORDED",
                           f"APPROVAL_TEXT={APPROVAL_TEXT}", "PROMOTION_EXECUTED=false"})
    comment_for_issue_108(head)
    auth = authorization()
    require(current.run_current_readiness()["CURRENT_ENVIRONMENT_READY"], "CURRENT_27_NOT_READY")
    return auth


def comment_for_issue_108(head: str) -> None:
    result = subprocess.run(["gh", "api", "repos/ta1k1-arakawa/stock-analyzer/issues/108/comments",
                             "--paginate"], capture_output=True, check=True)
    comments = json.loads(result.stdout)
    require(any(c.get("user", {}).get("login") == "ta1k1-arakawa" and
                {"MODEL=GPT-5.6_SOL", "MODE=GPT_EXACT_SHA_INDEPENDENT_REVIEW",
                 "GITHUB_ISSUE=108", f"REVIEWED_SHA={head}", "RESULT=PASS"} <=
                set(c.get("body", "").splitlines()) for c in comments),
            "ISSUE_108_GPT_EXACT_SHA_PASS_MISSING")


def attempt_root() -> Path:
    # Fixed authority namespace; never accept a caller root or nonce.
    return (phase_b._local_state_base() / "stock-analyzer" / "protected-execution" /
            "v13-xlsx-active-mutation" / ATTEMPT_NAME)


def verified_wheels() -> tuple[Path, tuple[dict, ...]]:
    root = evidence._safe_root()
    _, source_hash = evidence.export_evidence()
    require(source_hash == freeze.SOURCE_EVIDENCE_SHA256, "SOURCE_EVIDENCE_MISMATCH")
    record = json.loads(reviewed(freeze.RECORD), object_pairs_hook=realization.unique)
    wheelhouse = root / "wheelhouse"
    for entry in wheelhouse.iterdir():
        info = entry.lstat()
        require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode) and
                not (getattr(info, "st_file_attributes", 0) & 0x400), "WHEEL_PATH_INVALID")
    wheels = verify_wheelhouse(wheelhouse, record["resolved_wheels"])
    require(len(wheels) == 29 and freeze.MANIFEST_SHA256 ==
            record.get("wheel_manifest_sha256", freeze.MANIFEST_SHA256), "WHEEL_MANIFEST_INVALID")
    return wheelhouse, wheels


def delta_wheels(wheelhouse: Path, wheels: tuple[dict, ...]) -> tuple[Path, Path]:
    selected = {w["name"]: w for w in wheels if w["name"] in DELTA}
    require(len(selected) == 2 and {k: w["version"] for k, w in selected.items()} == DELTA,
            "DELTA_WHEELS_INVALID")
    return tuple(wheelhouse / selected[name]["filename"] for name in sorted(DELTA))  # type: ignore[return-value]


def precheck_attempt(root: Path) -> None:
    require(root.is_absolute() and not os.path.lexists(root) and ".." not in root.parts,
            "ONE_SHOT_ALREADY_STARTED")
    node = root.parent
    while True:
        if os.path.lexists(node):
            info = os.lstat(node)
            require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and
                    not (getattr(info, "st_file_attributes", 0) & 0x400), "REPARSE_PATH_BLOCKED")
        if node == node.parent:
            break
        node = node.parent
    require(not root.is_relative_to(ROOT) and
            not root.is_relative_to(current.CANONICAL_VENV_DIR), "ATTEMPT_PATH_INVALID")


def durable_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(".tmp")
    with open(temp, "x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


ML_CHILD = r'''
import json, math
from lightgbm import LGBMRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
X = [[0.,0.],[1.,1.],[2.,2.],[3.,3.]]
y = [0.,1.,2.,3.]
model = LGBMRegressor(n_estimators=1, random_state=0, n_jobs=1, verbosity=-1)
model.fit(X,y)
light = model.predict([[1.5,1.5]])
scaler = StandardScaler().fit(X)
ridge = Ridge().fit(scaler.transform(X),y)
pred = ridge.predict(scaler.transform([[1.5,1.5]]))
print(json.dumps({'lightgbm': len(light)==1 and math.isfinite(float(light[0])),
                  'ridge': len(pred)==1 and math.isfinite(float(pred[0]))}))
'''


def postvalidate() -> None:
    observed = current._run_isolated_observer()
    require(observed["status"] == "PASS", "POST_OBSERVER_FAILED")
    child = observed["evidence"]
    require(current._validate_child_identity(child)["status"] == "PASS", "POST_IDENTITY_FAILED")
    pins = freeze.LOCK.read_text(encoding="ascii").splitlines()
    package_map = dict(line.split("==", 1) for line in pins)
    require(current._validate_child_package_set(package_map, child)["status"] == "PASS" and
            len(child["packages"]) == 29, "POST_PACKAGE_SET_FAILED")
    require(current._validate_child_pdf_probe(child)["status"] == "PASS", "POST_PDF_FAILED")
    realization.inspect_candidate(current.CANONICAL_INTERPRETER, package_map)
    ml = subprocess.run([str(current.CANONICAL_INTERPRETER), "-I", "-B", "-c", ML_CHILD],
                        capture_output=True, text=True, env=realization.child_environment(), check=False)
    require(ml.returncode == 0 and not ml.stderr.strip() and
            json.loads(ml.stdout, object_pairs_hook=realization.unique) ==
            {"lightgbm": True, "ridge": True}, "POST_ML_FAILED")


def mutate(head: str) -> dict:
    preflight(head)
    wheelhouse, wheels = verified_wheels()
    root = attempt_root()
    precheck_attempt(root)
    chosen = delta_wheels(wheelhouse, wheels)
    realization.probe_frozen_wheel_xlsx(wheelhouse, wheels)
    phase_b._prepare_operation_parent(root)
    precheck_attempt(root)
    verify_wheelhouse(wheelhouse, wheels)
    # Exclusive mkdir is the durable one-shot boundary, before pip launch.
    root.mkdir(exist_ok=False)
    durable_json(root / "attempt.json", {"schema_version": "V13_XLSX_ACTIVE_MUTATION_ATTEMPT_V1",
                 "status": "CONSUMED_PENDING", "execution_head": head,
                 "authorization_blob": blob(reviewed(AUTH)), "one_shot": True, "reusable": False})
    argv = [str(current.CANONICAL_INTERPRETER), "-I", "-m", "pip", "install",
            "--no-index", "--no-deps", "--no-cache-dir", "--disable-pip-version-check",
            "--no-input", "--no-build-isolation", *map(str, chosen)]
    code = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          env=realization.child_environment(), check=False).returncode
    require(code == 0, "OFFLINE_DELTA_INSTALL_FAILED")
    postvalidate()
    receipt = {"schema_version": "V13_XLSX_ACTIVE_MUTATION_RECEIPT_V1",
               "status": "MUTATED_VALIDATED_NOT_YET_PROMOTED", "execution_head": head,
               "authorization_blob": blob(reviewed(AUTH)),
               "current_lock_sha256": current.CURRENT_AUTHORITY_LOCK_SHA256,
               "candidate_lock_sha256": freeze.LOCK_SHA256,
               "wheel_manifest_sha256": freeze.MANIFEST_SHA256,
               "installed_package_count": 29, "delta_package_count": 2,
               "production_xlsx_readiness": "PASS", "pdf_readiness": "PASS",
               "ml_readiness": "PASS", "network_requests": 0, "wheel_downloads": 0,
               "authority_consumed": True, "authorization_reusable": False,
               "current_authority_changed": False, "successor_promoted": False}
    durable_json(root / "receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--execution-head")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"rehearsal": True, "package_installations": 0,
                          "active_environment_mutated": False}, sort_keys=True))
        return 0
    try:
        require(args.execution_head is not None, "EXECUTION_HEAD_REQUIRED")
        print(json.dumps(mutate(args.execution_head), sort_keys=True))
        return 0
    except BaseException as error:
        # The root itself, including crashes before the marker, consumes this approval.
        try:
            consumed = sys.platform == "win32" and os.path.lexists(attempt_root())
        except BaseException:
            consumed = True
        reason = str(error) if type(error) is ValueError else "MUTATION_FAILED"
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", reason) is None:
            reason = "MUTATION_FAILED"
        print(json.dumps({"status": "FAIL", "failure_class":
                          "CONSUMED_ACTIVE_ENV_MUTATION_FAILURE" if consumed else "PRE_GATE_FAILURE",
                          "reason": reason, "authorization_reusable": not consumed}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
