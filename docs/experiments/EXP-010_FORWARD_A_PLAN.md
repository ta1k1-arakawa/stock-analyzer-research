# EXP-010 — adding variant A to EXP-004 forward paper validation (plan)

- Date: 2026-10-29
- Status: prepared, awaiting user approval to commit
- Background: EXP-010 variant A was judged PROMISING
  (`docs/experiments/EXP-010_RESULTS.md`). Following the EXP-009 precedent
  (S was added to forward after PROMISING), A joins the EXP-004 forward
  comparison as a paper portfolio.

## Design (identical mechanics to S, different ranking)

- A uses the existing tranche engine unchanged: 10 tranches × 2 names,
  2-day stagger, 20-trading-day hold, equal weights, budget ¥400,000
  (the EXP-004 forward convention for every portfolio, including S;
  the ¥2,000,000 figure was the backtest convention only).
- Longs: top of A's ranking. Shorts: bottom of **A's own** ranking,
  notional 50% of equity (SHORT_FRAC), 3%/yr carry — same as S.
- A's ranking is the backtest's variant-A score, computed with the very
  same code (`exp010_earnings_momentum.revision_momentum_scores`,
  imported — not reimplemented):
  score = (composite percentile rank + revision-momentum percentile
  rank) / 2, over the names eligible for the composite score that day.
- State: auto-initialized in `load_state()` exactly like S in EXP-009 —
  tranches + shorts + realized, first pending copied from R. The next
  `step` run after this change is committed starts A automatically.
- Real money is unaffected: `REAL` stays "V"; Slack notification logic
  is untouched.

## Code changes (experiments/exp004_forward.py, 6 small hunks)

1. Import `exp010_earnings_momentum as E10`.
2. `PORTFOLIOS` gains `"A"`.
3. `load_state()`: auto-init block for A (mirrors S).
4. `step_day()`: compute `rank["A"]` from today's composite + momentum.
5. Short-order pool uses each portfolio's own ranking
   (`rank[name]` instead of hardcoded `rank["R"]`; for S this is
   behavior-identical because `rank["S"] is rank["R"]`).
6. Order-sheet title for A.

## Pre-flight check (run once before the first stepped day)

The momentum leg needs revision history in `forward/fundamentals.csv`.
The file is believed to be seeded from the J-Quants cache (~14k rows),
but verify:

```
python -c "import pandas as pd; d = pd.read_csv('forward/fundamentals.csv', dtype=str); print(d.disc_date.min(), len(d))"
```

Expected: earliest disc_date around 2017 and ~14,000+ rows. If coverage
only starts in 2026-09, do NOT start A yet — the leg would run on a
truncated 90-day window; seed the history from the rebuilt cache first
(separate task).

## Rollout / verification

1. Commit this change together with this plan.
2. Run the usual daily sequence (update-data → score → step → notify).
3. Verify: `forward/state.json` has an "A" key, `forward/ledger.csv`
   gains daily A rows, and the order sheet shows the A section.
4. Rollback if needed: revert the commit and delete the "A" key from
   `forward/state.json`; other portfolios are untouched either way.
