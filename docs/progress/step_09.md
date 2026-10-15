# Step 09: Disparate-impact audit on actual decisions

Date: 2026-10-15.

## What was built

`src/cognilend/fairness/disparate_impact.py`:

- **Approval rate per subgroup** for gender, age band (≤25 / 26-35 / 36-45 / 46-55 / >55) and dependents (0 / 1-2 / 3+). The full-pipeline numbers come from the **decisions table joined to applicants** (batch `test-eval`).
- **DI** is a subgroup's rate divided by the reference's rate. The reference is the most-favoured subgroup with enough data; it is configurable, and `Unknown` can never be the reference. DI < 0.80 is flagged.
- **Uncertainty and small groups:** each subgroup's n and a bootstrap 95% CI are reported (2,000 resamples, subgroup and reference resampled independently). Groups with n < 30 are "insufficient data": reported, never flagged, never hidden.
- **Three modes plus two context columns:**
  - rules only: approved if the rule outcome is PASS
  - model only: approved if the tree predicts Approved
  - full pipeline
  - historical label (context)
  - pipeline not-rejected: Approved or Human Review
- **Contribution shift** per feature, subgroup and split (train vs test): `fairness_contrib_shift.csv`.
- **Breach test:** 200 synthetic applicants are added as a new gender subgroup at half the overall approval rate.
- **Mitigation analysis** never uses a protected attribute: counterfactual rule removal (single rules and combinations), a global τ sweep, and a tree retrained without the age proxy `work_experience`.
- **Storage and outputs:** each mode is saved to `fairness_reports` with a `run_id` and versions. Outputs are `fairness.md`, `fairness_di.png`, `fairness_di.csv` and `fairness_contrib_shift.csv`.
- **Chart:** the three-colour palette passed the dataviz validator. Aqua is below 3:1 contrast, so distinct marker shapes, a legend and the matching table provide relief.

## Commands

```
python -m cognilend.fairness.disparate_impact     (17.6 s)
python -m pytest                                  -> 260 passed (11 in test_fairness.py)
```

## Results (test split, n = 1,478; `artifacts/reports/fairness.md`)

**Verdict: DI ≥ 0.80 does NOT hold for every subgroup.** Full-pipeline subgroups below the threshold:

| Subgroup | n | DI (95% CI) | Model only | Rules only | Historical label | Pipeline not-rejected |
|---|---|---|---|---|---|---|
| age ≤25 | 123 | **0.366** (0.212–0.553) | 0.980 | 0.454 | 0.546 | 0.735 |
| age 26-35 | 452 | **0.653** (0.541–0.781) | 0.866 | 0.894 | 0.695 | 0.938 |
| age >55 | 30 | **0.750** (0.338–1.189) | 0.887 | 0.564 | 1.000 | 0.494 |
| dependents 0 | 491 | **0.756** (0.607–0.943) | 0.981 | 0.781 | 0.846 | 0.863 |

- **Gender passes:** Male 0.835 against Female (the most favoured). Transgender (n = 3) and Unknown (n = 25) are insufficient data, and that is reported.
- **The model is not the source.** Model-only DI is at least 0.866 for every subgroup with enough data. The gaps come from the age-linked policy rules (R01 minimum age, R03 age at maturity, and S01/S02, which correlate with age) and from the historical label itself (younger applicants have less experience and thinner credit files).
- **Much of the young applicants' gap is deferral, not rejection.** Their not-rejected DI is 0.735, against 0.366 for approval.
- **Mitigations tried** (none brings every age band to 0.80):
  - Dropping R01 + R03 + S02: lowest age DI 0.366 → 0.666.
  - Dropping S01 + S02: dependents DI 0.756 → 0.803.
  - Global τ = 0.60: age DI 0.490, dependents 0.845, but it auto-approves the least certain leaf.
  - Tree without `work_experience`: model-only age DI 0.879 (was 0.866), accuracy 0.7882 vs 0.7930.
- **Contribution shift**, train vs test, among subgroups with n_test ≥ 30: the largest absolute shift is 0.065 (age ≤25, CIBIL contribution).
- **Breach test:** `SYNTHETIC-BREACH` has DI 0.543 (CI 0.392–0.717) and is flagged = True. It is stored under run `breach_test-…` and listed in the report.
- **Data checks:** recomputing pipeline approvals from the stored rule results and tree outputs gives 0 differences from the decisions table. Gender in `applicants` differs from the protected side table in 0 rows.

## Acceptance checks

| Check | Evidence |
|---|---|
| Breach test flags the skewed subgroup | `test_breach_injection_is_flagged` (toy data) and `test_breach_surfaced_in_report_and_database` (real run: in fairness.md and `fairness_reports`, flagged) |
| Report states plainly whether DI ≥ 0.80 holds; if not, lists mitigations and avoids protected-attribute thresholds | `test_report_states_the_verdict_plainly`: exactly one of the two verdict sentences is present, and on failure the mitigation section, the "Not done, by rule" line and the decision request are required. `test_gender_and_marital_status_never_change_a_decision` (12 combinations, identical output) |

Other tests: the DI and CI maths, small groups reported but not flagged, `Unknown` never used as reference, the subgroup bands, runs saved for every mode, layer table and chart present.

## Issues found and fixed during the step

- In the first run, **`Unknown` dependents** (n = 42, missing data) became the reference group. A missing-data bucket is now never the reference. Dependents-0 DI moved from 0.727 to 0.756.
- The first report lacked the historical-label and not-rejected views, which would have pinned the age gap on the pipeline without context. Both were added.
- My draft conclusion said "no single rule change" reaches 0.80, while combinations had also been tested. It now says no change tried (single or combined) does.
- Chart: the age bands were out of order and the legend overlapped data. Both are fixed.

## Decision needed (team / guide)

The remaining age and dependents gaps come from explicit policy and the repayment signal in the data, not from the model. Options:

- **(a)** Keep the rules as business necessity and document the DI shown here.
- **(b)** Soften S02 / R03 and re-measure. Dropping S01 + S02 already lifts dependents-0 above 0.80.
- **(c)** Audit human-review outcomes for young applicants, since much of their gap is deferral rather than rejection.

This ties in with the open R03 question from Step 6.
