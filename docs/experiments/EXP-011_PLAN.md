# EXP-011 PLAN — replay verification of the forward implementation (A and S)

- Date: 2026-10-29
- Status: prepared, awaiting user approval to commit
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
  momentum 90d, forecast point-in-time) is far inside that window.
- Expected runtime: tens of minutes (per-day signal recomputation).

## How to run (local)

```
git pull
python experiments\exp004_forward.py update-data   # only if data/free/prices is missing/thin
python experiments\exp011_replay_forward.py
```

Paste back the final JSON. Delete `forward_replay/` to re-run; never
commit it.
