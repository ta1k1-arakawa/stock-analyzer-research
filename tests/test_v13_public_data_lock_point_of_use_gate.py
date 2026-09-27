"""Offline checks for the selected-500 point-of-use authorization boundary."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
AUTH_REL = "docs/v13/V13_PUBLIC_DATALOCK_POINT_OF_USE_AUTHORIZATION.json"
AUTH_BLOB = "980fb0c764d9495f8e298865fe1f48373ac84281"
IMPLEMENTATION = "6b4454aafc05c66c37d75e33a586d79653c1a413"
CALENDAR_BLOB = "336e5dd6141230b95fa4548231b0a137be6a15cb"
STANDING_BLOB = "291eda465ae26f86bbe8540f12551e1f40283d5b"
SCRIPT = ROOT / "scripts/run_v13_public_data_lock_direct_windows.ps1"


def test_authorization_frozen_bindings_and_scope():
    record = json.loads((ROOT / AUTH_REL).read_text(encoding="utf-8"))
    assert record == {
        "schema": "V13_PUBLIC_DATALOCK_POINT_OF_USE_AUTHORIZATION_V1",
        "study": "V13_CONDITIONAL_CROSS_SECTIONAL_SHORT_HORIZON",
        "authoritative_branch": "v13-conditional-cross-sectional-short-horizon",
        "authorization_scope": "SELECTED500_PUBLIC_DATALOCK_ONLY",
        "github_issue": 95,
        "human_approval_comment_id": 5843355424,
        "human_approval_comment_url": "https://github.com/ta1k1-arakawa/stock-analyzer/issues/95#issuecomment-5843355424",
        "predecessor_gpt_pass_issue": 94,
        "reviewed_implementation_sha": IMPLEMENTATION,
        "master_calendar_sha256": "30ad5d66c6c3b8bd2c71a814309e6133a03331437089103799551fa72150c44c",
        "master_calendar_safe_result_blob": CALENDAR_BLOB,
        "public_acquisition_authorization_blob": STANDING_BLOB,
        "operation_class": "RETRIABLE_PUBLIC_PLUMBING",
        "providers": ["JPX_CURRENT_LISTED_ISSUES", "YAHOO_FINANCE_CHART"],
        "price_window_start": "2015-01-01",
        "price_window_end": "2025-12-31",
        "selected_universe_size": 500,
        "public_datalock_execution_approved": True,
        "derived_t1_state_read_for_deterministic_exclusion_selection_resume_authorized": True,
        "original_private_source_reopen_authorized": False,
        "selected500_identity_print_authorized": False,
        "selected500_identity_commit_authorized": False,
        "model_fit_authorized": False,
        "historical_backtest_authorized": False,
        "a_to_q_execution_authorized": False,
        "forward_paper_authorized": False,
        "broker_access_authorized": False,
        "real_trading_authorized": False,
    }
    assert "execution_head" not in record
    assert subprocess.check_output(["git", "hash-object", AUTH_REL], cwd=ROOT, text=True).strip() == AUTH_BLOB
    assert subprocess.check_output(
        ["git", "hash-object", "V13_PUBLIC_ACQUISITION_AUTHORIZATION.json"], cwd=ROOT, text=True
    ).strip() == STANDING_BLOB


def test_wrapper_checks_before_private_or_network_boundary():
    source = SCRIPT.read_text(encoding="ascii")
    boundary = source.index("& $pythonExe scripts/v13_public_data_lock_execute.py --t1-state")
    reviewed_sources = {
        "scripts/v13_public_data_lock_execute.py": "1eda70521328101b7d82408e28401d48d5ec8502",
        "src/v13_public_data_lock.py": "9ba735105a6bb6e944300812d425c04ac08df185",
    }
    for path, blob in reviewed_sources.items():
        binding = f"Assert-ReviewedSourceBlob '{path}' '{blob}'"
        assert source.index("function Assert-ReviewedSourceBlob") < source.index(binding) < boundary
        assert subprocess.check_output(["git", "rev-parse", f"HEAD:{path}"], cwd=ROOT, text=True).strip() == blob
    assert source.index("BLOCK_REVIEWED_SOURCE_TREE_MISMATCH") < boundary
    assert source.index("BLOCK_REVIEWED_SOURCE_WORKTREE_MISMATCH") < boundary
    for required in (
        "git branch --show-current", "git rev-parse HEAD", "git ls-remote origin",
        "git status --porcelain", "git merge-base $ApprovedImplementationSha $ExecutionHead",
        "BLOCK_AUTHORIZATION_PATH", "BLOCK_AUTHORIZATION_BLOB",
        "BLOCK_AUTHORIZATION_OR_CALENDAR_SCOPE", "BLOCK_MASTER_CALENDAR_RESULT_BLOB",
        "BLOCK_STANDING_PUBLIC_AUTHORIZATION_BLOB", "check_current_protected_environment.py",
        "--preflight-calendar", "BLOCK_PRIVATE_OR_RAW_PATH_IN_REPOSITORY",
    ):
        assert source.index(required) < boundary
    assert "authorization.execution_head" not in source
    assert "6b4454aafc05c66c37d75e33a586d79653c1a413" in source
    assert AUTH_BLOB in source and CALENDAR_BLOB in source and STANDING_BLOB in source
    assert source.index("if (-not $Execute)") < source.index("Set-Location -LiteralPath $repoRoot")
    assigned = re.findall(r"\$([A-Za-z][A-Za-z0-9_]*)\s*=", source)
    assert not {name.lower() for name in assigned} & {
        "matches", "error", "args", "input", "host", "pid", "home"
    }


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell unavailable")
def test_powershell_rehearsal_and_parse():
    quoted_script = str(SCRIPT).replace("'", "''")
    parse = subprocess.run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "$parseTokens=$null; $parseErrors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{quoted_script}',"
        "[ref]$parseTokens,[ref]$parseErrors) > $null; "
        "if ($parseErrors.Count -ne 0) { exit 1 }",
    ], capture_output=True, text=True)
    assert parse.returncode == 0, parse.stderr
    rehearsal = subprocess.run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(SCRIPT)
    ], capture_output=True, text=True)
    assert rehearsal.returncode == 0, rehearsal.stderr
    assert "NETWORK_REQUESTS=0" in rehearsal.stdout
    assert "PRIVATE_READS=0" in rehearsal.stdout
    assert "REAL_UNIVERSE_SELECTED=false" in rehearsal.stdout


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell unavailable")
@pytest.mark.parametrize("mismatch,expected", [
    ("tree", "BLOCK_REVIEWED_SOURCE_TREE_MISMATCH"),
    ("worktree", "BLOCK_REVIEWED_SOURCE_WORKTREE_MISMATCH"),
])
def test_reviewed_source_binding_fails_closed_on_synthetic_mismatch(tmp_path: Path, mismatch: str, expected: str):
    relative = "src/v13_public_data_lock.py"
    blob = "9ba735105a6bb6e944300812d425c04ac08df185"
    path = tmp_path / relative
    path.parent.mkdir()
    path.write_text("synthetic parser", encoding="ascii")
    source = SCRIPT.read_text(encoding="ascii")
    function = source.split("    function Assert-ReviewedSourceBlob", 1)[1].split(
        "    Assert-ReviewedSourceBlob 'scripts/v13_public_data_lock_execute.py'", 1
    )[0]
    quoted_root = str(tmp_path).replace("'", "''")
    mock = f"""
$repoRoot = '{quoted_root}'
function git {{
    param([Parameter(ValueFromRemainingArguments=$true)][object[]]$gitArguments)
    $global:LASTEXITCODE = 0
    if ($gitArguments[0] -eq 'rev-parse') {{ return '{'0' * 40 if mismatch == 'tree' else blob}' }}
    if ($gitArguments[0] -eq 'hash-object') {{ return '{'0' * 40 if mismatch == 'worktree' else blob}' }}
    throw 'UNEXPECTED_SYNTHETIC_GIT_CALL'
}}
function Assert-ReviewedSourceBlob{function}
Assert-ReviewedSourceBlob '{relative}' '{blob}'
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", mock],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert expected in result.stderr, result.stderr


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell unavailable")
@pytest.mark.parametrize("scenario,expected", [
    ("wrong_path", "BLOCK_AUTHORIZATION_PATH"),
    ("wrong_blob", "BLOCK_AUTHORIZATION_BLOB"),
    ("wrong_content", "BLOCK_AUTHORIZATION_OR_CALENDAR_SCOPE"),
    ("wrong_calendar_blob", "BLOCK_MASTER_CALENDAR_RESULT_BLOB"),
    ("wrong_calendar_digest", "BLOCK_INVALID_BINDING"),
    ("wrong_local_head", "BLOCK_REPOSITORY_PREFLIGHT"),
    ("wrong_remote_head", "BLOCK_REPOSITORY_PREFLIGHT"),
    ("wrong_ancestry", "BLOCK_IMPLEMENTATION_ANCESTRY"),
])
def test_synthetic_powershell_gate_fail_closed(tmp_path: Path, scenario: str, expected: str):
    """Mock Git metadata; no private input or network transport exists here."""
    script = tmp_path / "scripts" / SCRIPT.name
    script.parent.mkdir()
    script.write_bytes(SCRIPT.read_bytes())
    auth = tmp_path / AUTH_REL
    auth.parent.mkdir(parents=True)
    auth.write_bytes((ROOT / AUTH_REL).read_bytes())
    calendar = tmp_path / "docs/v13/V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT.json"
    calendar.write_bytes((ROOT / "docs/v13/V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT.json").read_bytes())
    standing = tmp_path / "V13_PUBLIC_ACQUISITION_AUTHORIZATION.json"
    standing.write_bytes((ROOT / standing.name).read_bytes())
    if scenario in {"wrong_blob", "wrong_content"}:
        record = json.loads(auth.read_text(encoding="utf-8"))
        record["real_trading_authorized"] = True
        auth.write_text(json.dumps(record), encoding="utf-8")
    if scenario == "wrong_calendar_blob":
        calendar.write_bytes(calendar.read_bytes() + b" ")
    auth_arg = tmp_path / "wrong.json" if scenario == "wrong_path" else auth
    if scenario == "wrong_path":
        auth_arg.write_bytes(auth.read_bytes())
    execution = "a" * 40
    local = "b" * 40 if scenario == "wrong_local_head" else execution
    remote = "b" * 40 if scenario == "wrong_remote_head" else execution
    ancestor = "b" * 40 if scenario == "wrong_ancestry" else IMPLEMENTATION
    digest = "0" * 64 if scenario == "wrong_calendar_digest" else (
        "30ad5d66c6c3b8bd2c71a814309e6133a03331437089103799551fa72150c44c"
    )
    quoted = lambda value: str(value).replace("'", "''")
    mock = f"""
function git {{
    param([Parameter(ValueFromRemainingArguments=$true)][object[]]$gitArguments)
    $global:LASTEXITCODE = 0
    switch ($gitArguments[0]) {{
        'branch' {{ 'v13-conditional-cross-sectional-short-horizon'; return }}
        'rev-parse' {{ '{local}'; return }}
        'ls-remote' {{ '{remote}' + "`t" + 'refs/heads/v13-conditional-cross-sectional-short-horizon'; return }}
        'status' {{ return }}
        'merge-base' {{ '{ancestor}'; return }}
        'ls-tree' {{
            switch ($gitArguments[-1]) {{
                '{AUTH_REL}' {{ '100644 blob {AUTH_BLOB}' + "`t" + '{AUTH_REL}'; return }}
                'docs/v13/V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT.json' {{ '100644 blob {CALENDAR_BLOB}' + "`t" + 'docs/v13/V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT.json'; return }}
                'V13_PUBLIC_ACQUISITION_AUTHORIZATION.json' {{ '100644 blob {STANDING_BLOB}' + "`t" + 'V13_PUBLIC_ACQUISITION_AUTHORIZATION.json'; return }}
            }}
        }}
        'hash-object' {{
            if ('{scenario}' -eq 'wrong_content' -and $gitArguments[-1] -eq '{quoted(auth)}') {{ '{AUTH_BLOB}'; return }}
            & git.exe @gitArguments
            return
        }}
    }}
    throw 'UNEXPECTED_SYNTHETIC_GIT_CALL'
}}
& '{quoted(script)}' -Execute -ApprovedImplementationSha '{IMPLEMENTATION}' -ExecutionHead '{execution}' -AuthorizationRecord '{quoted(auth_arg)}' -PrivateT1State '{quoted(tmp_path / 'absent.private.json')}' -CalendarLock '{quoted(tmp_path / 'absent.calendar')}' -CalendarSha256 '{digest}' -OutputDirectory '{quoted(tmp_path / 'absent-output')}'
"""
    result = subprocess.run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-Command", mock,
    ], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0
    assert expected in result.stderr, result.stderr
    assert "BLOCK_CANONICAL_ENVIRONMENT" not in result.stderr
