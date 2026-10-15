# Step 05: Confidence score, routing threshold and per-decision explanation

Date: 2026-10-15.

## What was built

- **`src/cognilend/ml/confidence.py`**
  - For every leaf of `dt_v1`, it counts the **real training rows** (6,892, before SMOTE).
  - With a Beta(1,1) prior, it computes the posterior mean of the class the tree predicts, (k+1)/(n+2), and its 90% credible interval (scipy `beta.interval`). It also stores the leaf support n.
  - It stores real-count P(Approved) for every node, which the contribution calculation needs.
  - Calibration on validation: a Brier score and a reliability diagram (`calibration.png`) comparing the Bayesian leaf posterior with the raw `predict_proba`.
  - It tunes τ on validation and writes `confidence_v1.joblib`, `routing.md` and `routing.json`.
- **`src/cognilend/ml/explain.py`**: `Explainer.explain(clean_rows)` returns, for each applicant:
  - the leaf, prediction, confidence, credible interval, support and route
  - the path as a list of `{feature, direction, threshold, applicant_value, imputed, contribution, text}`, with thresholds and values in original units (inverse MinMax)
  - one sentence explaining the decision
  - per-feature path contributions: P(child) − P(parent), using real-count node probabilities
  
  `run()` writes `explanations.md` and `explain_shift.csv`, which compare train and test.
- **Settings:** `confidence.tau: 0.70` (copied from the tuning output, and a test checks they agree) and `n_min: 30`.

## Commands

```
python -m cognilend.ml.confidence
python -m cognilend.ml.explain
python -m pytest           -> 221 passed in 52.85s
```

## Results

Leaf table, from real train counts:

| Leaf | n | tree predicts | confidence | 90% CI | val observed P(App) |
|---|---|---|---|---|---|
| 4 | 1446 | Rejected | 0.854 | [0.839, 0.869] | 0.162 |
| 7 | 1002 | Rejected | 0.694 | [0.670, 0.718] | 0.336 |
| 9 | 908 | Approved | 0.631 | [0.604, 0.657] | 0.650 |
| 10 | 555 | Approved | 0.901 | [0.880, 0.921] | 0.846 |
| 11 | 857 | Approved | 0.853 | [0.833, 0.873] | 0.837 |
| 12 | 1309 | Approved | 0.967 | [0.959, 0.975] | 0.945 |
| 13 | 341 | Rejected | 0.650 | [0.607, 0.692] | 0.347 |
| 14 | 474 | Approved | 0.689 | [0.654, 0.723] | 0.644 |

**Calibration on validation (Brier score, lower is better):** the Bayesian leaf posterior scores **0.1578** and the raw tree `predict_proba` (SMOTE-balanced scale) scores 0.1613.

**Routing.** The rule is: auto-decide when confidence ≥ τ **and** n ≥ n_min.
- **The 90% auto-accuracy target cannot be met while also keeping review ≤ 50%** (the "majority auto-cleared" KPI). The tree has only 8 leaves, and only two of them (n = 555 and n = 1,309) are ≥ 90% pure.
- As designed in `tune_tau`, the fallback picks the best auto accuracy within the 50% review cap: **τ = 0.70**.

| Split | n | auto | review | auto share | auto acc | review acc | overall tree acc | dropped |
|---|---|---|---|---|---|---|---|---|
| val | 1477 | 870 | 607 | 0.589 | 0.8724 | 0.6540 | 0.7827 | 0 |
| test | 1478 | 894 | 584 | 0.605 | **0.8893** | 0.6455 | 0.7930 | 0 |

These numbers are for the ML layer alone. In the full pipeline the rule layer acts first.

**Contributions, train vs test** (`explanations.md`): tree importance is cibil_score 0.603, foir 0.349, work_experience 0.048. Mean absolute contributions from train to test: CIBIL 0.2028 → 0.2011, FOIR 0.1740 → 0.1731, experience 0.0271 → 0.0257. The largest shift is −0.0017, and leaf shares differ by at most 0.014, so there is no material shift between known and held-out data.

Example sentence: *"Rejected (confidence 0.85, leaf of 1446 past applicants) because CIBIL 660 <= 742 and FOIR 0.528 > 0.390."*

## Acceptance checks

| Check | Evidence |
|---|---|
| Every test prediction gets a confidence in (0,1), a path and a sentence | `test_every_test_prediction_has_confidence_path_and_sentence` (all 1,478). Also `test_explanations_match_saved_model_predictions`, `test_contributions_sum_to_leaf_probability` (within 1e-9) and `test_path_values_are_in_original_units_and_consistent` |
| The smallest leaves are routed to review (evidence gate) | `test_evidence_gate_routes_smallest_leaves_to_review`: with n_min set above the smallest leaf, every case in that leaf goes to review and nothing else does. `test_route_rule` (4 cases) |
| Routing split numbers printed | `routing.md` and `routing.json`, the table above, and `test_routing_split_none_dropped_and_majority_auto` |

## Issues found and fixed

- **Imputed values were shown as real.** When an applicant's CIBIL was *missing*, the sentence printed the imputed median ("CIBIL 735") as if it were their score. Now every path step carries `imputed`, and the text reads "735 (imputed: input missing)". In the live pipeline a missing CIBIL already goes to review through S04.
- A test first compared clean rows and processed rows in different orders (the parquet files are saved in split order). Fixed by aligning on Loan_ID. This was a test bug, not a code bug.

## Open issues

1. **Decision needed: the routing target.** 90% auto accuracy is not compatible with majority auto-clearing for this 8-leaf tree. At τ = 0.70 we get 60.5% auto at 0.889 accuracy (test). The alternative is τ = 0.87, which auto-decides only the two purest leaves (about 25%) at about 0.93 accuracy. That would put most cases in human review and break the KPI.
2. **`n_min = 30` currently never fires.** The smallest leaf has 341 training rows. The gate is tested and becomes active if a future tree has thin leaves.
3. The optional SHAP comparison was not done. Path contributions are exact for a single tree, so SHAP would add little here.
