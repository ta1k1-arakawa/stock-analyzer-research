# V13 successor: provider-invalid OHLC ordering as missing observations

```text
status=DRAFT_AWAITING_GPT_EXACT_SHA_REVIEW
frozen=false
current_v13_terminal_class=DATA_QUALITY_STOP
current_v13_continuation_authorized=false
successor_real_execution_authorized=false
future_profitability_established=false
```

This is a proposed successor-study ingestion policy. It is not a retroactive
amendment to the stopped current V13 execution. Issue #125's terminal
adjudication records 33 complete Yahoo raw locks, 32 derived price states, no
pending state, one previously authorized omission in the derived prefix, and
two distinct invalid observations in the unmatched complete raw. One is a
qualifying CLOSE>HIGH row that would make run-level omission #2 against the
current frozen maximum of one. The other is a LOW>CLOSE row outside the
current Issue #121 exception. Either condition prevents current V13
continuation. This is `DATA_QUALITY_STOP`, not a strategy or profitability
failure; future profitability is unestablished.

## 1. Successor boundary

The proposal changes only how otherwise valid provider numeric OHLC ordering
failures are represented at the successor ingestion boundary. Preserve the
current frozen provider and endpoints, date window, calendar, selected-500
universe identity and selection method, exclusion provenance, operation
identity, and content-locked raw bytes. A later separately reviewed and frozen
decision is required to change any of those. Do not apply this proposal to
the current V13 public-data-lock operation or treat this draft as permission
to resume it.

## 2. Content-lock authority

Every existing complete Yahoo and JPX raw lock remains authoritative and
immutable. Never refetch, replace, delete, mutate, clamp, repair, or
substitute a complete locked payload merely to obtain PASS. A later
authorized successor resume must reuse every complete existing raw lock and
acquire only genuinely missing payloads from the frozen public source scope,
after separate real-execution authorization. This design itself authorizes
no network request or durable-state write.

## 3. Ordering-invalid observation policy

Only after the existing structural, schema, symbol, date, length,
duplicate-session, and numeric type, finite, and nonnegative checks pass,
and after requiring strictly positive OHLC, classify an observation as
`PROVIDER_INVALID_OHLC_ORDERING` when either predicate holds:

```text
high < max(open, close, low)
low > min(open, close)
```

Treat the entire classified observation as missing for downstream price-state
construction. Count one omitted observation per row, including a row that
violates both predicates. Do not repair or clamp individual OHLC values. Do
not impute, forward-fill, backward-fill, interpolate, synthesize, or
substitute adjusted close. Retain the complete locked raw unchanged.

## 4. Other invalidity remains fail-closed

Null or non-numeric values, nonfinite values, negative values, nonpositive
OHLC, chart/schema/symbol mismatch, length mismatch, out-of-window
timestamps, duplicate sessions, malformed or invalid split events, and every
other invalidity outside the exact ordering predicates remain fail-closed.
The policy does not catch arbitrary parser errors as missing observations.
An ordering predicate cannot mask an earlier failure.

## 5. No post-hoc ingestion count cap

The successor policy removes the current instance-specific run-level maximum
of one ordering-invalid omission. It establishes no replacement threshold
chosen from the observed 33-raw failure prefix. Already-frozen downstream
missing-observation and eligibility requirements determine whether usable
coverage is sufficient. In particular, current `stage_a_from_raw()` requires
a valid signal observation and at least 253 valid historical observations;
omissions reduce usable coverage and fail or skip naturally under that
existing rule. Any absent required downstream signal, target, entry, or exit
observation retains its existing fail-closed or skip semantics. No missing
row is filled, and no downstream requirement is weakened.

## 6. Parser and API boundary

The shared/offline parser remains strict by default. Generalized
ordering-invalid-as-missing behavior requires an explicit successor-production
opt-in at the production entrypoint. Do not relax a generic or global OHLC
validator. Current V13's Issue #121 exact exception and one-omission cap
remain historical current-V13 contract facts, not a successor implementation
shortcut.

## 7. Privacy-safe evidence

Future implementation must expose only aggregate counters and hashes in
public evidence. At minimum record: total unique ordering-invalid
observations omitted; number of payloads containing at least one omission;
HIGH-order predicate row count; LOW-order predicate row count; and rows
satisfying both predicates, including zero if none. Predicate counts may
overlap, while the unique omission total counts each row once. Public
evidence must contain no ticker, date, price, path, or raw-payload identity.

## 8. Deterministic reuse of derived state

Future successor execution must deterministically recompute the price state
from each content-locked raw using the reviewed successor parser. Bind every
existing derived price state by no-overwrite/equality comparison to that
output. Reuse byte- or semantic-equivalent derived states without deleting or
rewriting them merely to obtain PASS. Any mismatch is a STOP for adjudication,
never authority to overwrite. Only missing derived state may be constructed
under a separately reviewed implementation and authorized execution.

## 9. Authority sequence

The required order is: DRAFT design commit; GPT exact-SHA independent review;
explicit human design-freeze approval; separate implementation Issue; GPT
exact-SHA implementation review; and separately adjudicated human
Direct-Windows same-root resume. Issue #126 grants none of those later
authorities. Parser implementation, public-data-lock rerun, private read,
model fit, backtest, A-Q execution, and trading remain unauthorized here.
