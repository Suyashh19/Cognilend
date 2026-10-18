# Step 04: Benchmark the constrained tree

Date: 2026-10-15.

## What was built

`src/cognilend/ml/benchmark.py` compares four models: the saved `dt_v1` tree, Random Forest, XGBoost and sklearn Gradient Boosting.

- All four use the **same split and the same 20 features**.
- The ensembles get light tuning on **validation only**, with grids in `settings.yaml` → `benchmark`: RF 9 candidates, XGB 6, GB 4.
- Every model is scored once on the shared test split. The code asserts that all models were evaluated on identical test Loan_IDs.
- Stratified 5-fold CV on train for all four models (the tree's SMOTE runs inside each fold).
- `benchmark.csv` and `benchmark.md` are written entirely by the script, including the cost figure and the justification paragraph. The paragraph's numbers are filled in from the computed table.

## Commands

```
python -m cognilend.ml.benchmark     (~60 s; run twice, identical numbers)
python -m pytest                     -> 221 passed
```

## Results (`artifacts/reports/benchmark.md`)

| Model | Test acc | Test F1 | Test ROC-AUC | Val acc | CV acc (mean ± sd) | Size | Explainability |
|---|---|---|---|---|---|---|---|
| decision_tree | 0.7930 | 0.8249 | 0.8518 | 0.7827 | 0.7925 ± 0.0094 | depth 4, 15 nodes | direct path |
| random_forest | 0.8674 | 0.8884 | 0.9368 | 0.8626 | 0.8572 ± 0.0091 | 300 trees, depth up to 30 | post-hoc only |
| xgboost | 0.8674 | 0.8888 | 0.9410 | 0.8639 | 0.8672 ± 0.0083 | 300 trees, depth 3 | post-hoc only |
| gradient_boosting | 0.8681 | 0.8889 | 0.9411 | 0.8592 | 0.8626 ± 0.0066 | 200 trees, depth 3 | post-hoc only |

- **Interpretability cost** (best ensemble test accuracy − tree test accuracy) is **0.0751**, or 7.5 points (Gradient Boosting). Computed on validation it is 0.0812, and on CV means 0.0747.
- KPI val accuracy ≥ 0.80: the tree reaches 0.7827 and does **not** meet it. Every ensemble does (the best scores 0.8639).
- The justification paragraph is in benchmark.md. While writing it I removed a claim that the data did not yet support ("most of the tree's errors are in the review leaves") and the word "small". Step 5 later measured that review-routed cases are 0.646 accurate versus 0.889 for auto-decided ones.

## Acceptance checks

| Check | Evidence |
|---|---|
| All four models evaluated on identical test indices | `assert` in `benchmark.run()`. `test_four_models_on_the_same_test_set` (n_test = 1,478 for all) |
| CV and test numbers both reported; every number regenerable | `test_cv_and_test_numbers_reported`. `test_markdown_numbers_come_from_the_csv` checks that every accuracy and the cost in the .md come from the CSV the script writes. `test_decision_tree_row_matches_saved_metrics` |

## Issues

- The console print first failed with `UnicodeEncodeError` (Windows cp1252 cannot print "−"). The files had already been written. Fixed with `sys.stdout.reconfigure(encoding='utf-8')`.
- **The Loan.csv benchmark (task 4) is blocked**, because the file has not been supplied. benchmark.md says so.
