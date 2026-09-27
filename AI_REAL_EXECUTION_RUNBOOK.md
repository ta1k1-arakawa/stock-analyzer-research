# AI Real Execution Runbook

```text
document_type=REPOSITORY_REAL_EXECUTION_SAFETY_RUNBOOK
status=ACTIVE
scope=REAL_NETWORK_PRIVATE_DATA_HUMAN_GATE_DURABLE_STATE
```

This runbook is mandatory whenever a task can reach any of the following:

- real Yahoo, JPX, broker, or other external production network;
- private or sealed data, identities, or inputs;
- human-gated one-shot execution;
- durable machine-local production, gate, or audit state;
- raw acquisition or research opening; or
- direct Windows PowerShell prepared for any of the above.

It applies to the task author, ChatGPT, GPT-5.6 Sol, Codex, Claude Code
Cloud, and reviewers when they prepare, inspect, authorize, execute, or
report an in-scope operation.

## Authority and boundary

The frozen task or study design remains authoritative for methodology,
including provider, sentinel, windows, retry policy, thresholds, partitions,
sample rules, stopping rules, and gate semantics. The human gate remains the
ultimate authority. A task-specific stricter rule wins. This runbook supplies
stable operational safety only; it must never silently relax, reinterpret, or
replace a frozen study design. If a repair would change methodology or the
execution contract, stop and obtain a successor-study or other explicit
methodology decision from the GPT methodology authority and human authority.

Reusable real-execution safety belongs in this version-controlled runbook,
not in conversational memory or repeated long prompts. Repository-first and
delta-only prompt rules remain in `AI_RESEARCH_EXECUTION_RULES.md`.

## 1. Atomic PowerShell execution

A fail-closed real-execution command supplied to a user MUST be one atomic
PowerShell script block, normally `& { ... }`, or a pre-created reviewed
`.ps1` file. Do not provide independent lines where a `throw` can fail while
the user can continue pasting later commands.

The atomic scope MUST set the stop mode inside the scope:

```powershell
& {
    $ErrorActionPreference = "Stop"
    # Read-only provenance and state preflight.
    # Stop before the private/network/gate boundary unless every check passes.
    # Consume a one-shot gate only when the frozen operation requires one.
    try {
        # Authorized operation.
    }
    finally {
        # Clear any transient private environment values.
    }
}
```

Every preflight failure must terminate the whole block before any private,
network, or gate boundary. If an interactive continuation prompt `>>` is
present unexpectedly, instruct the user to press Ctrl+C before any further
execution. Long or one-shot execution must not depend on an AI-agent session
remaining alive.

A PowerShell `throw` terminates only the current statement/scope -- it does
not, and cannot, prevent the user from independently pasting and running a
further, unrelated command afterward in the same shell. This is exactly why
independent, sequential, standalone snippets are prohibited for protected
execution: a `throw` on an earlier line does not stop a later, separately
pasted line from still running. A single reviewed `& { ... }` block (or one
reviewed `.ps1` file, itself normally wrapped in a single top-level
`& { ... }` scope) does not have this problem, because control never returns
to the prompt until the entire scope has completed or failed as one unit.

## 2. Mandatory preflight before a boundary

Before any irreversible, private, network, or gate boundary, mechanically
verify every item applicable to the frozen design:

- correct repository;
- authoritative branch;
- exact expected local HEAD;
- exact authoritative remote HEAD;
- clean working tree;
- required commit, blob, and artifact bindings;
- frozen-design binding;
- reviewed-implementation binding;
- human-authority prerequisites;
- for a one-shot operation, its gate not already consumed;
- no conflicting durable execution binding, audit, or receipt;
- required private input exists and resolves uniquely.

Only after all required checks PASS may execution continue. A missing,
ambiguous, malformed, mismatched, stale, or unverifiable prerequisite is a
STOP condition. The preflight must not print private values while proving
these predicates.

## 3. Stale local checkout recovery

Never interpret a merely stale local checkout as a research or study failure.
First fetch `origin`. If, and only if, the authoritative remote HEAD equals
the exact expected SHA, the working tree is clean, the branch is correct, and
the current local HEAD is an ancestor of that expected SHA, a sync-only
pre-execution operation is allowed:

```powershell
git reset --hard <exact-expected-SHA>
```

This creates no methodology authority and consumes no gate. If ancestry,
branch, remote HEAD, cleanliness, or history is not exact, stop with
`EXPECTED_HEAD_MISMATCH` or `LOCAL_HISTORY_MISMATCH`, as applicable. Never
use `git pull`, merge, rebase, cherry-pick, or force as recovery. Re-run the
entire preflight from the beginning after an allowed sync.

## 4. Pre-gate versus post-gate failure

Classify the boundary before deciding authorization status or recovery. First
perform read-only state verification.

For a `STATISTICALLY_IRREVERSIBLE_GATE` or another explicitly one-shot,
private, or production operation, `PRE_GATE_FAILURE` means its gate was not
consumed, the applicable boundary was not crossed, and real request count is
zero where provable. Do not automatically declare a still-unused
authorization consumed. Only non-methodological, safe preflight repair may
be proposed; then run preflight again from the beginning.

`POST_GATE_FAILURE` means a durable one-shot gate was consumed. A crash or
BLOCK does not restore authorization. Do not retry, reset, delete a receipt,
generate a fresh nonce to bypass the gate, or reinterpret the same human
authorization. Follow the frozen stopping rule and return to the GPT
methodology authority and human authority for the next decision.

When the exact boundary cannot be proven, fail closed and do not assume
`PRE_GATE_FAILURE`.

### 4.1 Proportional irreversibility and recovery

For future designs, classify the operation before applying one-shot failure
discipline. `RETRIABLE_PUBLIC_PLUMBING` covers only explicitly public,
non-sealed transport and its setup/parser/filesystem processing; it may use
`STANDING_RETRIABLE_PUBLIC_PLUMBING_AUTHORITY` explicitly granted by the
human-approved frozen design. That authority is bounded by study,
provider/endpoint, source semantics, content lock, retry conditions, and
stopping conditions; it is not reuse of a one-shot authorization. It never
covers private/sealed data, broker actions, production trading, or holdout
exposure.
`STATISTICALLY_IRREVERSIBLE_GATE` covers first sealed membership/outcome
exposure (including T1/T2/T3 where applicable), irreversible research
opening, and production authority; its one-shot rule remains intact.

A public source must be content-locked: use the frozen provider/endpoint,
retry transport only until the first complete payload, immediately preserve
and hash that payload before semantic inspection, then repair/reprocess only
that same payload. A parser, T0, eligibility, or other semantic/data-quality
failure is not authority to re-fetch until PASS or substitute provider/date.
Classify it separately as `DATA_QUALITY_FAILURE`; transport/setup failure
before complete payload is `PLUMBING_FAILURE_RETRIABLE`.

For `DETERMINISTIC_DURABLE_STATE`, persist authoritative state (for example,
a partition seed) before dependent computation. After a crash, reuse that
exact state and verify deterministic regeneration; never reroll merely to
obtain PASS. Existing frozen studies retain their own approved semantics.

## 5. Private path and file discovery

Never guess a private path. Never ask the user to paste a private path into
public or chat output when avoidable. Before the applicable authorized
content boundary, discovery is metadata-only.

Resolve candidate paths privately and count them without printing identities
or paths:

- zero candidates: STOP;
- exactly one candidate: it may proceed after all other checks PASS;
- more than one candidate: STOP for ambiguity.

Do not print ticker identities, private paths, raw payloads, prices,
features, outcomes, or raw authorization identity. Content reads require the
applicable authorization boundary. Safe evidence may expose only approved
hashes, counts, booleans, and safe aggregates.

## 6. PowerShell automatic variables

PowerShell variable names are case-insensitive. Do not use ordinary task
variables whose names collide with automatic variables. At minimum prohibit:

```text
Matches / matches
Error / error
Args / args
Input / input
Host / host
PID / pid
HOME / home
```

Prefer descriptive names such as `regexMatch`, `candidatePaths`,
`executionError`, and `privateManifestPath`. Apply this rule to every
variable in a prepared script, including variables in `catch`, `finally`,
and helper functions.

## 7. Execution environment

For real network, private-data, human-gated, or durable-machine-state
execution, default to direct Windows PowerShell. Claude Code Cloud and
Codex may prepare and statically inspect the command, but execution must not
depend on the lifetime of an AI-agent session. Long or one-shot work must be
prepared so it can continue on the Windows side after an SSH or agent
connection ends, when the frozen design permits that topology.

Local Claude Code remains prohibited by repository governance. Normal local
Codex editing and short validation are separate from direct execution and do
not authorize a private or network boundary.

### 7a. Active protected-environment authority resolution

Before a protected PRE_GATE Issue names an environment checker, resolve the
current canonical authority from repository evidence and bind the exact
reviewed promotion/freeze chain in that Issue. Use:

```text
.venv-real-execution\Scripts\python.exe scripts/check_current_protected_environment.py
```

The checker is no-network, no-private-data, and read-only. After exact-SHA
GPT PASS of Issue #111's final promotion, it resolves the V13 29-package
XLSX successor as current authority from the #110-reviewed mutation safe
result, final promotion artifact, and project-state fields. The F9-reviewed
V10C 27-package lock remains bound as historical predecessor. It then
checks the exact canonical interpreter, Python `3.12.10`, and the live
installed package identity through `importlib.metadata.distributions()` with
normalized names, exact versions, exact cardinality, and duplicate rejection
inside an isolated child launched by that exact interpreter with `-I` and
`-B`. The child removes ambient `PYTHONPATH`/`PYTHONHOME` authority, disables
user-site and bytecode, and loads repository-local probe code by explicit
file path. It also runs the reviewed synthetic PDF operational probe and the
synthetic production XLSX parser route, requiring exact `openpyxl==3.1.5`
and `et-xmlfile==2.0.0`. `pip freeze` presentation,
including direct-reference lines, is not installed-identity authority.
The parent fails closed on child launch/nonzero/schema/identity/package/probe
failure. `check_current_protected_environment.py` resolving this current
authority does not replace operation-specific reachable-dependency probes;
each future protected task must bind and pass the probes applicable to its
post-gate path.
`scripts/check_real_execution_env.py` remains an independent
historical V9_014 generic 15-package checker; it must not be named as the
current PRE_GATE authority unless a later reviewed project-state transition
explicitly makes it current. A missing, ambiguous, stale, or contradictory
chain is `CHATGPT_DECISION_REQUIRED`/`PRE_GATE_ENVIRONMENT_BLOCK`; do not
invent a lock, package count, promotion, or checker binding.

An Orca/SSH/Termux-operated Windows PowerShell session is an acceptable
transport to the Windows machine for direct PowerShell and read-only
preflight work. That transport does not grant execution authority. An
elevated Windows token is required only for an operation that actually needs
administrator rights. One-shot or long-running protected work must run on
the Windows side and must not depend on an Orca, Codex, or Claude agent
session remaining alive.

Agent-created pytest caches, temporary directories, and other transient
state inside the repository must remain readable by the host user. An
unreadable repository-root cache/temp directory is a PRE_GATE clean-tree
blocker; avoid creating one or safely remove it before handoff.

## 8. Durable-state collision check

Before consuming a gate, read-only check every relevant existing durable
state location, including:

- gate receipt;
- production execution binding;
- audit aggregate or dossier where a deterministic conflict matters;
- verification receipt; and
- stage-specific durable state.

If existing state indicates a prior attempt or execution, STOP. Never delete,
reset, overwrite, or otherwise alter that state to obtain another attempt.
Durable publication must remain exclusive and no-overwrite when required by
the frozen design.

## 9. Transient secrets and private values

Raw human authorization identities and private paths must not be printed.
If a private value is temporarily placed in an environment variable, clear it
in a `finally` block even when the operation fails. Prefer public or durable
safe evidence consisting of SHA-256 values, counts, booleans, or safe
aggregates. Private ticker identities, raw URLs, and raw payloads must not
leak into logs, reports, exceptions, or receipts.

## 10. Frozen failure discipline

After a real BLOCK, the execution agent or ChatGPT must not, within the same
frozen study, silently:

- change provider;
- change a sentinel;
- change a readiness or acquisition window;
- add or change retry behavior;
- change a threshold;
- substitute another ticker or block;
- redraw a partition;
- alter sample inclusion or exclusion; or
- relax validation.

Follow the frozen stopping rule. If repair changes methodology or the
contract and was not explicitly pre-authorized, require a successor-study
decision. Operational recovery is not permission to retry a consumed
experiment.

## 11. Safe execution report contract

For real execution, report only safe values, where applicable, using this
contract:

```text
PRE_GATE_STATUS=<PASS|FAIL|UNKNOWN>
LOCAL_HEAD=<safe exact SHA or omitted when unavailable>
REMOTE_HEAD=<safe exact SHA or omitted when unavailable>
WORKING_TREE_CLEAN=<true|false|unknown>
GATE_CONSUMED=<true|false|unknown>
PRIVATE_READS=<nonnegative count|unknown>
NETWORK_REQUESTS=<nonnegative count|unknown>
YAHOO_REQUESTS=<nonnegative count|unknown>
JPX_REQUESTS=<nonnegative count|unknown>
EXECUTION_RESULT=<safe enum>
FAILURE_CLASS=<safe enum or NONE>
DURABLE_EVIDENCE=<hashes/counts/booleans/safe aggregates only>
AUTHORIZATION_REUSABLE=<true|false|unknown>
SECOND_EXECUTION_ALLOWED=<true|false|unknown>
RAW_ACQUISITION_ALLOWED=<true|false|unknown>
RESEARCH_OPENING_ALLOWED=<true|false|unknown>
CANONICAL_ENVIRONMENT_STATUS=<PASS|FAIL|UNKNOWN>
INTERPRETER_IDENTITY_STATUS=<PASS|FAIL|UNKNOWN>
PYTHON_VERSION=<safe exact version or omitted when unavailable>
DEPENDENCY_READINESS=<PASS|FAIL|UNKNOWN>
SYNTHETIC_PARSER_READINESS=<PASS|FAIL|CHATGPT_DECISION_REQUIRED|UNKNOWN>
ENVIRONMENT_LOCK_FINGERPRINT_STATUS=<FROZEN|CANDIDATE_VERIFIED_NOT_FROZEN|CANDIDATE_INVALID_OR_UNVERIFIED|NOT_YET_ESTABLISHED|UNKNOWN>
ENVIRONMENT_LOCK_PACKAGE_SET_MATCH=<true|false|unknown>
ENVIRONMENT_LOCK_PACKAGE_COUNT=<nonnegative count|unknown>
ENVIRONMENT_LOCK_SHA256_MATCH=<true|false|unknown>
PYTHON_PATCH_MATCH=<true|false|unknown>
ENVIRONMENT_FREEZE_CHECK=<PASS|FAIL|UNKNOWN>
ENVIRONMENT_FREEZE_EVIDENCE_GIT_SHA256_MATCH=<true|false|unknown>
REAL_EXECUTION_ENVIRONMENT_FROZEN=<true|false|unknown>
NEXT_ACTION=<safe stopping or authority action>
```

See §15-§19 for the canonical environment contract, the required
environment-readiness-before-authorization ordering, environment failure
classification, and the mandatory reviewer question these fields support.

Never include prohibited private values in a report, including private paths,
ticker identities, raw URLs, raw payloads, prices, features, outcomes, or raw
authorization identity.

## 12. Recovery state machine

Select the recovery branch from the frozen operation class; merely crossing a
public network boundary does not itself consume a statistical one-shot
authority.

For a `STATISTICALLY_IRREVERSIBLE_GATE` or another explicitly one-shot,
private, or production operation, the strict recovery flow is:

```text
STOP
  -> determine whether the applicable private/gate boundary was reached
  -> read-only inspect durable state
  -> classify PRE_GATE or POST_GATE
  -> PRE_GATE: propose only non-methodological safe preflight repair
  -> PRE_GATE: re-run preflight from the beginning
  -> POST_GATE: authority is not restored; no retry/reset/delete/reuse unless frozen design explicitly permits
  -> return to GPT methodology authority and human authority for next study decision
```

If a state transition is not provable, STOP. A POST_GATE crash, BLOCK, or
partial result never becomes a PRE_GATE failure through cleanup.

For `RETRIABLE_PUBLIC_PLUMBING` with valid
`STANDING_RETRIABLE_PUBLIC_PLUMBING_AUTHORITY`, recovery instead follows the
frozen content-lock state:

```text
no complete public payload
  -> PLUMBING_FAILURE_RETRIABLE
  -> retry transport only under frozen provider/endpoint/retry/stopping conditions

first complete payload preserved and content-locked
  -> never re-fetch because of a downstream failure
  -> environment/parser/software repair reruns only against the exact preserved raw bytes

semantic/T0/eligibility/data-quality failure
  -> DATA_QUALITY_FAILURE
  -> STOP; no additional fetch to seek PASS
```

Provider/date substitution is prohibited. Historical V8I and V8J remain
governed by their immutable recorded one-shot semantics and are not
reinterpreted by this prospective branch.

## 13. Command quality checklist

Before giving a real-execution PowerShell block, ChatGPT or the execution
agent preparing it must statically check:

- one atomic `& { }` scope or one reviewed `.ps1`;
- `$ErrorActionPreference = "Stop"` inside that scope;
- no automatic-variable name collisions;
- no path continues after a failed preflight;
- no private or network operation before required preflight;
- gate-consumption boundary matches the frozen design;
- no raw secrets are printed;
- `finally` cleanup exists for transient private environment values;
- second-execution behavior is explicit;
- failure output is privacy-safe; and
- no methodology choice is hidden in recovery logic.

## 14. Generic incident rationale

Stale local Git state must be repaired before interpreting a study outcome.
Shell error handling must be atomic because interactive line-by-line
execution can continue after a thrown error. PowerShell's case-insensitive
automatic variables can corrupt ordinary state if reused. One-shot gates
require explicit pre- and post-boundary classification. These are
operational safety rules, not permission to retry a consumed experiment.

This rationale is generic and does not establish any study-specific root
cause or convert a hypothesis into a confirmed fact.

## 15. Canonical Python environment (`.venv-real-execution`)

This repository has two distinct Python environments. Only one is ever
accepted for protected execution:

```text
.venv                 = GENERAL_PROJECT_ENVIRONMENT_NOT_AUTHORIZED_FOR_PROTECTED_EXECUTION
.venv-real-execution   = CANONICAL_PROTECTED_REAL_EXECUTION_ENVIRONMENT
```

The existing `.venv` is a general mixed project/trading-bot environment
(Windows-grounded inspection found it to be Python 3.12.10 with 46
packages, including unrelated dependencies such as `yfinance`, `lightgbm`,
`pytest`, `requests`, `curl_cffi`, `scikit-learn`). It remains available,
untouched, for ordinary project development and is never deleted,
modified, cleaned, or reinterpreted by real-execution tooling -- it is
simply never accepted as the protected interpreter, regardless of its
Python version or which packages happen to be installed in it.

For repository Python protected execution:

- the canonical environment directory is `.venv-real-execution` at the
  repository root; it is never committed to Git;
- all protected execution MUST invoke the interpreter explicitly as
  `.venv-real-execution\Scripts\python.exe` -- never `.venv\Scripts\
  python.exe` (the general environment), `python`, `python3`, `py`, PATH
  activation, or whatever interpreter happens to be currently active;
- system Python and any WindowsApps-alias Python are prohibited for
  protected execution;
- activation (`.venv-real-execution\Scripts\Activate.ps1`) may be
  convenient for a human operator but is never the security/provenance
  mechanism -- an activated shell's `python` can still silently resolve to
  something other than the canonical interpreter, including the general
  `.venv`;
- production code/preflight must verify `sys.executable` resolves to the
  repository's exact `.venv-real-execution\Scripts\python.exe` before any
  gate/network/private boundary. A mismatch is `PRE_GATE_WRONG_PYTHON_
  ENVIRONMENT` (§17) -- including, explicitly, when the resolved
  interpreter is the general `.venv`.

Rationale: the protected environment should minimize dependency drift and
attack surface (every package in it should be traceable to the real
execution import closure, not incidentally present for an unrelated bot
feature), and unrelated development/trading-bot dependency upgrades in
`.venv` must never silently alter the frozen research execution
environment.

Once a reviewed environment lock exists (§19),
`requirements-real-execution.lock.txt` -- not the unpinned
`requirements-real-execution.txt` -- is the protected installation/runtime
package authority: protected packages are resolved and installed
exclusively from that reviewed, exact-pinned lock, with `--no-deps`, so pip
cannot silently add or resolve any package outside the complete reviewed
lock. `requirements-real-execution.txt` remains the direct-dependency
*specification* (§4's traced import closure), not the install source, once
a lock has been captured.

See `REAL_EXECUTION_PYTHON_ENVIRONMENT.md` for the full human-readable
contract (canonical Python version, direct dependency closure, required JPX
Excel engine, bootstrap/readiness procedures, and the environment
lock/fingerprint procedure, including §6a's lock-authority contract),
`requirements-real-execution.txt` for the direct dependency specification,
`requirements-real-execution.lock.txt` for the reviewed exact-pinned
installation authority, `scripts/bootstrap_real_execution_env.ps1` for the
environment-setup-only bootstrap script, and
`scripts/check_real_execution_env.py` for the no-network, no-private-data
readiness checker (including its mechanical environment-lock check).

## 16. Environment readiness before the applicable authority boundary

For a `STATISTICALLY_IRREVERSIBLE_GATE` or another explicitly one-shot,
private, or production-gated operation, the required order is:

```text
design/freeze PASS
  -> implementation exact-SHA review PASS
  -> repo sync/provenance preflight
  -> canonical .venv-real-execution existence
  -> exact interpreter validation
  -> dependency closure validation
  -> synthetic operational parser probe
  -> filesystem/durable readiness
  -> environment lock/fingerprint verification
  -> ALL PRE_GATE checks PASS
  -> only then request/accept fresh point-of-use human authorization
  -> rerun all non-destructive bindings
  -> consume gate
  -> real execution
```

If authorization was supplied earlier, it still must not be consumed until
every readiness check passes. Environment readiness is part of preflight
(§2), not a substitute for it, and does not relax any other preflight
requirement.

For `RETRIABLE_PUBLIC_PLUMBING` with valid frozen standing authority, there
is no artificial one-shot gate merely because transport uses a real public
network. The required order is:

```text
design/freeze PASS
  -> implementation review as applicable
  -> repo/provenance preflight
  -> canonical environment/readiness checks as applicable
  -> verify exact standing-authority scope
  -> verify public-source content-lock state
  -> execute/retry only under frozen transport retry conditions
  -> on first complete payload: preserve/hash immediately
  -> later repair/retries use only the exact preserved raw bytes
  -> semantic/DQ failure STOPs; it never authorizes re-fetch
```

## 17. Environment failure classification

For a one-shot/private/production-gated operation, before the gate's durable
receipt is published:

```text
PRE_GATE_ENVIRONMENT_BLOCK
```

Examples: `.venv-real-execution` missing; wrong interpreter
(`PRE_GATE_WRONG_PYTHON_ENVIRONMENT`, including resolving to the general
`.venv`); Python version not exactly `3.12.10`; missing package; wrong
package version; missing Excel engine; parser synthetic-probe failure;
filesystem readiness failure; environment-lock mismatch (reviewed lock
candidate manifest missing/invalid/not matching the reviewed binding, lock
file SHA-256 mismatch, source-requirements canonical Git-bytes provenance
mismatch, or live `pip freeze --all` package set diverging from the
reviewed lock -- extra, missing, or version-drifted). These may be repaired
and the complete preflight rerun from the beginning, but only if no
protected boundary was crossed (§4).

For that same one-shot/private/production-gated operation, after the gate's
durable receipt is published:

```text
POST_GATE_ENVIRONMENT_FAILURE
```

Same underlying causes as above, but discovered only after gate
consumption. No retry authority is created by this classification -- it is
still a `POST_GATE_FAILURE` under §4/§10: no retry, no reset, no receipt
deletion, no reinterpretation of the same human authorization. This is
exactly the failure class this repository's own V8I terminal record
documents (`V8I_SOURCE_SNAPSHOT_TERMINAL_ADJUDICATION.json`:
`failure_class=EXECUTION_ENVIRONMENT_FAILURE`, a missing `pandas`
dependency discovered only after gate consumption) -- the entire purpose of
§15-§19 is to make that specific class of failure provable-closed-before-
the-gate for future protected execution, not to reopen or excuse that
already-terminal V8I attempt (§20).

For standing `RETRIABLE_PUBLIC_PLUMBING`, classify transport/setup failure
before the first complete payload as `PLUMBING_FAILURE_RETRIABLE`. After the
first payload, software/parser repair must use the same content-locked raw
bytes. A semantic or data-quality failure is `DATA_QUALITY_FAILURE` and
STOPs; it never authorizes fetch-until-PASS, provider substitution, or date
substitution. These classifications do not create or consume a one-shot
receipt.

## 18. Mandatory dependency-readiness question

For all future protected execution, the reviewer must answer:

```text
CAN_EVERY_REACHABLE_POST_GATE_SOFTWARE_DEPENDENCY_BE_PROVEN_READY_PRE_GATE?
```

Allowed answers: `YES`, `NO`, `UNKNOWN`. `NO` or `UNKNOWN` => STOP; do not
proceed across the applicable authority boundary until the answer is `YES`
with mechanical evidence (§15-§16), including the operational
synthetic-parser probe, not merely `import <package>` succeeding. Current
authority resolution is not a substitute for this operation-specific probe:
the checker or task must prove every reachable post-gate parser/runtime path
that the protected operation will use. This is a readiness control; it does
not prove that each public transport attempt requires a one-shot statistical
gate.

## 19. Exact environment lock/fingerprint

An explicitly reviewed command, run on the real target Windows machine
using the canonical interpreter ONLY (never the general `.venv`), generates
the exact environment record:

```powershell
.venv-real-execution\Scripts\python.exe -m pip freeze --all
```

The exact Windows-grounded resolved package set is committed as a dedicated
environment lock/fingerprint artifact (`REAL_EXECUTION_ENVIRONMENT_LOCK_
CANDIDATE.json` and `requirements-real-execution.lock.txt`), subject to its
own GPT exact-SHA independent review, before any future real execution is
authorized. A task that runs only in Claude Code Cloud (or any other
non-Windows environment) must never claim to have produced this
Windows-grounded lock.

A reviewed lock candidate was captured (`artifact_status =
CANDIDATE_NOT_FROZEN`, reviewed at commit
`107430894723c2bdc2f8493cb12c467fccd8665e`). Per
`REAL_EXECUTION_ENVIRONMENT_LOCK_ENFORCEMENT` (§15's `requirements-real-
execution.lock.txt` install-authority rule), that reviewed lock -- not the
unpinned `requirements-real-execution.txt` -- is the protected
installation/runtime package authority, and
`scripts/check_real_execution_env.py`'s `check_environment_lock` mechanical
check (binding to the reviewed manifest/lock/source-provenance/fixture
hashes and the live `pip freeze --all` package set) must `PASS` before
`REAL_EXECUTION_ENVIRONMENT_READY` can be `true`.

**`REAL_EXECUTION_ENVIRONMENT_FREEZE_PROMOTION`: explicit freeze/promotion
completed.** That lock-enforcement implementation was independently GPT
exact-SHA reviewed and Windows-grounded execution tested at implementation
commit `84d4512d800b18b858b6f129be9a4ba0ea73d4ca`; that validation was
itself recorded as a reviewed candidate evidence artifact at commit
`f52f31ab6305e321cd9e8e9855d6efd83238f552`
(`REAL_EXECUTION_ENVIRONMENT_WINDOWS_VALIDATION_EVIDENCE.json`).
`REAL_EXECUTION_ENVIRONMENT_FREEZE_RECORD.json` mechanically binds all
three (the reviewed lock candidate, the tested implementation, and the
reviewed Windows validation evidence) together, and
`scripts/check_real_execution_env.py`'s `check_freeze_record` mechanically
enforces that binding: it requires the live environment-lock check to
itself currently `PASS`, requires the freeze record's complete structural
and semantic content to exactly match the hardcoded reviewed binding,
cross-checks every identity against the same reviewed constants
`check_environment_lock` uses, and independently re-derives the canonical
Git blob SHA-256 of the reviewed Windows validation evidence artifact
(`git cat-file blob <sha>:<path>`, never a checked-out working-tree copy)
rather than trusting any self-reported hash. Only when that check PASSes
together with every existing readiness/lock/probe check does the checker
report:

```text
REAL_EXECUTION_ENVIRONMENT_FROZEN=true
```

This can only ever happen on a live run inside the exact canonical
`.venv-real-execution`, on the exact reviewed Windows/AMD64/win-amd64
platform, with the exact reviewed package set -- never from Claude Code
Cloud or any other non-Windows run, and never when any existing check is
failing; freezing never weakens, bypasses, or replaces any existing
environment-lock or readiness check.

**Environment freeze is NOT acquisition authorization.** It governs the
Python environment only. `future_protected_execution_authorized` remains
`false` in both the lock candidate and the freeze record. Future protected
execution still requires the applicable study-specific authority: a strict
human gate for one-shot/private/production work, or explicitly frozen
standing public-plumbing authority for the limited retriable class. A frozen
environment is never itself an authority substitute.

## 20. Prospective-only; V8I permanence

Sections 15-19 are prospective operational/governance hardening only. They
do not, by themselves or in combination:

- reopen V8I;
- authorize a V8I retry or a second JPX request under V8I;
- reset, delete, or reuse the V8I `HUMAN_V8I_SOURCE_SNAPSHOT_ACQUISITION_
  GATE` receipt;
- reuse the V8I human authorization;
- reconstruct or preserve the raw source bytes lost in the V8I terminal
  failure; or
- change V8I's `BLOCK_CLOSED` disposition in any way.

V8I remains permanently `BLOCK_CLOSED`, exactly as recorded in
`V8I_SOURCE_SNAPSHOT_TERMINAL_ADJUDICATION.json` and
`V8I_SOURCE_SNAPSHOT_EXECUTION_INCIDENTS.md`. Any future V8-lineage
source-snapshot attempt is a fresh, independent successor-study identity
with its own fresh gate, receipt key, and authorization grammar; §15-§19
exist only so that a future attempt's own gate cannot be consumed while a
provable, closeable software-environment gap (like V8I's missing `pandas`)
remains undiscovered.

V8J likewise remains immutable historical evidence under its recorded frozen
gate semantics. The evidence-tier wording above is prospective only and
applies only when a later human-approved frozen design explicitly selects it;
it does not reopen or reinterpret V8I or V8J.
