# EXP-011 PLAN — replay verification of the forward implementation (A and S)

- Date: 2026-10-29
- Status: pushed (commit 215f4b15); first run completed 2026-10-29;
  Amendment 1 (harness fix) applied before the re-run — see below
- Script: `experiments/exp011_replay_forward.py`

## Purpose

EXP-010 judged variant A PROMISING in the J-Quants-cache backtest, and A
has been added to the EXP-004 forward paper comparison. Before relying
on months of live paper trading (and before automating the daily
routine), verify that the **forward implementation** of A — free-data
panels, ¥400,000 forward budget, tranche engine — reproduces the
backtest's qualitative result. This is an implementation/regression
check, **not** a new profitability test; the profitability evidence
remains EXP-009/EXP-010.

## Method

- Run the actual `exp004_forward.step_day` engine day by day over
  **2022-01-04 – 2026-09-25** (EXP-010's second half), in a scratch
  directory `forward_replay/`; the live `forward/` state is never read
  for writing and never modified.
- Campaign semantics mirror a forward campaign starting 2022-01-04:
  first orders are decided on the last trading day of 2021 and executed
  at the 2022-01-04 open (`F4.START` patched; `next_trading_day` taken
  from the price-data calendar because `tse_holidays.txt` only covers
  the live campaign's year).
- Portfolios: R, W, V, S, A. Excluded: M (frozen LightGBM model; a
  2022-2026 replay would be in-sample for it, and its scorer is stubbed
  in the harness) and L (trap scores are point-in-time artefacts;
  replaying them would leak today's knowledge into past decisions).
- Stats use EXP-009's annualisation with the ¥400,000 forward budget.
  Backtest profits were at ¥2,000,000, so compare **ratios**
  (annual/DD) and signs, not absolute yen.

## Checks (defined before running)

1. **Engine sanity:** replay S is profitable (profit > 0) and its
   annual/DD is at least 0.5 (backtest: 1.086; free-data vs J-Quants
   differences are tolerated, a collapse is not).
2. **A implementation:** replay A's annual/DD exceeds replay S's, and
   replay A's profit > 0 (backtest second half: A 1.605 vs S 1.086).

If both checks pass, the forward implementation of A is verified and
live paper tracking (and later, automation of the daily routine) can
proceed. If a check fails, investigate the implementation/data gap
before starting A live; do not tune the strategy to the replay.

## Caveats

- Free data (Yahoo split-adjusted prices, TDnet XBRL fundamentals)
  differs in details from the J-Quants cache; exact agreement with the
  backtest is neither expected nor required.
- fundamentals.csv is point-in-time by disclosure date, but rows added
  later (corrections) can carry old disclosure dates — a small
  look-ahead of the same class as the rebuilt-cache revision note in
  EXP-010_RESULTS.md.
- Panels are sliced to a rolling ~560-day warmup per step for speed;
  every lookback the replayed portfolios use (liquidity 20d, vol 60d,
  momentum 90d, forecast point-in-time) is far inside that window. The
  one consumer that needed an absolute position — `due_tranches` —
  is patched to the full calendar (Amendment 1).
- Expected runtime: tens of minutes (per-day signal recomputation).

## How to run (local)

```
git pull
python experiments\exp004_forward.py update-data   # only if data/free/prices is missing/thin
python experiments\exp011_replay_forward.py
```

Paste back the final JSON. Delete `forward_replay/` to re-run; never
commit it.

## Amendment 1 (2026-10-29) — harness due-date fix, before re-run

First run (2022-01-04 – 2026-09-25, ¥400,000): R +¥1,061,899 (1.145),
W +¥1,013,383 (1.161), V +¥841,670 (1.101), S +¥1,081,117 (annual
31.84%, max DD −21.77%, ratio 1.463), A +¥887,349 (27.99%, −23.84%,
1.174). Check 1 passed clearly. Check 2 nominally failed (A 1.174 <
S 1.463) — **but the run is invalid from 2023-07-19 onward** and the
A-vs-S judgement is suspended until the re-run:

- The pasted daily log shows `tranches_due` degrading from 2023-07-19:
  the same tranche due for weeks at a time, long all-empty stretches —
  not the intended every-2-days rotation.
- Cause: `exp004_forward.due_tranches` counts trading days since START
  *within the panel it is handed*. The harness hands a rolling 560-day
  slice, so once the slice start passed START (START + 560d ≈
  2023-07-18) the count froze at the ~constant number of trading days
  inside the trailing window. The live `step` hands the full history,
  so live forward is unaffected; only the replay harness was wrong.
- Fix (harness only; live engine and strategy untouched): the harness
  now replaces `due_tranches` with a count on the full price calendar,
  which is identical to the stock function on a full-history panel.
- The two checks above are unchanged. Do not tune the strategy to the
  first run's numbers.
