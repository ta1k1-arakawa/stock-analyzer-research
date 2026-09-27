"""Synthetic Windows point-of-use path gates; no protected content is opened."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_v13_public_data_lock_point_of_use_gate import (
    AUTH_BLOB, AUTH_REL, CALENDAR_BLOB, IMPLEMENTATION, ROOT, SCRIPT, STANDING_BLOB,
)


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell unavailable")
@pytest.mark.parametrize("scenario,expected", [
    ("ordinary", "SYNTHETIC_DOWNSTREAM_BOUNDARY"),
    ("arbitrary_t1", "BLOCK_T1_STATE_IDENTITY"),
    ("original_recovery", "BLOCK_T1_STATE_IDENTITY"),
    ("missing_localappdata", "BLOCK_LOCALAPPDATA"),
    ("relative_localappdata", "BLOCK_LOCALAPPDATA"),
    ("t1_file_reparse", "BLOCK_PROTECTED_PATH_REPARSE"),
    ("t1_ancestor_reparse", "BLOCK_PROTECTED_PATH_REPARSE"),
    ("calendar_file_reparse", "BLOCK_PROTECTED_PATH_REPARSE"),
    ("calendar_ancestor_reparse", "BLOCK_PROTECTED_PATH_REPARSE"),
    ("output_ancestor_reparse", "BLOCK_PROTECTED_PATH_REPARSE"),
])
def test_synthetic_identity_and_reparse_gates(tmp_path: Path, scenario: str, expected: str):
    script = tmp_path / "repo" / "scripts" / SCRIPT.name
    script.parent.mkdir(parents=True)
    source = SCRIPT.read_text(encoding="ascii")
    # Stop before reviewed-source and Python preflight. This synthetic copy tests path gates only.
    source = source.split("    # Bind the reviewed Issue #121 implementation", 1)[0]
    source += "    Write-Output 'SYNTHETIC_DOWNSTREAM_BOUNDARY'\n}\n"
    script.write_text(source, encoding="ascii")
    repo = script.parent.parent
    auth = repo / AUTH_REL
    auth.parent.mkdir(parents=True)
    auth.write_bytes((ROOT / AUTH_REL).read_bytes())
    calendar_result = repo / "docs/v13/V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT.json"
    calendar_result.write_bytes((ROOT / "docs/v13/V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT.json").read_bytes())
    standing = repo / "V13_PUBLIC_ACQUISITION_AUTHORIZATION.json"
    standing.write_bytes((ROOT / standing.name).read_bytes())

    local = tmp_path / "local"
    t1 = local / "stock-analyzer/private/v13-t1-exclusion-provenance/t1-exclusion-state.json"
    t1.parent.mkdir(parents=True)
    t1.write_text("synthetic state; wrapper must not read it", encoding="ascii")
    calendar = tmp_path / "calendar" / "lock.json"
    calendar.parent.mkdir()
    calendar.write_text("synthetic calendar; wrapper must not read it", encoding="ascii")
    output = tmp_path / "output" / "selected500"
    output.parent.mkdir()
    arbitrary = tmp_path / "other" / "arbitrary.json"
    arbitrary.parent.mkdir()
    arbitrary.write_text("arbitrary synthetic", encoding="ascii")
    original = local / "stock-analyzer/private/v8-jquants-identity-recovery/recovery.json"
    original.parent.mkdir(parents=True)
    original.write_text("synthetic original", encoding="ascii")
    supplied = {"arbitrary_t1": arbitrary, "original_recovery": original}.get(scenario, t1)
    reparse = {
        "t1_file_reparse": t1,
        "t1_ancestor_reparse": t1.parent,
        "calendar_file_reparse": calendar,
        "calendar_ancestor_reparse": calendar.parent,
        "output_ancestor_reparse": output.parent,
    }.get(scenario)
    quote = lambda path: str(path).replace("'", "''")
    mock = f"""
function git {{
    param([Parameter(ValueFromRemainingArguments=$true)][object[]]$gitArguments)
    $global:LASTEXITCODE = 0
    switch ($gitArguments[0]) {{
        'branch' {{ 'v13-conditional-cross-sectional-short-horizon'; return }}
        'rev-parse' {{ '{'a' * 40}'; return }}
        'ls-remote' {{ '{'a' * 40}' + "`t" + 'refs/heads/v13-conditional-cross-sectional-short-horizon'; return }}
        'status' {{ return }}
        'merge-base' {{ '{IMPLEMENTATION}'; return }}
        'ls-tree' {{
            switch ($gitArguments[-1]) {{
                '{AUTH_REL}' {{ '100644 blob {AUTH_BLOB}' + "`t" + '{AUTH_REL}'; return }}
                'docs/v13/V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT.json' {{ '100644 blob {CALENDAR_BLOB}' + "`t" + 'docs/v13/V13_MASTER_CALENDAR_REAL_GENERATION_SAFE_RESULT.json'; return }}
                'V13_PUBLIC_ACQUISITION_AUTHORIZATION.json' {{ '100644 blob {STANDING_BLOB}' + "`t" + 'V13_PUBLIC_ACQUISITION_AUTHORIZATION.json'; return }}
            }}
        }}
        'hash-object' {{ & git.exe @gitArguments; return }}
    }}
    throw 'UNEXPECTED_SYNTHETIC_GIT_CALL'
}}
function Get-Item {{
    param([string]$LiteralPath, [switch]$Force, [string]$ErrorAction)
    if ($LiteralPath -eq '{quote(reparse) if reparse else 'NO_REPARSE_PATH'}') {{
        return [pscustomobject]@{{ Attributes = [IO.FileAttributes]::ReparsePoint }}
    }}
    Microsoft.PowerShell.Management\\Get-Item -LiteralPath $LiteralPath -Force -ErrorAction Stop
}}
& '{quote(script)}' -Execute -ApprovedImplementationSha '{IMPLEMENTATION}' -ExecutionHead '{'a' * 40}' -AuthorizationRecord '{quote(auth)}' -PrivateT1State '{quote(supplied)}' -CalendarLock '{quote(calendar)}' -CalendarSha256 '30ad5d66c6c3b8bd2c71a814309e6133a03331437089103799551fa72150c44c' -OutputDirectory '{quote(output)}'
"""
    env = os.environ.copy()
    env["LOCALAPPDATA"] = {"missing_localappdata": "", "relative_localappdata": "relative"}.get(scenario, str(local))
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", mock],
        cwd=repo, env=env, capture_output=True, text=True,
    )
    combined = result.stdout + result.stderr
    assert expected in combined, combined
    assert (result.returncode == 0) == (scenario == "ordinary"), combined
    if scenario != "ordinary":
        assert "SYNTHETIC_DOWNSTREAM_BOUNDARY" not in combined
