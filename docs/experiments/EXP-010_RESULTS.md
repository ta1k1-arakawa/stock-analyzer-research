# EXP-010 RESULTS — earnings-momentum leg (np_forecast revision momentum)

- Run date: 2026-10-29
- Preregistration: `docs/experiments/EXP-010_PREREGISTRATION.md`
- Amendments: 1 (leg redefined to np_forecast revision momentum),
  2 (adapter for the raw J-Quants v2 record schema)

## Verdict

- **Variant A (persistent tilt on the 2-day rebalance): PROMISING** —
  all three preregistered criteria passed.
- **Variant B (monthly momentum sleeve): NOT PROMISING** —
  criteria 1 and 2 passed; criterion 3 failed narrowly
  (full-period stress ratio 0.347 vs S 0.361).

## Data note (read before comparing with EXP-009)

The original EXP-002 cache no longer existed locally, so it was rebuilt on
2026-10-29 with `experiments/exp002_fetch.py`. The rebuilt cache's
combined_sha256 (7ea4b40e…) differs from `EXP-002_DATA_MANIFEST.json`
(c965f578…) because J-Quants has slightly revised historical data since
2026-09-25 (bars +718 records, fins −40, topix −1). All comparisons below
are against S **recomputed on the same rebuilt cache in the same script**.

Baseline check: recomputed S second-half profit +2,634,920 vs EXP-009's
published +2,634,909 (annual/DD ratio 1.086 in both) — the engine and the
rebuilt cache reproduce EXP-009 closely. Full-period S differs modestly
(+6,157,708 recomputed vs +5,669,799 published) due to the data revisions.

Implementation fixes made before any valid A/B output existed (the first
two runs crashed; the third produced degenerate all-zero A/B output
because NaN first-disclosure diffs propagated through a cumulative sum):
Amendment 2 schema adapter; `simulate_monthly` return-slice fix
(937b1637); NaN revision-sign fix (274b1d77). No design, hypothesis, or
criterion was changed after seeing any result.

Momentum-leg diagnostics: non-NaN share 1.0, mean per-day cross-sectional
std of the ranked leg 0.233.

## Results (budget ¥2,000,000; base = 0.03% one-way + 3%/yr short carry;
stress = 0.10% + 5%/yr)

### First half 2017-01-04 – 2021-12-30

| variant | cost | profit (¥) | annual % | max DD % | annual/DD |
|---|---|---:|---:|---:|---:|
| S | base | 1,034,912 | 8.72 | −28.93 | 0.302 |
| A | base | 1,001,487 | 8.48 | −24.36 | 0.348 |
| B | base | 1,603,309 | 12.53 | −15.86 | 0.790 |
| S | stress | 568,667 | 5.15 | −35.33 | 0.146 |
| A | stress | 534,112 | 4.86 | −30.14 | 0.161 |
| B | stress | 1,255,698 | 10.27 | −18.09 | 0.567 |

### Second half 2022-01-04 – 2026-09-25

| variant | cost | profit (¥) | annual % | max DD % | annual/DD |
|---|---|---:|---:|---:|---:|
| S | base | 2,634,920 | 19.48 | −17.93 | 1.086 |
| A | base | 4,160,686 | 26.90 | −16.76 | 1.605 |
| B | base | 1,671,619 | 13.73 | −6.71 | 2.044 |
| S | stress | 2,033,009 | 16.01 | −19.86 | 0.806 |
| A | stress | 3,415,924 | 23.48 | −18.35 | 1.280 |
| B | stress | 1,340,498 | 11.47 | −7.97 | 1.439 |

### Full period 2017-01-04 – 2026-09-25

| variant | cost | profit (¥) | annual % | max DD % | annual/DD |
|---|---|---:|---:|---:|---:|
| S | base | 6,157,708 | 15.56 | −28.93 | 0.538 |
| A | base | 6,125,742 | 15.51 | −24.36 | 0.637 |
| B | base | 2,295,714 | 8.18 | −15.86 | 0.516 |
| S | stress | 4,423,939 | 12.75 | −35.33 | 0.361 |
| A | stress | 4,381,964 | 12.68 | −30.14 | 0.421 |
| B | stress | 1,614,743 | 6.28 | −18.09 | 0.347 |

## Criteria (same three as preregistered, vs recomputed S)

| criterion | A | B |
|---|---|---|
| 1. Profit > 0 in both halves (base) | PASS | PASS |
| 2. annual/DD > S in both halves (base) | PASS (0.348>0.302, 1.605>1.086) | PASS (0.790>0.302, 2.044>1.086) |
| 3. Full-period stress: profit > 0 and annual/DD > S | PASS (0.421>0.361) | FAIL (0.347<0.361) |

## Interpretation

Variant A's gain is risk-adjusted, exactly the profile the pre-analysis
predicted: full-period profit is essentially tied with S (−0.5%) while
max drawdown shrinks (−24.4% vs −28.9%), and in the second half profit is
+58% vs S with a slightly smaller drawdown. The revision-momentum leg
appears to add information beyond the forecast-ROE leg in recent years.

Variant B is a genuinely low-drawdown sleeve (max DD −6.7% in the second
half) but its absolute profit is far below S and it fails the full-period
stress ratio by 0.014. Per the preregistration it is not adopted; the
near-miss is recorded here, not promoted.

Caveats: backtest on revised data (see data note); short-selling costs
modelled as in EXP-009; no 100-share lot rounding (same convention as
EXP-009); past backtest performance does not guarantee future returns.

## Proposed next steps

1. Add variant A to forward paper validation alongside S, following the
   EXP-009 precedent (pending user approval; requires changes to
   `experiments/exp004_forward.py`).
2. Follow-up experiment: 100-share lot-rounding sensitivity for A, to
   check real-world tradability at the ¥2,000,000 budget.
