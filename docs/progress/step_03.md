# Step 03: Interpretable model under the synopsis constraints

Date: 2026-10-15.

## What was built

- `src/cognilend/ml/entropy.py` is written from scratch in numpy:
  - `entropy()` handles count vectors and treats 0·log 0 as 0.
  - `label_entropy()` and `information_gain()` cover a single split.
  - `best_threshold()` finds the best split for a feature using a vectorised cumulative-count search over midpoints, the same candidates sklearn uses.
  - `rank_features()` ranks all features by their best information gain.
- `src/cognilend/ml/tree.py` trains the model:
  - The classifier is `DecisionTreeClassifier(criterion='entropy', max_depth=4, max_leaf_nodes=8, random_state=42)`. The caps come from config, and `max_leaf_nodes = (15 + 1) / 2`.
  - It sits inside an imblearn `Pipeline`: column selection, then optional SMOTENC, then the tree.
  - **Grid search on the VALIDATION split only:** min_samples_leaf {1, 5, 10, 20, 50, 100, 200} × class_weight {None, balanced} × SMOTE {off, on} × top-k features by information gain {all, 5, 8, 11}, giving 112 fits. Selection order: highest val accuracy, then smallest |gap|, then the simplest configuration. The test split is scored once, after selection.
  - `check_constraints()` asserts depth ≤ 4 and node_count ≤ 15 in code.
  - Exports: `tree_rules.txt`, with thresholds converted back to CIBIL points, ₹, years and FOIR ratio by inverting the saved MinMax scaler; `tree.png` (matplotlib `plot_tree`); `tree.dot`; and `dt_metrics.json`.
  - The saved bundle `artifacts/models/dt_v1.joblib` holds the version, parameters, features, preprocessor version and test predictions, so reproducibility can be checked.

## Commands

```
python -m cognilend.ml.tree      (39 s, 112-fit grid)
python -m pytest                 -> 130 passed in 19.14s
```

## Results

Chosen parameters: all 20 features, SMOTE on, class_weight None, min_samples_leaf 200. **The val accuracy of 0.7827 is identical for every min_samples_leaf from 10 to 200.** The 8-leaf cap is the binding constraint, so the choice is not limited by the edge of the grid.

| | Train | Val | Test |
|---|---|---|---|
| Accuracy | 0.8059 | **0.7827** | 0.7930 |
| ROC-AUC | 0.8667 | 0.8371 | 0.8518 |
| Rejected: precision / recall / F1 | 0.772 / 0.754 / 0.763 | 0.750 / 0.714 / 0.731 | 0.758 / 0.736 / 0.747 |
| Approved: precision / recall / F1 | 0.829 / 0.843 / 0.836 | 0.804 / 0.831 / 0.818 | 0.817 / 0.834 / 0.825 |
| Confusion matrix [[TN, FP], [FN, TP]] | [[2154, 703], [635, 3400]] | [[437, 175], [146, 719]] | [[451, 162], [144, 721]] |

- Depth is **4**, nodes **15**, leaves **8**. These are exactly at the caps.
- Generalization gap (train − val) is **0.0232**, within the ≤ 0.15 limit.
- **KPI: val accuracy ≥ 0.80 is NOT met (0.7827, 1.7 points short).** The caps were not loosened. Step 4 will compare against RF and XGBoost to quantify the cost of interpretability. For reference, Step 1 measured a noise-free ceiling of 0.902 and an unconstrained Random Forest at about 0.863 in CV.
- Features with the highest information gain on train: cibil_score 0.132, foir 0.097, Employment_Type_Salaried 0.050, work_experience 0.043. The tree splits only on cibil_score, foir and work_experience.

Tree, in original units (`artifacts/reports/tree_rules.txt`):
```
CIBIL <= 742
  FOIR <= 0.390
    CIBIL <= 686                         -> Rejected (P(App)=0.233)
    CIBIL > 686: experience <= 12.9 yrs  -> Approved (0.543) ; > 12.9 yrs -> Approved (0.867)
  FOIR > 0.390                           -> Rejected (0.108)
CIBIL > 742
  FOIR <= 0.458: CIBIL <= 777 -> Approved (0.801) ; > 777 -> Approved (0.962)
  FOIR > 0.458:  CIBIL <= 777 -> Rejected (0.280) ; > 777 -> Approved (0.631)
```

## Acceptance checks

| Check | Result |
|---|---|
| Entropy matches scipy within 1e-9 on 1,000 random distributions (including zero classes) | pass (`test_entropy_matches_scipy_on_1000_random_distributions`). The brute-force IG check and the sklearn root-split check also pass within 1e-9. |
| Saved model has depth ≤ 4 and node_count ≤ 15 | pass (`test_saved_model_depth_and_node_caps`) |
| Gap ≤ 15% | pass, 2.3% (`test_generalization_gap_within_limit`) |
| Retraining gives identical predictions | pass. Test predictions and val probabilities are identical (`test_retraining_gives_identical_predictions`). |

## Open issues / decisions for you

1. **The 80% val-accuracy KPI is missed by 1.7 points.** I did not loosen the caps. Step 4 will put a number on the gap against the ensembles.
2. **Leaf probabilities are on the SMOTE-balanced scale.** The leaf `P(Approved)` and `n` are computed on the resampled training data (8,070 rows, 50/50), not on the 58.5% prior. Step 5's Bayesian confidence should recompute leaf class counts on the real (un-resampled) training rows before treating them as probabilities.
3. **Graphviz/dtreeviz images:** neither the Graphviz `dot` binary nor dtreeviz rendering is available on this machine (`C:\Program Files\Graphviz\bin` is on PATH but does not exist). `tree.png` is drawn with matplotlib instead, and `tree.dot` is written for anyone who has Graphviz installed.
4. **Loan.csv benchmark (task 6) is blocked** until the file is supplied.
5. `artifacts/models`, `artifacts/encoders`, `artifacts/reports` and `data/processed` are gitignored, because they are regenerated by `make train` (or `scripts\tasks.ps1 train`). If you want the artefacts versioned in git for the submission, I can un-ignore them.
