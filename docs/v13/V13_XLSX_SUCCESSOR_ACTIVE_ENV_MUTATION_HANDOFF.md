# V13 XLSX successor active environment mutation handoff

This handoff is **inert until Issue #108 receives GPT exact-SHA PASS of the remediated execution HEAD**. The human approval is Issue #107 comment `5851057309`. The runner checks both sources at execution time. This task does not run the mutation. Issue #108 review of `f0661edeef94b51497fa982544b3dfcbf100418c` was BLOCK (comment `5851215806`); that SHA must not be executed.

The reviewed V10C canonical mutation used an in-place, offline, exact-delta pip install after an exclusive durable attempt-directory creation. Issue #108 uses the same boundary and installs only the frozen `et-xmlfile==2.0.0` and `openpyxl==3.1.5` wheels into the exact `.venv-real-execution`. It derives the wheelhouse from the reviewed Phase-B source logic and checks the complete 29-wheel manifest before the boundary. No root, target, wheelhouse, or nonce is a command argument.

On direct Windows PowerShell 5.1, from the authoritative repository worktree, run this **single atomic block** only after the GPT review is published. The block obtains the local 40-hex HEAD; the runner requires it to equal the remote HEAD and the exact reviewed Issue #108 SHA. It invokes the canonical Python directly and needs no `.ps1` execution-policy change.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $repoRoot = (Get-Location).Path
    $interpreter = Join-Path $repoRoot '.venv-real-execution\Scripts\python.exe'
    $executionHead = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $executionHead -cnotmatch '^[0-9a-f]{40}$') { throw 'BLOCK_EXECUTION_HEAD_INVALID' }
    if (-not (Test-Path -LiteralPath $interpreter -PathType Leaf)) { throw 'BLOCK_CANONICAL_INTERPRETER_MISSING' }
    & $interpreter -B -m scripts.v13_xlsx_active_env_mutation --execute --execution-head $executionHead
    if ($LASTEXITCODE -ne 0) { throw 'BLOCK_ACTIVE_ENV_MUTATION_FAILED' }
}
```

The Python preflight checks the exact repository, branch, local and remote execution HEAD, ancestry, clean tree, reviewed helper and artifacts, GPT PASS, human approval, current 27-package readiness, frozen wheel bytes, and XLSX wheel probe. The durable boundary is the exclusive creation of the one fixed attempt directory. Failure before it is `PRE_GATE_FAILURE` and leaves approval unused. Any failure after it is `CONSUMED_ACTIVE_ENV_MUTATION_FAILURE`; the approval is consumed even if pip was not launched. Never delete/reset the directory, retry, repair/rollback as a new attempt, or choose another root. Return post-boundary failures to GPT and human authority.

On success the privacy-safe receipt reports `MUTATED_VALIDATED_NOT_YET_PROMOTED`, exact 29-package installed identity, synthetic production XLSX parsing, existing PDF/runtime readiness, and zero network/downloads. The exact installed-package check covers the candidate ML dependency identities; it does not execute estimators. `MODEL_FITS=0` remains mandatory during later real execution. The current authority lock/checker remains the 27-package binding. A later safe-result checkpoint and GPT-reviewed freeze/promotion task is required before the 29-package successor becomes current authority. No JPX/Yahoo/private/selected500/model/backtest/A-Q/paper/live operation is authorized by this handoff.
