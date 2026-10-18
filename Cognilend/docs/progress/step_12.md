# Step 12: Stress twin (advisory)

Date: 2026-10-15.

Precondition: Steps 0–11 are complete and green (314/314 tests). The two KPI failures, accuracy and DI, are documented, open decisions rather than defects.

## What was built

- **`config/stress_twin.yaml`** holds every parameter and is labelled *illustrative, to be calibrated*:
  - simulation: seed 42, 1,000 paths, 12 months
  - shocks: income drop 20–50% for 1–3 months; an expense spike of 1–2× essentials in one month; a payment delay of 5–15 days; and all three combined
  - bands (on the combined scenario): below 10% shortfall probability is Resilient; 10–30% is Vulnerable, with alternative terms shown; 30% or more, or insufficient data, suggests review
  - the resilience weights and the alternative terms
- **`stress_twin/simulator.py`**:
  - `StressInputs` takes income mean and CV, income credit day, essential expenses, existing EMIs, either the proposed EMI directly or amount / rate / tenure, the EMI due day, and liquid savings.
  - Each month the simulation checks the balance on the EMI due date and at month end. Income only counts on the due date if it arrived by then.
  - Metric functions, each pure and unit-tested:

    | Function | What it computes |
    |---|---|
    | `min_cash_balance` | per path, the lowest balance at any check |
    | `shortfall_probability` | share of paths whose balance ever goes below zero |
    | `max_shortfall` | the largest deficit across paths |
    | `months_in_deficit` | months ending with a negative balance |
    | `recovery_time` | months from the first deficit back to a non-negative balance; capped at the end of the horizon if it never recovers |
    | `stressed_foir` | EMIs divided by the lowest monthly income on the path |
    | `buffer_coverage` | savings divided by (essentials + EMIs) |
    | `resilience_score` | 0–100: 0.5·(1 − shortfall probability) + 0.25·min(buffer / 6 months, 1) + 0.25·(1 − FOIR) |
    | `band` | the band for a shortfall probability |

  - `simulate()` returns per-scenario results plus the headline band and resilience score. `alternatives()` re-runs the combined scenario for a 20% smaller loan, a tenure 24 months longer, and the EMI due date moved to income day + 5.
- **UI:** `app/pages/6_Stress_Twin.py` is a separate advisory page that says it never changes the decision and that all thresholds are illustrative. `pipeline.py` does not import the twin, and a test checks this.

## Commands

```
python -m pytest tests/test_stress_twin.py     -> 24 passed in 4.02s
```

## Example (UI defaults: income ₹80k, CV 0.15, essentials ₹35k, EMIs ₹5k + ₹15L over 60 months at 10.5%, savings ₹60k)

- **Total EMI:** ₹37,241.
- **Buffer coverage:** 0.8 months.
- **Combined-scenario shortfall probability:** 47.3%, so the band is "High stress - suggest review", with resilience 35.3/100.
- **Shortfall probability per scenario:** baseline 0.001, income drop 0.093, expense spike 0.088, payment delay 0.019.
- **Alternative terms:** a 20% smaller loan gives 0.136 and a tenure 24 months longer gives 0.126 (both Vulnerable). Moving the due date gives 0.466, which barely helps because income already arrives before the due date.
- One run takes 0.09 s.

## Acceptance checks

| Check | Evidence |
|---|---|
| Deterministic with the seed | `test_deterministic_with_seed`: identical output on repeat; a different seed gives a different result |
| Unit test for each metric formula | `test_emi_formula`, `test_min_cash_balance`, `test_shortfall_probability`, `test_max_shortfall`, `test_months_in_deficit`, `test_recovery_time`, `test_stressed_foir`, `test_buffer_coverage`, `test_resilience_score` (4 cases) and `test_bands` (5 cases), all checked against hand-computed values |

Also tested: the shape of the result; shocks never make things better than baseline; a delayed salary always causes a shortfall in a tight budget; insufficient data leads to review; the alternatives lower the burden; the twin is not used by the decision pipeline.

## Issue found

- My first payment-delay test expected 100% shortfall, but the model correctly gave 23%. With ₹10k of monthly surplus, savings grow enough after about 3 months to absorb a late salary, so only delays in the first three months cause a shortfall (3/12 ≈ 25%). The test scenario was wrong, not the model, so it was rewritten with a ₹1k surplus.

## Open issues

- Every threshold, shock size and the resilience formula are illustrative and need calibration against real cash-flow data.
- The model is monthly. A salary delay that pushes income past the 30-day cycle is still counted within that month: a documented simplification.
