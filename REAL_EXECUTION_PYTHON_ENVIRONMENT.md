# Real-Execution Python Environment Contract

```text
document_type=REPOSITORY_REAL_EXECUTION_ENVIRONMENT_CONTRACT
status=ACTIVE
scope=REAL_NETWORK_PRIVATE_DATA_HUMAN_GATE_DURABLE_STATE_PYTHON_ENVIRONMENT
governs_task=REPRODUCIBLE_REAL_EXECUTION_ENVIRONMENT_AND_RUNBOOK_HARDENING
```

This document is the canonical, human-readable environment contract for any
real network, private-data, human-gated, or durable-machine-state Python
execution in this repository (`AI_REAL_EXECUTION_RUNBOOK.md`'s scope). It is
operational/governance hardening only. It does not reopen any study, does
not authorize any acquisition, and does not change research methodology.
`AI_REAL_EXECUTION_RUNBOOK.md` remains the authoritative operational-safety
document; this file explains the environment piece of that contract in one
place, and `scripts/check_real_execution_env.py` is the mechanical
enforcement of it.

## 0. Environment isolation (binding decision)

```text
finding_resolved = "REAL_EXECUTION_ENVIRONMENT_ISOLATION / CANONICAL_REAL_EXECUTION_ENVIRONMENT_NOT_ISOLATED"
existing_general_environment                    = ".venv"
canonical_protected_real_execution_environment  = ".venv-real-execution"
```

Windows-grounded inspection established that the repository-root `.venv`
is Python 3.12.10 and operationally passes the readiness checker, but
carries 46 packages including unrelated development/trading dependencies
(`yfinance`, `lightgbm`, `pytest`, `requests`, `curl_cffi`, `scikit-learn`,
and more) that have nothing to do with, and were never reviewed for,
protected real execution. By binding operational decision:

```text
.venv                 = GENERAL_PROJECT_ENVIRONMENT_NOT_AUTHORIZED_FOR_PROTECTED_EXECUTION
.venv-real-execution   = CANONICAL_PROTECTED_REAL_EXECUTION_ENVIRONMENT
```

`.venv` remains available, untouched, for ordinary project
development/trading workflows -- this contract does not delete, modify,
clean, or reinterpret it. Only `.venv-real-execution` may be accepted for
future protected real network execution, private/sealed access,
human-gated execution, or durable research-state execution. This
separation exists because:

- `.venv` is a general mixed project environment, not a reviewed
  real-execution environment;
- the protected environment should minimize dependency drift and attack
  surface -- every package inside it should be traceable to the real
  execution import closure (§4), not incidentally present because some
  unrelated bot feature needed it;
- unrelated bot/development dependency upgrades in `.venv` (a new
  `yfinance` release, a `lightgbm` bump, etc.) must never silently alter
  the frozen research execution environment.

This is operational/governance hardening only, not a research methodology
change.

## 1. Canonical environment directory

```text
canonical_environment_directory = ".venv-real-execution"   (repository root)
```

`.venv-real-execution` is never committed to Git. `.gitignore` ignores both
`.venv/` (the general environment) and `.venv-real-execution/` (the
canonical protected environment).

## 2. Canonical interpreter invocation

```text
canonical_windows_interpreter = ".venv-real-execution\Scripts\python.exe"   (exact, repo-root-relative)
```

All future Windows real/network/private/human-gated Python execution MUST
invoke this exact interpreter path explicitly. It MUST NOT rely on:

- `.venv\Scripts\python.exe` (the general, unauthorized project environment)
- `python`
- `python3`
- `py`
- PATH activation (`.venv-real-execution\Scripts\Activate.ps1`)
- whatever interpreter happens to be active in the current shell

Activation may be convenient for a human operator, but it is never the
security/provenance mechanism: an activated shell's `python` can silently
resolve to something other than `.venv-real-execution\Scripts\python.exe`
(a stale PATH entry, a WindowsApps alias, the general `.venv`, a
differently-versioned interpreter). Production code must instead verify
`sys.executable` itself resolves to the repository's exact
`.venv-real-execution\Scripts\python.exe` before any gate/network/private
boundary. This rejection is unconditional on interpreter *path* identity --
it applies even when the general `.venv` happens to be Python 3.12 with
pandas/xlrd installed and every other probe would otherwise pass. A
mismatch is `PRE_GATE_WRONG_PYTHON_ENVIRONMENT` (see
`AI_REAL_EXECUTION_RUNBOOK.md` §17), and
`scripts/check_real_execution_env.py` reports this exact failure class
(`INTERPRETER_FAILURE_CLASS`) together with `GENERAL_PROJECT_VENV_REJECTED`
when the rejected interpreter is specifically the general `.venv`.

## 3. Canonical Python version

```text
canonical_python_major_minor = "3.12"
canonical_python_version_source = ".github/workflows/daily_ai_trade.yml (python-version: '3.12')"
canonical_python_version_derivation = "MECHANICALLY_DERIVED_FROM_EXISTING_REPOSITORY_CI"
```

This repository already establishes Python 3.12 as its supported major/minor
version, in `.github/workflows/daily_ai_trade.yml`'s
`actions/setup-python@v4` step (`python-version: '3.12'`). Per the task's own
"Python version decision discipline," this existing repository evidence is
reused rather than a version being freshly invented because of whatever
Python happens to be installed on a given Windows machine (e.g. a
locally-installed 3.14.5 must not be silently adopted as canonical).

The exact resolved patch version (e.g. `3.12.x`) is whatever the real Windows
`py -3.12` launcher resolves to at bootstrap time. That exact patch version is
recorded, not fabricated, by `scripts/bootstrap_real_execution_env.ps1` and by
the future Windows-grounded environment lock (§7).

## 4. Direct real-execution dependencies

```text
direct_dependency_specification = "requirements-real-execution.txt"
```

Mechanically inspecting the complete import closure reachable from the real
V8-lineage source-snapshot execution path
(`src/v8i_source_snapshot.py` → `src/v8_partition.py`,
`src/v8c_git_provenance.py` → `src/v8b_git_provenance.py`,
`src/v8c_human_gate_consumption.py`; and the production parser reference
implementation, `scripts/build_v8_partition_manifest.py`'s
`default_parse_source_table`), the only non-stdlib direct dependencies are:

```text
pandas   (unpinned; see §7 -- no authoritative pandas version is
          established anywhere in this repository yet, and this task
          deliberately does not invent one)
xlrd==2.0.2   (pinned; reused verbatim from the repository's own existing
               requirement.txt -- not invented here)
```

Everything else reachable from that path is Python standard library only:
`hashlib`, `json`, `os`, `re`, `subprocess`, `datetime`, `pathlib`, `typing`,
`urllib.request`, `urllib.parse`, `urllib.error`, `ctypes`, `tempfile`,
`argparse`, `sys`.

This is deliberately narrower than the top-level `requirement.txt`, which
also serves the unrelated daily automated trading bot (`lightgbm`,
`scikit-learn`, `scipy`, `joblib`, `PyYAML`, `requests`, `python-dotenv`,
`pytest`, ...). None of those are imported anywhere on the real V8-lineage
source-snapshot path, and the task explicitly requires the real-execution
specification to reflect the real path, not merely what unit tests import.
Notably, `requests` is *not* on this path either: the real JPX fetch
reference implementation
(`scripts/build_v8_partition_manifest.py`'s `fetch_real_jpx_source`) uses
only `urllib.request` with a trusted-host redirect handler
(`TrustedJpxRedirectHandler`), not `requests`.

## 5. Required JPX Excel engine

```text
required_excel_engine = "xlrd"
required_excel_engine_version = "2.0.2"
required_excel_engine_derivation = "MECHANICALLY_DERIVED_FROM_EXISTING_REPOSITORY_EVIDENCE"
```

The official JPX listing is `data_j.xls` (see
`scripts/build_v8_partition_manifest.py`'s `DATA_LINK_PATTERN`,
`SYNTHETIC_SOURCE_URL`) -- the legacy OLE2/BIFF `.xls` binary format, not
`.xlsx`. `default_parse_source_table` calls
`pandas.read_excel(io.BytesIO(raw_bytes), dtype=str)` with no explicit
`engine=` argument; pandas selects the engine by sniffing the byte content
(OLE2 compound-file signature vs. `.xlsx`'s zip/OOXML signature), and reading
that OLE2/BIFF signature requires the `xlrd` package to be installed. Because
`xlrd >= 2.0` intentionally dropped `.xlsx` support and reads *only* the
legacy `.xls` format, `xlrd==2.0.2` -- already pinned in this repository's
own `requirement.txt` -- is exactly the correct, already-established engine
version for this real path. This task reuses that existing pin verbatim; it
does not invent a new one.

## 6. Bootstrap and readiness procedure

```text
bootstrap_script  = "scripts/bootstrap_real_execution_env.ps1"
readiness_checker = "scripts/check_real_execution_env.py"
```

`scripts/bootstrap_real_execution_env.ps1` is a fail-closed, environment-only
PowerShell script: it exclusively creates or verifies
`.venv-real-execution` (requiring exact Python `3.12.10`, not merely
`3.12`), runs the reviewed-lock preflight (§6a), installs the complete
reviewed lock via
`.venv-real-execution\Scripts\python.exe -m pip install --no-deps -r requirements-real-execution.lock.txt`,
and finally runs the readiness checker. It never consumes a human research
gate, never calls JPX/Yahoo, never accesses private/sealed data, never
executes any V8I/V8J real acquisition, and never reads, alters, uninstalls
from, or copies packages out of the separate general `.venv`.

### 6a. Reviewed lock is the installation/runtime package authority

```text
finding_resolved = "REAL_EXECUTION_ENVIRONMENT_LOCK_ENFORCEMENT"
protected_installation_authority = "requirements-real-execution.lock.txt"
requirements_real_execution_txt_role = "DIRECT_DEPENDENCY_SPECIFICATION_ONLY_NOT_INSTALL_AUTHORITY"
```

Once a reviewed environment lock exists
(`requirements-real-execution.lock.txt`, bound to
`REAL_EXECUTION_ENVIRONMENT_LOCK_CANDIDATE.json` -- see §7), it is the sole
protected installation and runtime package authority. Protected packages
are resolved and installed exclusively from that reviewed, exact-pinned
lock, with `--no-deps` so pip cannot silently add or resolve any package
outside the complete reviewed lock:

```powershell
.venv-real-execution\Scripts\python.exe -m pip install --no-deps -r requirements-real-execution.lock.txt
```

`requirements-real-execution.txt` (unpinned `pandas` + pinned
`xlrd==2.0.2`) remains the human-readable direct-dependency
*specification* -- it still documents and mechanically traces the real
import closure (§4) -- but it is **not** the protected installation
authority after a reviewed lock is captured. Its own executable dependency
semantics are unchanged (`pandas`, `xlrd==2.0.2`); only its instructional
comment was updated for accuracy.

Before any protected package installation, both the bootstrap script and
the readiness checker fail closed unless all of the following are exactly
the reviewed values -- hardcoded as constants in each, not merely trusted
from whatever the mutable candidate/lock files currently say on disk:

- the reviewed lock candidate manifest is structurally valid and its
  self-reported fields exactly match the reviewed binding (including
  `artifact_status == "CANDIDATE_NOT_FROZEN"`, `package_count == 15`);
- the reviewed lock's canonical Git blob
  (`5e9d15caa822bd39e751a49cd0758db6eaf04bdf`) is resolved locally with
  `git cat-file blob`, and those exact canonical bytes independently hash to
  the reviewed lock SHA-256
  (`ddd505cc01ac4a3a798cdf7ed9c35b3a9e56db569a421aef98c02d013dd286b7`);
  raw working-tree bytes are never lock provenance authority;
- the working-tree lock is independently parsed with line-ending-insensitive
  `splitlines()` semantics and its package map must exactly equal the
  reviewed canonical Git-blob package map, so equivalent LF/CRLF checkouts
  pass but missing, extra, or version-drifted packages fail;
- the source requirements file's independently recomputed **canonical Git
  object bytes** (`git cat-file blob <sha>:<path>`, captured via a raw
  byte stream, never a checked-out working-tree copy or PowerShell's
  text/console pipeline) hash to the reviewed source-requirements SHA-256
  -- this is the line-ending-independent provenance mechanism; a Windows
  CRLF checkout can never silently pass or fail it, per
  `REAL_EXECUTION_WINDOWS_LOCK_CANDIDATE_MEDIUM_1`;
- the canonical environment directory/interpreter identity matches
  `.venv-real-execution` / `.venv-real-execution\Scripts\python.exe`;
- the live platform is exactly CPython `3.12.10` / Windows / `AMD64` /
  `win-amd64` (not merely `3.12`).

The readiness checker additionally requires the live
`python -m pip freeze --all` package set to equal **exactly** the reviewed
seven entries -- no extra package, no missing package, no version drift --
before it can report `REAL_EXECUTION_ENVIRONMENT_READY=true`. See its
`check_environment_lock` function and module docstring for the exact
mechanics and safe result contract
(`ENVIRONMENT_LOCK_FINGERPRINT_STATUS`, `ENVIRONMENT_LOCK_PACKAGE_SET_MATCH`,
`ENVIRONMENT_LOCK_PACKAGE_COUNT`, `ENVIRONMENT_LOCK_SHA256_MATCH`,
`PYTHON_PATCH_MATCH`).

`scripts/check_real_execution_env.py` is a no-network, no-private-data
readiness checker. It verifies interpreter identity, dependency
presence/version, an *operational* parser probe (not merely `import
pandas`), TLS/stdlib initialization, trusted-host request-construction
initialization (reusing the real
`scripts/build_v8_partition_manifest.py` production code, not a
reimplementation), and durable-publication readiness by directly invoking
the real production exclusive/atomic publication primitive
(`src.v8i_source_snapshot._atomic_publish_once` -- staging write,
mandatory `os.fsync` of the file, atomic no-overwrite `os.link`, then a
best-effort directory fsync) on a disposable probe path that is
mechanically proven never to overlap real gate/receipt/evidence state. This
proves, not merely asserts, exclusive/no-overwrite creation, that a second
publication to the same destination correctly fails, durable byte
round-trip, and cleanup of the disposable probe artifact only -- an
ordinary write/read/unlink on an unrelated temp file would not exercise any
of that. See its module docstring for the exact safe result contract.

Precise durability semantics, stated exactly as the code behaves:

```text
file_fsync_mandatory_in_atomic_publish_once     = true
directory_fsync_attempted_best_effort           = true
directory_fsync_guaranteed_on_every_platform    = false
```

The file-level `os.fsync` is unconditional inside `_atomic_publish_once`.
The directory fsync goes through the production `_fsync_directory()`
helper, which returns silently when the platform cannot `os.open()` a
directory -- so a passing probe proves that code path executed, not that a
directory-entry fsync actually reached the disk on every OS. This document
does not claim otherwise.

### Operational JPX `.xls` parser probe -- RESOLVED

```text
former_open_item = "CHATGPT_DECISION_REQUIRED: REAL_EXECUTION_XLS_SYNTHETIC_FIXTURE_STRATEGY"
status           = RESOLVED_BY_BINDING_GPT_DECISION
resolution       = COMMITTED_SYNTHETIC_LEGACY_XLS_FIXTURE
```

The former open item is resolved by binding GPT methodology/operational
decision: this repository now commits an entirely synthetic, non-sensitive
legacy `.xls` fixture used solely for pre-gate environment readiness.

```text
fixture_path   = "tests/fixtures/synthetic_jpx_source_snapshot.xls"
fixture_sha256 = "ca47744896a286e1c56d4d0c09260775772c7df0c01b80d81b7e9a515e6d6aa7"
fixture_format = "legacy OLE2/BIFF .xls (verified D0CF11E0A1B11AE1 signature)"
```

```text
finding_resolved = "REAL_EXECUTION_XLS_FIXTURE_MEDIUM_1_REAL_TICKER_COLLISION"
```

An earlier revision of this fixture (SHA-256
`c51e3a766534820529a8946bec5c2093d7c90c593ccf0e99556b91d539cbd7cb`) used
plain `9001`-`9007`-style numeric placeholder codes, which collide with real
JPX security codes (`9001` and `9003` are real listed-instrument
identities) and therefore did not satisfy "no real ticker identities." That
SHA-256 is superseded and is **not** current canonical identity. Every code
is now drawn from an unmistakably artificial `ZZ`-prefixed namespace
(`ZZA1`, `ZZB2`, `ZZC3`, `ZZD4`, `ZZE5`, `ZZG6`, `ZZF7`, `ZZZZ8`) -- visibly
synthetic from the code value itself, not merely from the paired company
name -- and mechanically enforced: both the generator module (at import
time, via `_assert_synthetic_namespace`) and the readiness checker (before
parsing) fail if any fixture code does not start with the `ZZ` prefix, so a
later edit cannot silently reintroduce an ordinary numeric JPX-looking code.

**Completely synthetic and non-sensitive.** The fixture contains no real JPX
payload, no real or private ticker membership, no prices, and no outcomes.
Every row pairs a `ZZ`-namespace code with a `SYNTHETIC_*` name and
`SYNTHETIC_SECTOR_*` industry; none is asserted to be, or derived from, any
real listed instrument. Its columns are exactly the minimum the real parser
path needs -- `コード`, `銘柄名`, `市場・商品区分` (which satisfies the
production `_find_column(..., ("市場", "区分"))` detection), and
`33業種区分`.

It carries 8 synthetic rows: 5 that the production filter must accept
(`ZZA1`, `ZZB2`, `ZZC3`, `ZZD4`, `ZZE5`), plus one row per exclusion branch
-- non-prime/standard (`ZZG6`), non-domestic (`ZZF7`), and a
non-four-character code (`ZZZZ8`) -- so the probe exercises both the accept
and reject paths rather than merely proving that parsing returned
something.

**The checker mechanically verifies the fixture SHA-256 before parsing.**
`check_jpx_xls_parser_synthetic_probe` computes the committed fixture
bytes' SHA-256 and compares it against `EXPECTED_FIXTURE_SHA256` (recorded
in `scripts/generate_synthetic_jpx_xls_fixture.py`, the single source of
truth for the canonical identity) before calling any production parser
function. A mismatch -- tampered bytes, a stale recorded SHA after
regeneration, or any other divergence -- fails the probe immediately as
`FIXTURE_SHA256_MISMATCH`, rather than silently parsing whatever happens to
be on disk.

**Exact production functions exercised** by the readiness probe, in order,
with no reimplementation of `pandas.read_excel` in the checker:

1. read the committed synthetic `.xls` bytes;
2. `scripts.build_v8_partition_manifest.default_parse_source_table(raw_bytes)`;
3. `src.v8_partition.parse_eligible_universe(frame)`.

That mechanically proves the canonical `.venv-real-execution` Python works,
pandas imports, `xlrd` imports, pandas can actually parse legacy `.xls` bytes, the
production `default_parse_source_table` works, and the downstream JPX
column-detection / eligible-universe reconstruction initializes
successfully. The checker verifies only safe synthetic properties (a
DataFrame was returned, the expected synthetic row count, the expected
eligible reconstruction) and performs no network request, no private read,
and no gate consumption.

**Generator (dev tool only).**

```text
generator_script       = "scripts/generate_synthetic_jpx_xls_fixture.py"
generator_dependency   = "xlwt==1.3.0"
xlwt_is_production_dep = false
```

`xlwt==1.3.0` is a fixture-generation/dev dependency ONLY and is
deliberately **not** added to `requirements-real-execution.txt`: production
*reads* `.xls` (pandas + `xlrd`) and never writes it, so nothing on the
real execution path imports `xlwt`. The production direct-dependency set is
unchanged by this decision (`pandas`, `xlrd==2.0.2`).

**Byte determinism is not claimed.** Regenerating the workbook reproduced
identical bytes across repeated runs and across fresh interpreter processes
on the platform and library versions used to author it, but this repository
has not established that `xlwt`'s output is byte-stable across other
platforms or versions. Per the governing decision, the committed, reviewed
fixture bytes and the `fixture_sha256` recorded above are therefore the
canonical identity; the generator is explanatory/reconstruction tooling
only. `python3 scripts/generate_synthetic_jpx_xls_fixture.py --check`
reports whether a fresh rebuild happens to match the committed bytes
without asserting that it must.

**This resolves the parser probe only.** A genuine
`JPX_XLS_PARSER_SYNTHETIC_PROBE=PASS` does not by itself make the
environment ready: Windows-grounded execution inside the canonical
`.venv-real-execution` (§2-§3) is still required, and the environment lock
(§7) must exist, be verified, and eventually be promoted before
`REAL_EXECUTION_ENVIRONMENT_FROZEN` can ever become `true`.

## 7. Exact environment lock/fingerprint -- FROZEN

```text
finding_resolved                          = "REAL_EXECUTION_ENVIRONMENT_FREEZE_PROMOTION"
freeze_record                             = "REAL_EXECUTION_ENVIRONMENT_FREEZE_RECORD.json"
artifact_status                           = "REAL_EXECUTION_ENVIRONMENT_FROZEN"
lock_candidate_reviewed_git_sha           = "107430894723c2bdc2f8493cb12c467fccd8665e"
tested_implementation_git_sha             = "84d4512d800b18b858b6f129be9a4ba0ea73d4ca"
reviewed_windows_validation_evidence_git_sha = "f52f31ab6305e321cd9e8e9855d6efd83238f552"
```

A Windows-grounded package-resolution lock was captured and reviewed:
`REAL_EXECUTION_ENVIRONMENT_LOCK_CANDIDATE.json` (the manifest -- exact
CPython `3.12.10` / Windows / `AMD64` / `win-amd64`, the lock file's
SHA-256, the source-requirements canonical Git-bytes SHA-256, and the
fixture SHA-256) and `requirements-real-execution.lock.txt` (the exact
resolved seven-package set: `numpy`, `pandas`, `pip`,
`python-dateutil`, `six`, `tzdata`, `xlrd`), both generated on the real
target Windows machine via the canonical interpreter ONLY -- never the
general `.venv`:

```powershell
.venv-real-execution\Scripts\python.exe -m pip freeze --all
```

`REAL_EXECUTION_ENVIRONMENT_LOCK_ENFORCEMENT` made that reviewed candidate
the actual protected installation/runtime authority (§6a) and added a
mechanical lock check (`scripts/check_real_execution_env.py`'s
`check_environment_lock`) that `REAL_EXECUTION_ENVIRONMENT_READY` requires
to `PASS`. That lock-enforcement implementation was then independently
GPT exact-SHA reviewed and Windows-grounded execution tested (proving the
bootstrap script and checker actually behave as designed against the real
`.venv-real-execution`), and that Windows validation was itself recorded as
a reviewed candidate evidence artifact,
`REAL_EXECUTION_ENVIRONMENT_WINDOWS_VALIDATION_EVIDENCE.json`.

**Explicit environment freeze/promotion completed.**
`REAL_EXECUTION_ENVIRONMENT_FREEZE_PROMOTION` adds
`REAL_EXECUTION_ENVIRONMENT_FREEZE_RECORD.json` and a mechanical freeze
check (`check_freeze_record`) that mechanically binds the freeze together:
it requires the live environment-lock check to itself currently `PASS`,
requires the freeze record to structurally and semantically match the
hardcoded reviewed binding (any mutated SHA, package, platform value,
`frozen`/`authorized` flag, or missing/extra field fails it), cross-checks
every identity against the SAME reviewed constants
`check_environment_lock` itself uses, and independently re-derives the
canonical Git blob SHA-256 of the reviewed Windows validation evidence
artifact (`git cat-file blob <sha>:<path>`, never the working-tree copy)
rather than trusting any self-reported hash. Only when all of that PASSes
-- together with every existing readiness/lock/probe check -- does
`scripts/check_real_execution_env.py` report:

```text
REAL_EXECUTION_ENVIRONMENT_FROZEN = true
```

Freezing is mechanically bound to the reviewed lock candidate and the
reviewed Windows validation evidence; it is never a hardcoded or
self-declared value, and it can only ever become `true` on a live run
inside the exact canonical `.venv-real-execution` on the exact reviewed
Windows/AMD64/win-amd64 platform with the exact reviewed package set --
never from Claude Code Cloud or any other non-Windows run, and never when
any existing readiness/lock/probe check is failing.

**Environment freeze is NOT acquisition authorization.** This freeze
governs the *Python environment* only -- interpreter identity, package
set, platform binding. `future_protected_execution_authorized` remains
`false` in both the lock candidate and the freeze record, and freezing the
environment does not itself authorize JPX/Yahoo/private/sealed access or
consume any research gate. Future protected execution still requires all
study-specific human gates, exactly as before: a frozen environment is a
necessary precondition for a future gated attempt, never a substitute for
its own separate, study-specific human authorization.

## 7a. V9_014 PDF successor generic-authority promotion (E12/E13) -- FROZEN, migration-in-progress

```text
finding_resolved                 = "V9_014_PDF_ENV_SUCCESSOR_E12_E13_GENERIC_AUTHORITY_FINALIZATION"
canonical_environment_state      = "SUCCESSOR_MIGRATION_IN_PROGRESS_NOT_AUTHORIZED"
v9_014_pdf_environment_successor_promoted = false
package_count                    = 15
lock_sha256                      = "ddd505cc01ac4a3a798cdf7ed9c35b3a9e56db569a421aef98c02d013dd286b7"
e7_reviewed_git_sha              = "0c09e504d23f5e74f4c9a689fe1639d56219bc86"
e8_reviewed_git_sha              = "50e8e3d42137adf0d90342080b98b55e719f5f39"
e9_mutation_git_sha              = "50e8e3d42137adf0d90342080b98b55e719f5f39"
e10_validation_git_sha           = "50e8e3d42137adf0d90342080b98b55e719f5f39"
e11_reviewed_git_sha             = "7bc1ac6a792779eed62c90d8f659b010dc525648"
```

Stages E9 (canonical `.venv-real-execution` mutation) and E10 (post-mutation
live validation) were executed and their evidence (`V9_014_PDF_REAL_
EXECUTION_ENVIRONMENT_SUCCESSOR_LIVE_CANONICAL_VALIDATION_EVIDENCE.json`,
blob `81b046a3203b2f04aa512c3eb6f9939fd89bfec2`, SHA-256
`6986bf4f00bee4766fb2f47e9fa5e9326d0ad524a9877873c58b81112955009d`) was
committed and independently GPT exact-SHA reviewed at Stage E11
(`7bc1ac6a792779eed62c90d8f659b010dc525648`, `CRITICAL=0 HIGH=0 MEDIUM=0
RESULT=PASS`). This Stage E12/E13 finalization updates the generic
canonical-authority artifacts to reflect that reviewed live state:

- `requirements-real-execution.txt` now specifies `pandas`, `xlrd==2.0.2`,
  and `pdfplumber==0.11.10`;
- `requirements-real-execution.lock.txt` now pins exactly 15 packages
  (PEP 503-normalized-name sorted): `cffi`, `charset-normalizer`,
  `cryptography`, `numpy`, `pandas`, `pdfminer-six`, `pdfplumber`, `pillow`,
  `pip`, `pycparser`, `pypdfium2`, `python-dateutil`, `six`, `tzdata`,
  `xlrd`;
- `REAL_EXECUTION_ENVIRONMENT_LOCK_CANDIDATE.json`,
  `REAL_EXECUTION_ENVIRONMENT_WINDOWS_VALIDATION_EVIDENCE.json`, and
  `REAL_EXECUTION_ENVIRONMENT_FREEZE_RECORD.json` were updated (schema
  evolved minimally: `schema_version` 1 -> 2, plus a new
  `synthetic_pdf_fixture` block and a new `v9_014_successor_provenance`
  block binding the E7/E8/E9/E10/E11 chain above) to bind this exact
  15-package closure, never a fabricated future commit SHA;
- `scripts/check_real_execution_env.py`'s hardcoded `REVIEWED_*` constants
  were promoted in lockstep to this same 15-package closure, and now also
  require an operational `pdfplumber==0.11.10` probe (`check_pdf_parser_
  synthetic_probe`, reusing `scripts.v9_014_pdf_env_successor.run_
  synthetic_pdf_operational_probe` against the committed synthetic PDF
  fixture, `tests/fixtures/v9_014_synthetic_pdf_env_probe.pdf`, SHA-256
  `5eecb758a50e829af16bd42833f89a8329bfaaaa561aee209fbd2249b507b413`) to
  PASS before `REAL_EXECUTION_ENVIRONMENT_READY` can be `true`.

Because the source-requirements file and all three generic JSON artifacts
were rewritten in this same finalization commit, their Git provenance is
bound by exact content-addressed blob SHA-1 (`git cat-file blob
<blob-sha>`) rather than a historical `<commit>:<path>` pair -- this needs
no prior distinct "reviewed at commit X" identity for bytes that did not
exist before this commit, and never fabricates a future commit SHA to
satisfy the binding.

**`REAL_EXECUTION_ENVIRONMENT_READY=true` / `REAL_EXECUTION_ENVIRONMENT_
FROZEN=true` under this binding are mechanical-freeze-readiness signals
only** -- proof that a genuinely Windows-grounded run inside the exact
canonical `.venv-real-execution` matches this exact reviewed 15-package
closure. They do **not** by themselves imply `V9_014_PDF_ENVIRONMENT_
SUCCESSOR_PROMOTED=true`. Per `V9_014_PDF_REAL_EXECUTION_ENVIRONMENT_
SUCCESSOR_DESIGN.md` §2a, `CANONICAL_ENVIRONMENT_STATE` remains
`SUCCESSOR_MIGRATION_IN_PROGRESS_NOT_AUTHORIZED` throughout E9-E14; only
Stage E15's own exact-SHA review of Stage E14's final no-network live
reverification may transition it to `SUCCESSOR_CANONICAL_FROZEN` and set
`V9_014_PDF_ENVIRONMENT_SUCCESSOR_PROMOTED=true`. No protected/private/
research execution is authorized under either environment's authority
while this state holds. `future_protected_execution_authorized` remains
`false` in every one of these artifacts.

### 7b. Current authority versus preserved historical authority

The V9_014 15-package generic checker and its lock remain preserved historical
evidence and regression tooling. They are not the current authority for a
future protected PRE_GATE. After Issue #111 receives its own GPT exact-SHA
PASS, the V13 XLSX successor is the current protected-environment authority
with exactly 29 packages. Its final promotion binds the #110-reviewed
active-mutation safe result, the exact final lock, and the human approval.
The F9-reviewed V10C 27-package chain remains historical predecessor
provenance, including its earlier 20-package predecessor. Resolve this
distinction mechanically with
`scripts/check_current_protected_environment.py` before naming a checker in
a protected task. If the repository later records a different reviewed
current chain, this checker must fail closed until a separately reviewed
implementation binds that transition; do not repoint the historical checker
silently. Current-authority resolution is only one readiness component: it
does not replace operation-specific reachable-dependency probes. The V12
selector-compatible profile requires the reviewed synthetic `pdfplumber`
operational probe to PASS. The current V13 profile additionally requires the
synthetic production XLSX route and exact `openpyxl==3.1.5` and
`et-xmlfile==2.0.0` identities before `CURRENT_ENVIRONMENT_READY` can be
true; future protected tasks must bind the probes applicable to their own
post-gate execution path. The current checker performs package, PDF, and XLSX
observation inside an exact-canonical-interpreter isolated child using `-I`,
`-B`, controlled no-user-site/no-bytecode environment variables, no ambient
`PYTHONPATH`, and explicit repository-file loading; parent validation fails
closed on child launch, schema, identity, package, or probe failure.

`V9_014_PDF_REAL_EXECUTION_ENVIRONMENT_SUCCESSOR_FREEZE_RECORD.json`
(Stage E12, this same commit) is the distinct V9_014-specific successor
freeze/promotion record (design §4, artifact 5): it binds the E7/E8/E9/E10/
E11 chain, the frozen V9_014 design provenance
(`efee3d0efca368645c00aeed63cb8e0637cd3672`), and the Stage E10 observed
package-set/platform identity, and is itself reviewed for artifact/tooling
correctness only at Stage E13 -- never promotion, which remains Stage E15's
sole authority.

## 8. Authorization ordering

No real human authorization may be requested or accepted before environment
readiness `PASS`. The full required ordering is frozen in
`AI_REAL_EXECUTION_RUNBOOK.md` §16.

## 9. V8I permanence (prospective only)

This environment contract is prospective infrastructure only. It does not:

- reopen V8I;
- authorize a V8I retry or a second JPX request;
- reset, delete, or reuse the V8I `HUMAN_V8I_SOURCE_SNAPSHOT_ACQUISITION_GATE`
  receipt;
- reuse the V8I human authorization;
- reconstruct or preserve the lost V8I raw bytes; or
- change V8I's `BLOCK_CLOSED` disposition.

V8I remains permanently `BLOCK_CLOSED`, exactly as recorded in
`V8I_SOURCE_SNAPSHOT_TERMINAL_ADJUDICATION.json` and
`V8I_SOURCE_SNAPSHOT_EXECUTION_INCIDENTS.md`. Any future V8-lineage
source-snapshot attempt (e.g. under a successor study such as V8J) is a
fresh, independent study identity with its own fresh gate, receipt key, and
authorization grammar; this contract merely ensures that a future attempt
cannot again discover a missing software dependency only after its own gate
is consumed.
