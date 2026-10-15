# Step 00: Audit and repository setup

Date: 2026-10-15. Environment: Windows 11, CPython 3.14.3. CPython 3.14 is the only interpreter installed (`py -0p`).

## 1. Inventory: what was found

Project folder before this step (excluding `.git`, `.venv`, `.venv-1`):

| File | Size | What it is |
|---|---|---|
| `loan_applications_raw.csv` | 10,000 rows × 17 cols | **The synthetic Indian dataset.** It has `Loan_ID`, 15 features and `Loan_Status` (Approved/Rejected). Data-quality problems were injected on purpose. |
| `loan_applications_final.csv` | 9,847 × 16 | A reference preprocessed output: 14 scaled features plus the target. Its own report says that the imputation, scaling and selection were **fitted on all rows**, so it leaks and must not be used for training. |
| `report.md` | 25 KB | Documentation for the dataset: how it was generated, its data-quality problems, policy rules R1–R7, and the bias that was injected on purpose |
| `loan_engine.py` | 27 KB | Prototype engine with cleaning, an `Imputer` fitted on train only, feature building, rules R1–R7, an XGBoost model, SHAP reasons, and APPROVE / REJECT / MANUAL_REVIEW decisions |
| `train.py` | 5 KB | Trains the prototype: 80/20 split, monotone XGBoost, fairness audit by gender and area, saves a joblib file |
| `test_scenarios.py` | 9 KB | pytest scenario tests for the prototype |
| `loan_approval_engine.ipynb` | 35 cells | Notebook that walks through the prototype. Its cells were saved without outputs. |
| `loan_approval_prediction.ipynb` | 50 cells | Notebook following the Simplilearn tutorial: label-encode, scale, then RF/NB/DT/KNN |
| `artifacts/` | 4 files | Prototype outputs: `loan_engine.joblib`, `test_decisions.csv`, and two fairness CSVs |
| `.venv/` | | Jupyter venv (py 3.14). It has **no** xgboost, shap or pytest, so the prototype tests cannot run in it. |
| `.venv-1/` | | Empty uv venv containing only pip |

### Searched for and NOT found

| Claimed or expected item | Status |
|---|---|
| `Loan.csv` | **Missing.** Searched the project folder and `C:\Users\Aditya` down to 4 levels. |
| `data_preprosessing.ipynb` (the notebook described in the brief: depth-10 gini tree, leakage, gender used as an input) | **Missing.** None of the problems listed in the brief can be checked against it. |
| Rule-engine code from G12 (forward-chaining, HARD/SOFT) | **Missing** as a separate component. The only rule code is `evaluate_rules()` in `loan_engine.py`: 7 vectorised checks, all treated as hard, with no forward chaining. |
| SQL / schema files, DB layer, audit log, lock layer | **Missing.** The `.sql` files found elsewhere on the machine (`librarydb.sql`, `campus_app/*`) belong to other projects. |
| Fairness layer from G15 | **Partial.** `train.fairness_audit()` computes DIR by gender and property area from model scores. It does not cover age band or dependents, and it does not use final decisions. |
| Streamlit app | **Missing** |
| "53/53 tests passed" | **Not reproduced.** `test_scenarios.py` collects **51** tests, and **51/51 pass** (output below). No other test file exists. |

## 2. How the existing work compares to the spec

The prototype is careful work, and parts of it carry over directly. It also differs from the synopsis in ways that matter.

| Requirement | Prototype | Verdict |
|---|---|---|
| Fit preprocessing on the training split only | Yes: `Imputer` is fitted on the training split only | Reuse (Step 2) |
| Protected attributes excluded from the model | Yes. Gender and Marital_Status are not model inputs, and a test checks that they do not change the score. | Reuse |
| Fitted transformers saved | Yes, but as one pickled engine object without a version | Rework: versioned artefacts |
| Rules before ML; a hard violation means ML is never called (FR-2, FR-6) | **No.** The model scores every row, and `decide()` overrides afterwards. | Rework (Step 3) |
| Constrained entropy DT, depth ≤ 4, ≤ 15 nodes | **No.** It uses XGBoost (300 trees, depth 3). | Rebuild (Step 4). XGBoost becomes the benchmark. |
| Tree path recorded for each prediction (FR-9) | No. SHAP contributions are used instead. | Rebuild |
| 70/30 split, seed 42 everywhere | 80/20 split. Split seed is 42, but the model uses `random_state=0`. | Fix |
| Thresholds in YAML | They are in Python dicts (`POLICY`, `DECISION`) | Moved into `config/policies_v1.yaml` (done) |
| DB, audit, hash chain, lock (FR-4, FR-10) | None | Build (Steps 6–7) |
| DI by gender, age band and dependents | Gender and area only | Extend (Step 8) |
| Target meaning | `Loan_Status` = Approved/Rejected, documented in `report.md` §1.1. This is clear for the synthetic set. | The status=1/default concern applies only to `Loan.csv`, which is missing. |

Reusable pieces to carry forward: the cleaning maps and validity rules, the `Imputer`, the feature formulas (FOIR, LTV slabs, age at maturity), the rule parameters R1–R7, the review triggers (now SOFT rules S1–S6), and the scenario tests, which will be ported to the new API.

## 3. What was built

- Folder tree as specified. The current folder is the repo root, which stands in for `cognilend/`.
- Legacy prototype moved **unchanged** to `notebooks/legacy/` (both notebooks, `loan_engine.py`, `train.py`, `test_scenarios.py`). Its outputs moved to `artifacts/legacy/`.
- CSVs moved to `data/synthetic/`. `report.md` moved to `docs/dataset_report.md`.
- `src/cognilend/` package. Every module named in the brief is a docstring stub, except `config.py`, which is a working YAML loader.
- `config/settings.yaml`: seed 42, 70/15/15 split, tree constraints, KPI thresholds. `config/policies_v1.yaml`: HARD R1–R7 and SOFT S1–S6, with values copied from the prototype. `config/fairness.yaml`: DI ≥ 0.80, gender, age bands, dependents.
- `requirements.txt` (pinned), `pyproject.toml`, `pytest.ini` (`pythonpath = src`, `testpaths = tests`), `.gitignore`, `Makefile`, `scripts/tasks.ps1`, `README.md`.
- `tests/test_smoke.py`: imports every module and checks the configs' key values.
- Git was already initialised (branch `main`, no commits). Nothing has been committed.

## 4. Commands run and output

Prototype claim check (scratch venv, prototype files in their original location):
```
$ python -m pytest test_scenarios.py --collect-only -q   -> 51 tests collected
$ python -m pytest test_scenarios.py -q                  -> 51 passed in 17.65s
```

Prototype baseline (`train.py` run on a copy in scratch, so the repo was not overwritten). This is a reference point and not a result of the new system:
```
Model alone  : accuracy=0.9096  ROC-AUC=0.9551  F1=0.9255      (XGBoost, 80/20 hold-out)
Hybrid engine: auto-decided 84.4%, accuracy on those = 0.9398; 15.6% sent to manual review
DIR (model p>=.5): Female 0.926, Transgender 0.848 (n=11), Unknown 0.820, Rural 0.863
```

Acceptance: fresh venv, plain pip:
```
$ python -m venv .venv-check
$ .venv-check/Scripts/python -m pip install -r requirements.txt   -> exit 0
$ .venv-check/Scripts/python -m pip install -e . --no-deps        -> exit 0
$ pip check                                                       -> No broken requirements found.
$ python -c "import numpy,pandas,sklearn,xgboost,imblearn,sqlalchemy,streamlit,graphviz,dtreeviz,yaml,matplotlib"  -> ok
$ python -m pytest                                                -> 21 passed in 0.19s
```
`.venv-check` was deleted afterwards.

**Note:** the first install attempt, in a venv under the long `%TEMP%\claude\...` path, failed with `WinError 206 (filename too long)` on a deeply nested streamlit template file. The cause is the Windows 260-character path limit, not a requirements problem. Installing at the project path works. If a teammate's path is longer, they should enable long paths (`LongPathsEnabled=1`) or clone to a short path.

## 5. Open issues / decisions needed

1. **Loan.csv and `data_preprosessing.ipynb` are not in this folder.** If they are needed (for example as a second, real-world dataset), please provide them. Until then the synthetic dataset is the primary dataset, and its target meaning is clear (1 = Approved).
2. **Teammates' code:** no separate G12 rule-engine/SQL code or G15 fairness code exists here, and no file explains the "53 tests" claim. Please share any such code before Steps 3, 6 and 8, so that it is reused rather than rewritten.
3. Python floor: the brief says 3.10+, but the pinned pandas 3.0.6 needs ≥ 3.11. If a teammate must use 3.10, the pins need to change to pandas 2.x.
4. `.venv` (the Jupyter venv) was left untouched. `scripts/tasks.ps1 setup` installs into it. A clean `.venv` is recommended: delete it and rerun setup.
5. The prototype's high-score override note and its gender/area fairness use model scores, not final decisions. This will be addressed in Steps 3 and 8.
