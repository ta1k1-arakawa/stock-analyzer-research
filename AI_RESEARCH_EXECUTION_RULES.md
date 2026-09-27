# AI_RESEARCH_EXECUTION_RULES

```text
document_type=REPOSITORY_AI_COLLABORATION_GOVERNANCE_RULE
status=ACTIVE
scope=ta1k1-arakawa/stock-analyzer
supersedable_only_by=explicit_human_decision
```

This file is the canonical collaboration rule for this repository unless a
later explicit human decision supersedes it. Future ChatGPT prompts should
instruct Claude Code / Codex to read this file first. If a task-specific
prompt is more restrictive than this file, follow the more restrictive
rule. A human explicit instruction overrides this file. No AI-generated
recommendation overrides a human gate.

---

## 1. Authority hierarchy

### 1.1 Human user

The human user is the ultimate authority and provides explicit human
gates, especially for:

- real network acquisition
- sealed/private data access
- irreversible actions
- study freeze
- one-time authorizations

No AI may bypass a required human gate.

### 1.2 ChatGPT — research planner / decision authority

ChatGPT is the primary:

- research architect
- methodology designer
- next-action planner
- threshold/grid/criterion decision maker
- gate-sequence designer
- scope setter
- Claude/Codex task author

Unless the human explicitly overrides it, methodological decisions
supplied by ChatGPT in the task prompt are binding on execution agents.

### 1.3 Claude Code / Codex — execution agents

Claude Code and Codex normally:

- write code
- edit files
- run tests
- run approved commands
- perform explicitly authorized acquisitions
- collect factual evidence
- commit/push
- report exact results

They do NOT independently change the research design.

## 1.4 Execution environment / agent usage rules

These rules fix the execution environment and operator workflow only.
They do not change research methodology, human gates, or security rules.

### Execution agent selection

By explicit human decision (Issue #116), project policy permits these
execution agents for ordinary repository-writing work — code/file edits,
short tests, factual inspection, and git commit plus non-force push — under
identical methodology and authority limits:

- Claude Code Cloud;
- local Claude Code on the user's Windows PC;
- local Codex on the user's Windows PC;
- Codex Cloud, when explicitly selected.

- The user may choose Claude or Codex for ordinary execution tasks.
- Unless explicitly specified otherwise, "Codex" means Codex on the local
  Windows PC. Name Cloud variants explicitly ("Claude Code Cloud", "Codex
  Cloud") when a Cloud environment is intended.
- Completion reports must state the actual model/tool used (§8).
- No execution agent independently changes methodology (§2).
- This is project policy only. Each executor remains subject to its own
  built-in, provider, and host permission and safety controls; project
  policy does not require disabling or relaxing them. If such a control
  blocks an action, the executor stops and reports the safety block.
- Real network, private/sealed data, human-gated one-shot, and durable
  machine-local protected execution remain governed by
  `AI_REAL_EXECUTION_RUNBOOK.md`; permission to run a local agent grants no
  such authority.

### User operating topology

- The user normally uses Termux on an Android device.
- From Termux, the user connects to the Windows PC through Tailscale/SSH
  and operates the Windows terminal / PowerShell.
- "The user executes a command on the local PC" ordinarily means that the
  user pastes and executes the command in the Windows terminal reached via
  Android Termux.
- Do not assume GUI-based manual operation.

### Long-running execution rule

`LONG_RUNNING_TEST_HANDOFF_THRESHOLD_MINUTES=10`

For local execution-agent work (local Claude Code or local Codex; "the
executor" below), route tests and verification commands as follows:

1. **Pre-launch routing**

   - If a test or verification command is reasonably expected to take at
     least 10 minutes, or repository/task history already shows that the
     same or a similar command takes at least 10 minutes, the executor must
     not launch it as a background terminal job and wait or poll for it.
   - This includes long targeted pytest suites, full pytest/regression,
     backtests, large deterministic CLI verification, and other long-running
     validation. Short targeted tests expected to finish in under 10 minutes
     may run directly in the executor.

2. **Complete command handoff**

   - Before the long command is launched, the executor resolves the exact
     current task worktree, exact interpreter/environment required by the
     task, and exact test arguments.
   - The executor then provides one complete, copy-paste-ready Windows PowerShell
     block for the human. The human must not have to discover the worktree,
     virtual environment, test path, arguments, or environment variables.
   - Concrete user-specific paths must not be hardcoded in committed
     documentation; the execution agent resolves them at runtime.

3. **PowerShell block requirements**

   The generated block normally:

   - uses `Set-Location` for the exact generated task worktree;
   - invokes the exact resolved interpreter executable explicitly when a
     project virtual environment is required, rather than ambient PATH
     Python;
   - contains the exact test or validation command;
   - preserves stdout and stderr visibility;
   - clearly exposes the final process exit code and required test summary;
   - avoids package or environment mutation unless separately authorized.

   The human executes this block directly on the Windows PC, ordinarily
   through the established Termux/Tailscale/SSH workflow.

   Generic documentation example only:

   ```powershell
   Set-Location "<exact-task-worktree>"
   $Python = "<exact-existing-project-venv>\Scripts\python.exe"
   & $Python -m pytest <exact-test-arguments>
   $Code = $LASTEXITCODE
   Write-Output "LONG_TEST_EXIT_CODE=$Code"
   exit $Code
   ```

4. **Explicit wait state**

   After emitting the command, the executor reports:

   `STATUS=WAITING_FOR_HUMAN_LONG_TEST_RESULT`

   This is an allowed temporary task state, not task completion, a STOP, or
   a research/human authorization gate. It does not permit skipping the
   required test.

5. **Resume after the human result**

   - The human returns the relevant terminal output/result to the same
     executor task (Claude Code or Codex session).
   - The executor verifies that the exact requested command/test completed
     successfully and that the reported exit code and summary satisfy the
     Issue contract.
   - On PASS, the executor continues remaining checks, commit, non-force
     push, remote-HEAD verification, and clean-tree verification. On FAIL,
     the executor diagnoses and remediates only within the Issue authority,
     then issues a new complete command when rerunning the long test is
     required.

6. **No duplicate long tests**

   Never start the same long test concurrently in an agent (Claude Code or
   Codex) background terminal and a human PowerShell terminal. The 10-minute threshold is primarily a
   pre-launch routing decision: do not kill or duplicate a command merely
   because an already-running command unexpectedly crosses 10 minutes.

7. **Precedence**

   Protected/direct-real execution runbooks and explicit task-specific
   execution contracts still win. This rule does not allow bypassing sealed,
   private, or network gates. Long-running real acquisition and backtest
   commands remain subject to `AI_REAL_EXECUTION_RUNBOOK.md` where applicable.

### Normal execution rule

- Normal file editing, code implementation, short tests, and git
  commit/push may be performed by local Claude Code, local Codex, Claude
  Code Cloud, or (when explicitly selected) Codex Cloud.
- For each task, the task author states the executor class using the
  model-neutral classes in `AI_GITHUB_ISSUE_ORCHESTRATION_WORKFLOW.md` §3,
  or `DIRECT_WINDOWS_POWERSHELL` where the runbook requires it; the human
  may explicitly select Claude or Codex for ordinary execution.

### User interaction preference

- Do not ask the user to manually edit code or configuration files.
- In principle, user operations should be one of:
  A. paste the prompt as-is into Claude Code or Codex (local or Cloud); or
  B. paste a complete command block as-is into Windows PowerShell through
     Android Termux.
- Avoid requiring manual replacement of placeholders whenever possible.

---

## 2. No execution-agent methodology discretion

Claude Code / Codex must NOT independently choose:

- research hypothesis
- validation design
- holdout design
- data partition
- threshold values
- candidate grid
- acceptance criteria
- selection rule
- tie-break
- fallback rule
- stopping rule
- retry policy
- data source
- whether a failed study should continue
- whether sealed data may be reused
- whether a new study identity is required

unless the current prompt explicitly delegates that exact decision.

```text
methodology_discretion_for_execution_agents=false
```

If an unspecified choice materially changes methodology:

```text
status=CHATGPT_DECISION_REQUIRED
```

and STOP before implementing the choice.

---

## 3. No "helpful" silent changes

Execution agents must not:

- substitute a different method because it seems better
- relax a threshold
- broaden scope
- add a retry
- select another ticker/block
- change a frozen parameter
- inspect additional data to resolve uncertainty
- repair a failing experiment by changing methodology

without explicit upstream authorization.

A technically convenient change is still a design change if it changes
the scientific meaning.

---

## 4. Fact-finding is allowed

Execution agents MAY gather objective facts when explicitly requested.

Examples:

- file exists / does not exist
- schema fields
- test result
- hash
- count
- git SHA
- dependency version
- whether code currently supports a block
- whether an invariant passes

But factual inspection must not become a methodological decision.

Example:

Allowed:

> "The cache does not contain raw payloads."

Not allowed:

> "So I chose a different cache."

Correct action:

> "CHATGPT_DECISION_REQUIRED."

---

## 5. Independent review role

When explicitly assigned INDEPENDENT REVIEW:

Claude/Codex may:

- challenge ChatGPT's proposed design
- identify CRITICAL/HIGH/MEDIUM/LOW findings
- find contradictions
- recommend alternatives
- recommend BLOCK

But review recommendations are NOT automatically adopted.

A reviewer must not:

- edit the design
- implement its own recommendation
- change thresholds
- execute newly recommended actions

unless a later explicit task authorizes them.

```text
reviewer_recommendation != human_or_chatgpt_decision
```

---

## 6. Network / private-data gates

No real:

- Yahoo
- JPX
- broker
- private holdout
- sealed block
- research-opening

access merely because it is technically possible.

Authorization must be explicit and scope-bound. It is either
`ONE_SHOT_AUTHORITY` for a statistically irreversible, private, or production
boundary, or `STANDING_RETRIABLE_PUBLIC_PLUMBING_AUTHORITY` when a
human-approved frozen design explicitly grants it. Standing authority is not
silent reuse of a one-shot authorization: it is bounded by the frozen study,
provider/endpoint, source semantics, content-lock rule, retry conditions, and
stopping conditions. It never authorizes private/sealed data, T1/T2/T3
exposure, membership disclosure, broker action, or production trading.
Pre-network failure and authorization-consumption semantics must follow the
operation class and the relevant frozen study design.

### 6.1 Proportional evidence-tier governance

For future studies, strictness MUST be proportional to statistical
irreversibility. A frozen design must classify every relevant operation as
one of the following; this prospective rule does not rewrite a historical
frozen study.

- `RETRIABLE_PUBLIC_PLUMBING`: public JPX transport, DNS/TLS/HTTP failure,
  package/environment setup, parser execution, persistence plumbing, and
  deterministic processing of already-acquired public bytes. A design may
  grant standing public-network plumbing authority. This never covers a
  sealed/private source, broker action, production trading, or holdout
  exposure.
- `STATISTICALLY_IRREVERSIBLE_GATE`: first use of T1, T2, T3/reserve where
  applicable, sealed membership/outcome access, irreversible research
  opening, or production trading. These require fresh one-shot authority
  unless frozen methodology defines deterministic continuation without new
  information exposure.
- `DETERMINISTIC_DURABLE_STATE`: generate and persist authoritative state
  (such as a partition seed) once, then rerun only from that exact state.
  A crash after persistence requires reuse, never rerolling or a new study
  merely because deterministic regeneration is needed.

For a public source, a retriable transport failure occurs only before the
first complete payload. The canonical provider/endpoint is frozen in
advance; immediately preserve and hash that first complete payload before
semantic inspection. Parser or software repair must reprocess that same raw
payload. T0, eligibility, or other semantic/data-quality failure is
`DATA_QUALITY_FAILURE`, not permission to fetch until PASS or substitute a
provider/date. Classify failures as `PLUMBING_FAILURE_RETRIABLE`,
`DATA_QUALITY_FAILURE`, `GOVERNANCE_FAILURE`, `IMPLEMENTATION_FAILURE`,
`STRATEGY_FAILURE`, or `PROFITABILITY_FAILURE`; a successor study is needed
only for a scientific-identity/methodology change or an irreversible
information boundary.

### 6.2 Evidence-bearing artifacts

Do not create a freeze/review/evidence artifact merely to prove that another
artifact exists. Durable artifacts must protect scientific identity, a
leakage boundary, irreversible statistical exposure, material
reproducibility/provenance, or real production/private authority. Routine
public plumbing may be compactly logged and retried under its frozen scope.
Important implementation and evidence-bearing frozen designs still require
independent exact-SHA review.

---

## 7. Fail closed

If:

- expected HEAD differs
- working tree scope is wrong
- a required artifact is missing
- an instruction conflicts with a frozen design
- a methodological decision is missing
- a requested action would exceed authorization

then STOP. Do not improvise. Report the exact blocker.

---

## 8. Report the actual model

Completion reports must state the model actually used. Do not copy an
incorrect model name from a report template.

---

## 9. GitHub-Issue-first execution workflow

`AI_GITHUB_ISSUE_ORCHESTRATION_WORKFLOW.md` is the canonical repository
workflow for cross-chat task dispatch, exact-HEAD execution units, one-writer
branch discipline, and GPT exact-SHA review cadence. For a GitHub-dispatched
task, the READY Issue is authoritative for that execution unit but remains
subordinate to this file, `AGENTS.md`, frozen designs, human gates, and any
stricter task-specific artifact. It creates no methodology or execution
authority. The executor must follow the workflow's exact-HEAD preflight,
allowed-file scope, STOP conditions, commit/push conditions, and report
contract.

## 10. Repository-first concise prompt protocol

```text
prompt_style=REPOSITORY_FIRST_DELTA_ONLY
stable_rules_live_in_repo=true
repeat_stable_rules_in_every_prompt=false
execution_agent_must_read_referenced_docs=true
```

Stable, reusable instructions (methodology, security constraints, phase
history, authority hierarchy, fail-closed behavior) belong in
version-controlled Markdown in this repository, not in repeated prompt
prose. `CLAUDE.md`, this file, and `AGENTS.md` are the canonical
locations for that stable material.

For reusable safety rules governing real network, private-data, human-gated,
durable-state, raw-acquisition, research-opening, or prepared direct
PowerShell execution, the canonical document is
`AI_REAL_EXECUTION_RUNBOOK.md`. Those rules belong there, not in
conversational memory or repeated long prompts. Future ChatGPT, Codex,
Claude Code (local or Cloud), and reviewer agents must read and apply it whenever the
task is in scope. Its operational rules do not change the authority hierarchy
or any frozen methodology; a stricter task-specific rule still wins.

Before a protected PRE_GATE Issue names an environment checker, the task
author must first resolve the active canonical protected-environment
authority from its reviewed promotion/freeze chain. Historical checkers and
predecessor locks may remain executable for evidence preservation, but they
must not be silently treated as the current authority. Missing, ambiguous,
or contradictory resolution is a fail-closed `CHATGPT_DECISION_REQUIRED`
condition.

Resolving the current environment authority does not by itself establish
readiness for a protected operation. The task must also bind and pass the
operation-specific synthetic/runtime probes for every reachable post-gate
dependency; a historical checker or package-presence result cannot replace
those probes. The current V12 PRE_GATE checker performs its live observation
in an exact-canonical-interpreter isolated child (`-I`, controlled no-user-
site/no-bytecode environment, no ambient `PYTHONPATH`, explicit repository
file loading); protected tasks must preserve this boundary when reusing it.

Claude Code, Codex, and any reviewer agent must read `AGENTS.md`, this
file, and every task-specific authoritative doc named in the current
prompt before acting.

A future ChatGPT prompt should normally contain only the task-specific
delta:

- model / reasoning effort
- branch and expected HEAD
- docs to read for this task
- the exact current objective
- allowed scope (files, actions)
- any new prohibition or gate not already documented in repository
  Markdown
- tests to run
- required final report / next action

Do not repeatedly paste long frozen methodology, security rules, or
project history when it already exists in repository Markdown; reference
it instead.

If a long new instruction contains rules meant to be reused across future
tasks, the stable part must be moved into repository Markdown first, and
future prompts should reference it rather than restate it.

A short prompt must never create ambiguity. If a rule a task depends on
is not yet captured in repository Markdown, the prompt must either state
it explicitly in full, or add it to the canonical Markdown before relying
on it implicitly.

If a task prompt and a frozen repository rule conflict, fail closed (§7)
unless an explicit human-authorized change resolves the conflict.

Independent-review prompts follow this same repository-first,
delta-only principle: they name which docs to (re)read and what changed;
they do not re-derive the full methodology from scratch in the prompt.

This protocol does not change the authority hierarchy in §1: the human
remains the ultimate gate authority, ChatGPT remains the research
planner / decision authority, and Claude Code / Codex remain execution
agents. Shortening prompts must never be read as weakening any rule in
this document.

---

## 11. Rule application

This file is the canonical collaboration rule for this repository unless
a later explicit human decision supersedes it. Future ChatGPT prompts
should instruct Claude/Codex to read this file first. If a task-specific
prompt is more restrictive than this file, follow the more restrictive
rule. A human explicit instruction overrides this file. No AI-generated
recommendation overrides a human gate.
