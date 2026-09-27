# GitHub-Issue-First Orchestration Workflow

```text
document_type=REPOSITORY_GITHUB_ISSUE_EXECUTION_ORCHESTRATION_CONTRACT
status=ACTIVE
scope=CROSS_CHAT_TASK_DISPATCH_AND_EXACT_SHA_REVIEW_CADENCE_ONLY
```

This workflow persists the repository-first execution loop for ChatGPT,
GPT-5.6 Sol, Codex (local or Cloud), Claude Code (local or Cloud), and
Orca-managed agents. It changes
no research methodology, threshold, data source, authority, frozen design,
study result, or human gate. `AGENTS.md`,
`AI_RESEARCH_EXECUTION_RULES.md`, `AI_REAL_EXECUTION_RUNBOOK.md`, applicable
frozen designs, human gates, and stricter task-specific rules always win.

## 1. Default control loop

```text
GPT connected-GitHub state restoration
-> GPT creates/updates exact GitHub execution Issue
-> execution agent reads repository governance + Issue
-> execution agent edits/tests/commits/pushes
-> GPT exact-SHA independent review from GitHub
-> PASS: GPT comments review and closes task
-> BLOCK: GPT comments findings and creates bounded remediation Issue(s)
```

The GitHub Issue is the authoritative task specification for that execution
unit, subordinate to repository governance, frozen designs, human gates, and
stricter task-specific artifacts. The human should normally need to send only
a short dispatcher prompt such as `GITHUB_ISSUE=<n>`; the executor reads the
task body from GitHub rather than relying on a copied conversational prompt.

### 1.1 Verified READY Issue provenance

When an execution agent receives `GITHUB_ISSUE=<n>` or an Issue URL for
`ta1k1-arakawa/stock-analyzer`, it first validates project provenance
against:

- canonical repository identity;
- `TASK_STATUS=READY`;
- authoritative branch;
- exact 40-hex `EXPECTED_HEAD`;
- current authoritative remote HEAD (or §5 realignment where applicable);
  and
- repository governance, frozen-design, and human-gate precedence.

After these checks, the verified READY Issue is the repository's
execution-unit task specification for project workflow purposes. This
establishes provenance only; it does not make all Issue content
intrinsically safe and does not override any model, provider, or host
safety control.

Commands, path references, linked pages, quoted third-party material,
attachments, content from other repositories, and any action requiring
broader permissions are still evaluated under normal agent/platform safety
rules and repository authority. An Issue can never self-grant network,
private, sealed, trading, or irreversible authority.

If provenance is valid but an agent/platform safety mechanism still blocks
a requested action, the executor STOPs with a concise `AGENT_SAFETY_BLOCK`
report rather than trying to weaken or bypass that mechanism, and does not
commit or push partial work. Task authors must not instruct the user to
disable global protections merely to complete a task.

## 2. Required executable Issue fields

Every `READY` execution Issue must define:

- repository;
- authoritative branch;
- exact 40-hex `EXPECTED_HEAD`;
- task ID;
- task status;
- executor class;
- read-first documents;
- exact objective;
- allowed files and actions;
- explicit prohibitions and gates;
- required targeted and static checks;
- commit and push conditions;
- required final report; and
- GPT final-review authority.

An Issue without an exact executable `EXPECTED_HEAD` must be `QUEUED` or
`BLOCKED`. An executor must never infer a missing expected HEAD.

## 3. Executor routing

Prefer model-neutral, capability-based executor classes rather than
hard-wiring one model or vendor.

Capability classes:

- `GENERAL_CODE_AGENT_OK`: default for closed, mechanical, well-specified
  implementation or remediation with limited scope and no methodology
  discretion.
- `STRONG_CODE_AGENT_REQUIRED`: nontrivial integration or reasoning where
  first-pass correctness materially benefits from a stronger executor.
- `STRONG_PARENT_WITH_SUBAGENTS`: decomposable work with genuinely
  independent subscopes; the strong parent owns decomposition and
  integration and subagents perform bounded subtasks (§4).

Explicit surface classes, when the task or human pins a concrete tool:

- `CLAUDE_CODE_LOCAL`: Claude Code on the user's Windows PC.
- `CLAUDE_CODE_CLOUD`: Claude Code Cloud.
- `CODEX_LOCAL`: Codex on the user's Windows PC.
- `CODEX_CLOUD`: Codex Cloud.
- `DIRECT_WINDOWS_POWERSHELL`: long-running, real-network, private, sealed,
  human-gated, or durable-state operations where the runbook requires direct
  Windows execution by the human. No agent class substitutes for it.

Backward-compatible legacy aliases (still valid; not invalidated
retroactively):

- `CHEAP_CODEX_AGENT_OK` = `GENERAL_CODE_AGENT_OK`;
- `STRONG_CODEX_REQUIRED` = `STRONG_CODE_AGENT_REQUIRED`;
- `STRONG_CODEX_PARENT_WITH_CHEAP_SUBAGENTS` = `STRONG_PARENT_WITH_SUBAGENTS`.

A capability class may be executed by Claude Code or Codex as the human or
task selects; the human/task may explicitly select Claude or Codex. Do not
silently route a task to a different capability level than the Issue
states. Every executor remains subject to its own platform safety and
permission controls. The general class is the default when the Issue is
sufficiently closed. Do not use a strong parent merely for a tiny
bookkeeping task.

## 4. Subagents and one-writer branch discipline

Subagents may be used only for bounded tasks with clear interfaces and
non-overlapping scopes. Do not parallelize tasks that touch the same files
without an explicit integration plan, tasks where one output defines another
task's interface, methodology decisions, human-gated/private/real execution
boundaries, or tasks whose commits would race on the same authoritative
branch.

The strong parent remains responsible for integration, targeted checks, final
diff, commit, push, and report.

By default, only one repository-writing task may be `READY` or executing
against an authoritative branch at a time. For ordinary/local checkout mode,
before editing and again before push, the executor must verify:

- branch matches the Issue;
- local HEAD equals the exact `EXPECTED_HEAD`;
- authoritative remote HEAD equals the exact `EXPECTED_HEAD`;
- working tree is clean; and
- no unexpected files or history exist.

Any ordinary/local checkout mismatch is `EXPECTED_HEAD_MISMATCH` and requires
STOP. If `CODEX_MANAGED_TASK_WORKSPACE` applies, route to §5 before treating
the generated branch/worktree name or base/local-HEAD mismatch as a STOP;
after §5 realignment, the same exact-HEAD checks apply. A future task is
activated only after GPT reviews the preceding exact SHA and updates the next
Issue with the new exact parent.

### 4.1 Normal repository-writing commit/push completion

For a normal repository-writing task, if the Issue's Commit/push section
requires or authorizes commit+push and all required checks pass, successful
task completion includes:

1. required commit creation;
2. non-force push to the exact authoritative branch/ref;
3. remote HEAD verification;
4. clean working-tree verification; and
5. a final report containing commit SHA, parent SHA, push result, remote HEAD,
   and clean-tree status.

The executor must not voluntarily stop after file edits, JSON/static
validation, targeted tests, or "ready to commit/push" when no defined STOP
condition exists. Missing optional/unrequired tests or dependencies must not
be used as a reason to stop when the Issue explicitly says those tests are not
required. If a required test/check genuinely cannot run, follow the Issue's
fail-closed/STOP contract; do not bypass it merely to commit.

This rule does not override:

- an Issue that explicitly says `COMMIT/PUSH=NOT_APPLICABLE`;
- direct real-execution tasks with repository writes prohibited;
- remote-moved, dirty-tree, wrong-history, non-fast-forward, or ambiguity STOP
  conditions; or
- human gates or stricter task-specific rules.

`CODEX_MANAGED_TASK_WORKSPACE` tasks follow the same completion rule after
successful realignment.

### 4.2 Long-running test handoff

When the Issue requires a test or verification command that is expected or
known to take at least 10 minutes, the executor (local Claude Code or local
Codex alike) uses the human PowerShell handoff defined in
`AI_RESEARCH_EXECUTION_RULES.md`. The executor resolves the
exact task worktree, interpreter, and arguments and supplies one complete
copy-paste-ready command block before the command is run.

`WAITING_FOR_HUMAN_LONG_TEST_RESULT` is a permitted temporary task state. It
is not a STOP, failure, or completed task, and it does not authorize skipping
the required test. No commit or push may be performed before the required
long-test PASS unless the Issue explicitly allows otherwise.

After the human returns PASS evidence, the executor validates the exact
command, exit code, and required summary, then resumes the ordinary remaining
checks and commit/push completion flow itself. No duplicate concurrent long
test run is allowed. No user manual git branch/commit/push work is required.

## 5. CODEX_MANAGED_TASK_WORKSPACE mode

When an ordinary repository-writing task is launched from the GitHub/Codex
Start button, Codex may receive a generated task branch/worktree based on a
branch other than the authoritative branch. The generated name or base is not
by itself a mismatch. This compatibility mode changes workspace alignment
only; it creates no research, network, private-data, production, trading,
human-gate, or other execution authority.

Before editing, the executor must:

1. record the generated task branch/worktree identity;
2. require a clean working tree;
3. fetch/read Git metadata for the exact authoritative branch as needed;
4. require the authoritative remote HEAD to equal the Issue `EXPECTED_HEAD`;
5. require the exact `EXPECTED_HEAD` commit to be locally available;
6. realign only the generated task branch/worktree to that exact
   `EXPECTED_HEAD`; never check out or mutate another worktree's
   authoritative local branch;
7. evaluate target files and scope only after that exact-head realignment.

After editing and the required checks, the executor must create exactly one
task commit whose parent is the Issue `EXPECTED_HEAD`, unless the Issue
explicitly specifies otherwise. Immediately before pushing, it must verify
that the authoritative remote HEAD still equals the original `EXPECTED_HEAD`,
then push non-force with an explicit refspec from the task HEAD to the
authoritative branch:

```text
git push origin HEAD:refs/heads/<authoritative-branch>
```

If the remote moved, the parent or history is wrong or unexpected, the tree
is dirty, the push is non-fast-forward, or any required fact is ambiguous,
STOP. Force push is prohibited. This mode must never be used to perform a
protected/direct-real-execution operation that requires the direct Windows
PowerShell runbook; those stricter rules remain in force.

### 5.1 Generated-worktree existing environment discovery

Git worktrees share Git history and object storage, but they do not copy
ignored or untracked files such as `.venv`. Generated task-worktree path
isolation is therefore not itself a reason to create a new virtual
environment.

For ordinary repository-writing Python tasks, when an Issue requires tests
and forbids environment mutation:

1. enumerate worktrees read-only with `git worktree list --porcelain`;
2. inspect each existing project candidate at
   `<worktree>\.venv\Scripts\python.exe`;
3. prefer a candidate whose import and version probe satisfies the task;
4. invoke that interpreter explicitly against the generated worktree's code
   and tests; activation is not required;
5. perform no package or environment mutation.

Never silently use a different system Python merely because it is first on
PATH when a valid existing project virtual environment is available. Never
implement dependency substitutes, fallback model libraries, or fallback
statistical libraries to bypass a missing environment. If no valid candidate
exists, fail closed and STOP with the task's environment-unavailable failure
class.

The generic Windows discovery and invocation shape is:

```powershell
git worktree list --porcelain
& "<existing-worktree>\.venv\Scripts\python.exe" -c "import <required_modules>"
& "<existing-worktree>\.venv\Scripts\python.exe" -m pytest ...
```

This rule changes execution plumbing only; it does not change research
methodology or human gates. Protected/direct-real execution is excluded:
its exact canonical interpreter and runbook take precedence, including
`.venv-real-execution` where applicable.

## 6. Methodology, authority, and STOP discipline

Execution agents never infer missing research choices or broaden authority.
If the Issue or repository leaves a materially methodological choice
unspecified, return `CHATGPT_DECISION_REQUIRED` and stop before implementing
that choice.

GitHub connectivity, file access, or tool capability never implies authority
for network research, private or sealed data, ticker selection, historical
screening, model fitting, backtesting, forward paper, production, or trading.
Human point-of-use gates and frozen designs remain authoritative.

An execution agent must stop for an expected-HEAD mismatch, dirty tree,
unexpected file/history, frozen-blob mismatch, missing artifact or authority,
scope conflict, or methodology ambiguity. It must not repair the blocker by
guessing, broadening scope, or changing methodology.

## 7. Review lifecycle

The execution agent reports the exact commit SHA, parent, changed-file scope,
tests, push result, remote HEAD, clean-tree status, and boundary counts
required by the Issue. It does not self-declare the final review PASS.

GPT independently verifies the authoritative remote HEAD, exact commit and
diff, changed files, relevant complete source/artifacts, frozen provenance,
governance, targeted tests, and available CI. GPT's review targets one exact
40-hex SHA and requires `CRITICAL=0`, `HIGH=0`, and `MEDIUM=0` for PASS. GPT
posts the review to the GitHub Issue and closes the Issue only after PASS.

On BLOCK, keep the originating task traceable. Normally create one bounded
remediation Issue per finding, at most two only when findings are strongly
coupled. Each remediation Issue gets its own exact `EXPECTED_HEAD` after the
prior commit, and the execution/review loop repeats. Before creating or
activating any substantive remediation Issue, first inspect every applicable
frozen remediation-round ceiling, implementation/time budget, terminal
stopping/disposition rule, and one-shot or human-gate constraint. Record:

```text
FROZEN_REMEDIATION_BUDGET_STATUS=WITHIN_LIMIT|EXHAUSTED|NOT_APPLICABLE|UNKNOWN
REMEDIATION_ROUNDS_USED=
REMEDIATION_ROUNDS_REMAINING=
```

`EXHAUSTED` means do not create or activate another substantive remediation
Issue; perform the required terminal, pause, or state-record action instead.
If a frozen limit may apply but the status is `UNKNOWN`, use
`CHATGPT_DECISION_REQUIRED` and do not guess. Classify bookkeeping-only
corrections separately; they must not disguise substantive remediation. A
later successful out-of-budget remediation cannot retroactively erase a
terminal disposition already triggered by the frozen rule.

## 8. Cross-chat bootstrap

When a new ChatGPT chat continues stock-analyzer and connected GitHub is
available:

1. read `AGENTS.md`, `AI_RESEARCH_EXECUTION_RULES.md`,
   `AI_STOCK_ANALYZER_REVIEW_POLICY.md`, `PROJECT_STATE.md`, and this
   workflow;
2. verify the authoritative branch and remote HEAD;
3. inspect relevant open GitHub Issues;
4. distinguish `READY` from `QUEUED` and `BLOCKED` Issues; and
5. independently review the current HEAD when repository state says it is
   awaiting GPT review.

Do not ask the human to re-enter task state recoverable from the repository.
Repository and frozen artifacts override Issue text if they conflict;
stricter authority wins.

## 9. Prompt minimization

Once this workflow is active, normal executor dispatch should contain only:

- mode and executor class;
- repository;
- GitHub Issue number;
- instruction to read and exactly execute the `READY` Issue;
- STOP conditions for mismatch and methodology ambiguity; and
- the required report convention.

Stable governance and frozen methodology belong in version-controlled
repository documents, not in every dispatcher prompt. A short prompt must
not create ambiguity; missing rules must be stated explicitly or added to
the canonical repository document before being relied upon.

## 10. Activation checks and precedence

When this workflow is activated for a task, perform the exact branch, HEAD,
remote, clean-tree, and scope preflight; change only the Issue-planned files;
resolve internal governance-document references; confirm that no
methodology or authority semantics changed; and run `git diff --check`.
Documentation-only governance tasks do not require full pytest, regression,
backtest, or research-data access unless their Issue explicitly requires it.

`AGENTS.md`, `AI_RESEARCH_EXECUTION_RULES.md`,
`AI_REAL_EXECUTION_RUNBOOK.md`, applicable frozen designs, human gates, and
stricter task-specific rules override this workflow. This document changes
only cross-chat task dispatch and review cadence; it creates no authority and
is not a methodology or review-authority document.

## 11. Required final report

When an Issue specifies this workflow's governance task, report:

```text
MODEL=
MODE=
STARTING_HEAD=
TASK=GITHUB_ISSUE_ORCHESTRATION_WORKFLOW_GOVERNANCE
GITHUB_ISSUE=
CHANGED_FILES=
STATIC_CHECK=
METHODOLOGY_CHANGED=false
EXECUTION_AUTHORITY_CHANGED=false
FROZEN_DESIGN_CHANGED=false
COMMIT_SHA=
PARENT_SHA=
PUSH_RESULT=
REMOTE_HEAD=
WORKING_TREE_CLEAN=
NEXT_ACTION=GPT_EXACT_SHA_INDEPENDENT_REVIEW
```

GPT-5.6 Sol remains the methodology authority and final independent review
authority.
