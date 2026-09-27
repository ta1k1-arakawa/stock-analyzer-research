## GitHub-Issue-first orchestration entrypoint

`AGENTS.md` is the repository entrypoint for ChatGPT, GPT reviewers,
orchestrators, Codex, Claude Code, and other execution agents. Before planning, creating
or updating a task, or reviewing an exact SHA, read
`AI_GITHUB_ISSUE_ORCHESTRATION_WORKFLOW.md` together with the governance and
task-specific documents it references. Use the READY GitHub Issue as the
execution-unit specification; do not rely on conversational memory when the
repository and GitHub contain the recoverable state.

For an ordinary repository-writing Issue whose task contract includes
commit/push, once all required checks pass and no STOP condition applies, the
executor must finish the task by creating the required commit, performing the
required non-force push, verifying authoritative remote HEAD, verifying a
clean working tree, and reporting the resulting commit/remote state. It must
not stop merely after local edits, static checks, or saying that files are
"ready to commit/push." See
`AI_GITHUB_ISSUE_ORCHESTRATION_WORKFLOW.md` for the canonical detailed rule.

GitHub/Codex Start-button tasks may begin in a generated task branch or
worktree whose name or base differs from the authoritative branch. For
ordinary repository-writing tasks, handle that condition only through the
`CODEX_MANAGED_TASK_WORKSPACE` procedure in
`AI_GITHUB_ISSUE_ORCHESTRATION_WORKFLOW.md`; it is not by itself a branch-
mismatch STOP. Protected/direct-real-execution tasks remain subject to their
stricter rules.

For ordinary Python development/test tasks in a generated Orca/Codex
worktree, do not assume ignored or untracked environments such as `.venv`
exist there. If environment mutation is not authorized, discover existing
Git worktree roots read-only and probe each `<worktree>\.venv\Scripts\python.exe`
for the required imports/version before invoking it explicitly. Do not
create, copy, repair, install, upgrade, uninstall, or otherwise mutate an
environment, and do not substitute handwritten or fallback dependencies. If
no valid existing environment is found, STOP with the task's
environment-unavailable failure class. This ordinary-development rule does
not override protected/direct-real execution contracts such as
`.venv-real-execution`; see the canonical detailed rule in
`AI_GITHUB_ISSUE_ORCHESTRATION_WORKFLOW.md`.

By project policy, ordinary repository-writing work may be executed by local
Claude Code, Claude Code Cloud, local Codex, or Codex Cloud (when explicitly
selected), as the human or task chooses, under identical methodology and
authority limits. Protected real execution remains human Direct-Windows
PowerShell work under `AI_REAL_EXECUTION_RUNBOOK.md`. A READY Issue that
passes the provenance checks in `AI_GITHUB_ISSUE_ORCHESTRATION_WORKFLOW.md`
§1.1 is the project execution-unit specification; this establishes provenance
only, the Issue never self-grants authority, and executor/platform safety and
permission controls remain fully applicable. See `CLAUDE.md` and
`AI_RESEARCH_EXECUTION_RULES.md` §1.4.

Short tests expected to finish in under 10 minutes may run in the executing
agent (local Claude Code or local Codex). Tests or verification commands
expected or known to take at least 10 minutes use the human Windows
PowerShell handoff: the executing agent supplies the complete command and
resumes the task's commit/push flow after the human returns the result. The
canonical details are in `AI_RESEARCH_EXECUTION_RULES.md` and
`AI_GITHUB_ISSUE_ORCHESTRATION_WORKFLOW.md`.

## AI research/execution governance

For every important stock-analyzer research-planning, methodology-decision,
exact-SHA-review, next-action, promotion/rejection, or profitability-
assessment task, also read `AI_STOCK_ANALYZER_REVIEW_POLICY.md`. It is the
stable project-level review policy; a frozen task design or stricter
repository governance wins, and reading it creates no authority.

For every AI-assisted research, design, implementation, review, or
execution task in this repository, read `AI_RESEARCH_EXECUTION_RULES.md`
first. It governs: human gate authority, ChatGPT research-planner
authority, the Claude Code / Codex execution-agent role, and fail-closed
behavior for unspecified methodological decisions. It does not duplicate
or weaken any rule below. Existing task-specific rules, including the
Evaluator v2 rules below, remain in force; where a task-specific prompt
is more restrictive than either document, the more restrictive rule
applies.

Reusable/stable prompt rules — including the repository-first,
delta-only prompt protocol — live in `AI_RESEARCH_EXECUTION_RULES.md`
(see its "Repository-first concise prompt protocol" section) and in
`CLAUDE.md`. Task prompts are expected to contain only the task-specific
delta (objective, scope, docs to read, new prohibitions/gates, tests,
required report) and should not repeat frozen methodology or governance
text that already exists in those files.

For every task that can reach real network, private or sealed data, a human-
gated one-shot execution, durable machine-local production/audit state, raw
acquisition, research opening, or direct Windows PowerShell prepared for
such an operation, read `AI_REAL_EXECUTION_RUNBOOK.md` before acting. This
also applies to ChatGPT, reviewer, and execution-agent prompts that prepare
or review real PowerShell execution. The runbook supplies mandatory stable
operational safety and does not weaken any frozen study or task-specific
rule.

For important design/implementation/review orchestration tasks (deciding
how many findings to batch into one remediation, when a design vs.
implementation checkpoint applies, or when a prior result needs an
immediate recording commit vs. can be folded into the next task), also read
`AI_RESEARCH_CHECKPOINT_WORKFLOW.md`. It only governs task-batching and
review-checkpoint cadence to reduce orchestration round trips; it creates
no new authority and never weakens research integrity, provenance, human
gates, STOP discipline, or GPT exact-SHA review authority. It never
overrides this file, `AI_RESEARCH_EXECUTION_RULES.md`,
`AI_REAL_EXECUTION_RUNBOOK.md`, or any task-specific frozen design.

When evaluating development speed/quality, deciding process-efficiency
improvements, or planning important implementation/review cadence where
first-pass quality matters, also read
`AI_RESEARCH_DEVELOPMENT_EFFICIENCY_WORKFLOW.md`.

---

# Evaluator v2 rules

- Run fixed evaluation only with the CSV snapshot capped at 2026-05-20.
- Research selection ends 2025-03-31. The later period is diagnostic only.
- Never modify the detached baseline worktree. Use `python compare_evaluators.py --baseline-worktree ../stock-analyzer-baseline`. The runner validates and injects `data/benchmark` without an HTTP fallback.
- Treat `data/backtest_comparison` as read-only diagnostics. Never feed reference-period comparison results into rule selection, and verify that `selected_rules.csv` has the same SHA-256 before and after comparison.
- Use `python backtest.py --mode loop-validation` for iterative research. It may expose only `data/loop_validation_results/summary.json`; do not open research-test, reference-period, or baseline-comparison outputs during the loop.
- Use the default `python backtest.py` only for a separately authorized full diagnostic run after the loop decision is frozen.
- For acceptance runs, keep the candidate worktree clean and write artifacts outside it with `--output-dir`. Pass that full output explicitly to `compare_evaluators.py --candidate-results`; the recorded candidate commit must equal the current HEAD.
- `config_hash` always uses `utf8-normalized-lf-v1`; raw checkout bytes must never be hashed directly.
- Run `python -m pytest -q` before accepting an iteration. Reject any leakage, future-price access, negative cash, or duplicate capital allocation.
- Record every comparison in `experiments/iterations.csv`.

## Fixed OHLCV benchmark

- Generate only when intentionally refreshing the frozen input: `python scripts/generate_benchmark.py`.
- Normal benchmark code must use `FixedOHLCVLoader`; it never falls back to HTTP.
- Validate before use with `python scripts/validate_benchmark.py`. Do not hand-edit CSVs or `manifest.json`.

## Durable project memory

- `PROJECT_STATE.md` is the rolling current-stage external-memory source.
- `PROJECT_DECISION_LOG.md` is append-only for important durable decisions and exact-SHA review/stage transitions.
- Every important task must read `PROJECT_STATE.md` in addition to existing governance and task-specific documents.
- After any material methodology/design decision, design freeze, exact-SHA independent review, PASS/BLOCK that changes the next action, human-gate issuance or consumption, real execution, stage transition, or study termination, update project state in Git at the next authorized repo-writing task; do not rely on chat memory.
- Task-specific frozen design, evidence, and code remain authoritative over summary state if they conflict.
- Never place raw authorization, private paths, private ticker identities, sealed memberships, raw payloads, or other protected material in these public memory documents.
- Keep `PROJECT_STATE.md` compact; place detailed immutable history in task/study documents and `PROJECT_DECISION_LOG.md`.
- Record exact SHA/provenance whenever material.

If `PROJECT_STATE.md` declares an active branch-wide advisory review for the
current study, read that file after the normal governance and project-state
documents for important direction, methodology, profitability/expected-value,
process-efficiency, or next-action work. Treat it as evidence and critique,
not authority: it cannot by itself change frozen methodology, gates, provider
or data scope, evaluation criteria, execution permissions, or study disposition.
Current frozen and task-specific artifacts and exact READY Issue contracts
take precedence. Revalidate snapshot facts against current repository state
when the authoritative tree has materially diverged from the review's
`reviewed_head`. Recommendations, including portfolio breadth, universe size,
acceptance criteria, and gate cadence, remain proposals until separately
adopted through the required GPT, human, and freeze workflow. When a review
identifies process overhead, consider the shortest scientifically valid path
to the next informative measurement without weakening real, private, or
one-shot safety boundaries.
