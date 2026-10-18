# Step 08: All layers in one decision function

Date: 2026-10-15.

## What was built

`src/cognilend/pipeline.py`, `DecisionPipeline.decide(application)`:

1. **Contract validation.** Malformed input is rejected with "invalid input: …", and the decision is still logged.
2. **Facts and rule engine.** A HARD rule means Rejected; the tree is never consulted.
3. **Lock pre-check.** If the applicant or collateral already has an approved active loan, the case goes to Human Review.
4. **Model.** `transform_applicant`, then the constrained tree, giving the prediction, Bayesian confidence and path in original units.
5. **Routing.** A SOFT rule, confidence < τ, or leaf support < n_min sends the case to Human Review.
6. **Persistence.** Applicant, loan, decision, rule results and the audit event are written in one transaction, including the binding lock check. An approval that loses a race becomes Human Review.
7. **Return value.** `{decision, confidence, reason, tree_path, fired_rules, audit_log_id, model_version, policy_version, loan_id, decision_id, source, persisted, fallback_id, …}`

Applicant and loan ids: a missing `Loan_ID` gets a generated id. A missing `Applicant_ID` becomes `APP-<loan_id>`, so an unknown person is never locked against someone else.

Other entry points:
- **`decide_many(csv | DataFrame, batch_id)`** runs normalisation and the tree once over the batch, then persists each decision in its own transaction. It is 3× faster than per-row calls (45 vs 142 ms per row) and produces **identical** decisions (`test_batch_mode_equals_single_decisions`; also checked on 300 rows).
- **`complete_review(review_id, officer, outcome, notes)`** records a HUMAN decision with its own audit event.

Scripts:
- `scripts/evaluate_pipeline.py` writes `data/processed/test_applications.csv` (the cleaned test applications), runs them on a fresh `data/processed/cognilend.db` and writes `pipeline_eval.md` and `pipeline_decisions.csv`.
- `scripts/reproducibility.py` runs the test split 3 times on fresh DBs and writes `reproducibility.md`.

## Commands

```
python scripts/evaluate_pipeline.py     (49.8 s, 33.7 ms/decision)
python scripts/reproducibility.py       (3 x ~46 s)
python -m pytest                        -> 260 passed
```

## Results: full test split (n = 1,478), `artifacts/reports/pipeline_eval.md`

| Decision | Source | n | share |
|---|---|---|---|
| Approved | MODEL | 476 | 0.322 |
| Rejected | RULE (HARD or invalid input) | 490 | 0.332 |
| Rejected | MODEL | 67 | 0.045 |
| Human Review | RULE (SOFT) | 215 | 0.145 |
| Human Review | MODEL (low confidence) | 230 | 0.156 |

- **Coverage:** 1,478 / 1,478 decisions are in the DB (100.0%) and each has an audit event. The chain is OK (1,482 rows: 1,478 decisions plus 4 version registrations). No row went to the fallback log, and none were dropped.
- **Routing:** 69.9% auto-decided, 30.1% human review.
- **Accuracy:** model auto-decisions agree with the historical label 0.9042 of the time (n = 543). Including HARD-rule rejections, agreement is 0.8112: by design, the rules reject some applicants the label approved.

## Acceptance checks

| Check | Evidence |
|---|---|
| Full test set through `decide_many`: 100% decisions and DB rows | `test_full_test_set_coverage_is_100_percent`: 1,478 rows, the same Loan_ID set in the DB, all persisted, chain OK |
| Every output has all 4 parts | `test_every_output_has_the_four_required_parts`: decision, confidence, reason and audit id are non-null for 1,478/1,478 |
| Reproducible over 3 fresh-DB runs | `reproducibility.md`: three runs, identical SHA-256 `6287e61d…` over the stored decision fields (outcome, confidence, reason, rules, tree path, versions). `test_reproducibility_report_says_identical`, plus `test_two_fresh_runs_identical` in pytest |

## Changes to earlier code

- `rules/engine.py` gained `evaluate_many()`, a batch normalisation path with identical per-row results.
- The Step 6 tests now use `DecisionPipeline(persist=False)`, so unit tests don't write into the evaluation DB. Two assertions moved from the old `ml` key to `tree_path` / `model_prediction`.
- The first full run took 110 ms per decision. Profiling showed per-row pandas overhead, which led to the batch path above.

## Open issues

- The "Rejected / RULE" row includes 67 invalid-input rejections: cleaned historical rows still missing a required field. These are data-quality cases, not credit decisions. The fairness audit counts them as not approved.
