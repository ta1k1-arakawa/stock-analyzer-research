# EXP-011 RESULTS — replay verification of the forward implementation (A and S)

- Date: 2026-10-29
- Plan: `docs/experiments/EXP-011_PLAN.md` (incl. Amendment 1)
- Script: `experiments/exp011_replay_forward.py`
- **Verdict: BOTH pre-defined checks PASS — the forward implementation
  of A is verified.**

## Results (re-run after Amendment 1, 2022-01-04 – 2026-09-25, ¥400,000)

| Portfolio | Profit (¥) | Annual % | Max DD % | Annual/DD |
|---|---:|---:|---:|---:|
| R | +625,605 | 21.99 | −24.40 | 0.901 |
| W | +626,231 | 22.01 | −24.36 | 0.904 |
| V | +584,163 | 20.94 | −23.86 | 0.877 |
| S | +503,311 | 18.77 | −18.48 | 1.015 |
| **A** | **+925,812** | **28.79** | **−18.39** | **1.565** |

Checks (defined in the plan before any run):

1. **Engine sanity — PASS.** Replay S is profitable (+¥503,311) and its
   annual/DD is 1.015 ≥ 0.5.
2. **A implementation — PASS.** Replay A's annual/DD (1.565) exceeds
   replay S's (1.015), and A's profit is positive (+¥925,812).

The ratios also agree qualitatively with the EXP-010 backtest's second
half (A 1.605 vs S 1.086), which is what this implementation check was
designed to confirm. This is not a new profitability test and not a
guarantee of future returns; the profitability evidence remains
EXP-009/EXP-010.

## Run history

**Run 1 (user's PC, 2026-10-29)** produced R +¥1,061,899 (1.145),
W +¥1,013,383 (1.161), V +¥841,670 (1.101), S +¥1,081,117 (1.463),
A +¥887,349 (1.174): check 1 passed, check 2 nominally failed — but the
run was **invalid from 2023-07-19 onward** because the harness's
rolling 560-day panel slice corrupted `due_tranches`' day count
(Amendment 1 in the plan). Its post-2023-07 numbers are not the
strategy's and are superseded by the re-run.

**Run 2 (re-run, 2026-10-29)** was executed by Muse on its own VM
after the user asked Muse to run everything itself:

- Code at commit 9e75f96e (with the Amendment 1 harness fix), fetched
  via the GitHub API; `forward/fundamentals.csv` taken from the repo
  (14,429 rows, disc_date 2016-09-27 – 2026-09-25, 306 codes).
- Prices downloaded fresh from Yahoo via `free_data.update_prices`
  (306 codes + 1306 TOPIX proxy; 61 codes needed one automatic retry
  after Yahoo rate limiting, final set complete).
- Environment matched to the user's PC: pandas 3.1.0 / numpy 2.5.4.
- Daily values over the segment where run 1 was still valid match
  run 1 exactly (spot-checked, e.g. 2022-02-09: R 394,559 /
  S 411,823 / A 411,724 in both runs).

## Rotation health (run 2)

Verified from the replay log: 1,156 trading days; after the initial
all-tranches day, `tranches_due` strictly alternates between an empty
day and a single tranche, and the 577 single-tranche dues follow the
exact 0→9 cycle (offset by the initial day) with no repeats, no stuck
tranche, and no gaps — including the 2023-07-19 onward segment that
degraded in run 1.

## Next steps

- A is verified for live forward paper tracking (it auto-initializes
  on the next live `step`; note the live `step` also needs lightgbm
  installed for portfolio M's scoring).
- Follow-up the user asked for: automate the daily forward routine so
  it no longer needs manual runs.
