# EXP-010 Amendment 2 — adapter fix for the raw J-Quants v2 record schema

- Date: 2026-10-29
- Status: made after the first local run failed with `KeyError: 'disc_date'`
  BEFORE any backtest results were produced or seen. No EXP-010 results
  exist at the time of this amendment.

## What was wrong

`_as_records()` in `experiments/exp010_earnings_momentum.py` assumed the
normalized free-data schema (`code` / `disc_date` / `np_forecast`, as in
`experiments/free_data.py` FUND_FIELDS). In fact `E3.load()` returns the
cache's RAW J-Quants v2 records as a dict of code -> list of records, with
fields `DiscDate` / `DiscTime` / `DocType` / `CurPerType` / `FNP` / `NxFNp`.

## The fix (implementation only)

- `_as_records()` now maps the raw fields: disclosure date = `DiscDate`,
  ordering by (`DiscDate`, `DiscTime`), code from the dict key.
- The forecast value follows EXP-003's own selection rule verbatim:
  `NxFNp` when `CurPerType == "FY"` and the document is a financial
  statement, `FNP` otherwise. The momentum leg therefore diffs exactly the
  forecast series EXP-003's composite score uses.

## What does NOT change

Hypothesis, leg definition (net sign of np_forecast revisions over the
trailing 90 days), variants A and B, the three judging criteria, periods,
universe, budget, and costs are all unchanged from the preregistration and
Amendment 1.

## Context: cache rebuild

The original EXP-002 cache no longer existed on the local machine, so it
was rebuilt on 2026-10-29 with `experiments/exp002_fetch.py` (613 requests,
306 codes, no missing codes). The rebuilt cache's `combined_sha256`
(7ea4b40e…) differs from `docs/experiments/EXP-002_DATA_MANIFEST.json`
(c965f578…): J-Quants has slightly revised historical data since the
original 2026-09-25 fetch (bars +718 records, fins −40, topix −1).
EXP-010 recomputes the S baseline on the same rebuilt cache inside the
script, so the A/B-vs-S comparison is unaffected; absolute figures may
differ slightly from EXP-009's published values and must be read with this
note attached.
