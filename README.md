# Cognilend
A Hybrid Rule-and-ML System for Explainable, Fair Loan Decisioning

Third-year mini project, Department of AI & ML, Walchand College of Engineering, Sangli
(Apni Leap Initiative, AY 2026-27). Guide: Dr. V. N. Waghmare.

> ⚠️ **Status: work in progress.** Each layer has been built and tested **on its own**. The layers
> are **not yet integrated** into one pipeline. See [Known issues](#known-issues) and
> [Roadmap](#roadmap-what-will-be-done).

---

## What the system does

Every loan application passes through four layers in order:

```
Applicant form (Streamlit / Flask)
   │
   ▼
Layer 1  Policy rules (expert system) ── hard rule fails ──► REJECT with the rule cited
   │ all hard rules pass
   ▼
Layer 2  ML model → P(approve) + explanation
   ├── high confidence ──► AUTO APPROVE / AUTO REJECT
   └── low confidence / soft-rule flag / missing data ──► human loan officer
   ▼
Layer 3  DBMS / audit: every input, rule result, prediction and decision is stored (append-only)
   ▼
Layer 4  Fairness: approval rates per subgroup, disparate-impact ratio ≥ 0.80
   ▼
Output: Approved / Rejected + confidence + human-readable reason + audit-log ID
```

| Group | Responsibility |
|---|---|
| **G10** | Core ML: preprocessing, model training, benchmarking, confidence score |
| **G12** | Rules + DBMS: policy-rule layer, relational schema, audit trail |
| **G15** | Fairness + integration: human-review routing, end-to-end pipeline, fairness audit, UI |

---

## Repository layout

| Folder | Owner | Contents | Status |
|---|---|---|---|
| `preprocessing/` | G10 | `dataset/` raw (10,000 × 17) and final (9,847 × 16) CSVs, column dictionary; `scripts/phase_0/` data generation and collection; `reports/final_report.md` describes every data-quality issue and cleaning step | ✅ done |
| `model_training/` | G10 | `loan_engine.py` (cleaning → imputation → features → rules R1–R7 → model → decision with reasons), `train.py` (XGBoost training + fairness audit), `test_scenarios.py` (pytest edge cases), notebooks | ✅ works standalone, ⚠️ see issues 1–3 |
| `database/` | G12 | MySQL 8 scripts `01`–`09`: schema, seed rules, triggers, stored procedures, views, roles, import, 50+ edge-case tests. Details in [`database/README.md`](database/README.md) | 🧪 **prototype**, see issues 4–5 |
| `rule_ui/` | G12 | Flask demo page that runs the database rule layer and the "try to tamper" checks | 🧪 test UI only |

---

## Database layer (G12) in short

The full documentation is in [`database/README.md`](database/README.md).

- **Rules are stored as data** (`policy_rule` table) and versioned (`rule_set`). Changing policy
  creates a new version, so old decisions stay reproducible.
- **HARD vs SOFT rules.** A failed HARD rule rejects the application. A failed SOFT rule sends it
  to a human. Each rule also says what to do when data is missing (FAIL / REFER / SKIP).
- **The pipeline runs through stored procedures:** `sp_submit_application` → `sp_run_rule_layer` →
  `sp_record_prediction` / `sp_record_model_failure` → `sp_claim_review` / `sp_resolve_review` →
  `sp_run_fairness`.
- **Audit guarantees are enforced by triggers.** Decisions, rule evaluations, predictions and audit
  rows are append-only. The audit log is a SHA-256 hash chain, so tampering is detectable. A
  rule-rejected application can never be approved later. Inputs are frozen after submission.
- **Least-privilege roles.** The ML user can only read a de-identified feature view (no gender,
  age or dependents).

**This is a raw test implementation.** It proves the design and its edge cases. The final
database will be rebuilt during integration with the agreed stack (MySQL/PostgreSQL + a single
Python data-access module), aligned to the team's dataset and rules (see below).

---

## Known issues

Found while reviewing the repo on 2026-10-02. These are not yet fixed.

### Code

1. **`train.py` and `test_scenarios.py` cannot run as committed.** They import
   `model_training.loan_engine`, so they must be run from the repo root. But they read
   `pd.read_csv('loan_applications_raw.csv')`, which only exists in `preprocessing/dataset/`, so no
   working directory satisfies both. The notebooks have the same relative path.
   *Fix:* build the path from the file location, e.g.
   `Path(__file__).resolve().parents[1] / 'preprocessing/dataset/loan_applications_raw.csv'`.
2. **There is no root `requirements.txt`.** The ML code needs `pandas`, `numpy`, `scikit-learn`,
   `xgboost`, `shap`, `joblib` and `pytest`. Only `rule_ui/requirements.txt` exists.
3. **`trash.py` is still tracked.** It is listed in `.gitignore`, but it was committed before the
   ignore rule was added. Remove it with `git rm --cached trash.py`.

### Integration

4. **The database expects a different dataset.** `database/01_schema.sql` and
   `07_import_dataset.sql` were written for Kaggle `Loan_Default.csv` (148k rows: `dtir1`, `LTV`,
   `Credit_Worthiness`, …). The team's pipeline uses `loan_applications_raw.csv` (CIBIL score, FOIR,
   employment type, co-applicant income, existing EMI, collateral, property area, marital status).
   `07_import_dataset.sql` also has a hard-coded local path.
5. **There are two separate rule sets.** `loan_engine.py` has R1–R7 (CIBIL ≥ 650, FOIR slabs by
   income, RBI LTV slabs, maturity age and experience by employment type). The database seeds
   R01–R10 (score ≥ 550, DTI ≤ 50 %, LTV ≤ 90 %, blacklist, loan stacking, …). The same applicant
   could get different answers from each.

### Synopsis vs implementation (update one or the other before review)

| Synopsis says | Code does |
|---|---|
| Decision Tree, depth ≤ 4, ≤ 15 nodes, benchmarked against RF / XGBoost | Main model is XGBoost (300 trees, depth 3, monotone constraints) with SHAP explanations. A constrained Decision Tree is not yet the production model |
| Naive Bayes / Bayesian layer for the confidence score | Confidence comes from the model's own probability (approve ≥ 0.65, reject < 0.35, in between → review) |
| 148,000+ records, ~75 / 25 class split | 10,000 synthetic Indian-bank records, 58.5 / 41.5 split |
| 70 / 30 split + SMOTE | 80 / 20 stratified split, no SMOTE (mild imbalance, so it is not needed) |
| Fairness subgroups: gender, age band, dependents | `train.py` audits Gender and Property_Area. The database supports gender, age band and dependents |

---

## Roadmap (what will be done)

### Phase 1: fix the basics
- [ ] Fix the dataset paths in `train.py`, `test_scenarios.py` and the notebooks (issue 1)
- [ ] Add a root `requirements.txt` and setup steps to this README (issue 2)
- [ ] Untrack `trash.py` (issue 3)
- [ ] Decide on the model: train a constrained Decision Tree (depth ≤ 4) as the explainable
      production model with XGBoost as the benchmark, **or** update the synopsis to XGBoost + SHAP

### Phase 2: integrate the rule layer and the database (G12 with G10)
- [ ] **One rule catalogue.** Move `POLICY` / `RULE_TEXT` from `loan_engine.py` into `policy_rule`
      as rule set v2.0, and keep the database-only rules (blacklist, loan stacking, re-apply abuse)
- [ ] **Python computes the values, the database applies the thresholds.** `sp_run_rule_layer`
      takes the facts built by `build_features()` (`foir`, `foir_limit`, `ltv`, `ltv_cap`,
      `age_at_maturity`, …), so the rules and the model see identical numbers
- [ ] Re-align the schema columns and the import script to `loan_applications_raw.csv` (issue 4)
- [ ] Add a `db.py` module that is the **only** code talking to the database (submit, run rules,
      record prediction or failure, review, fairness), with an outbox file when the DB is down
- [ ] Register the trained model in `model_version` with the SHA-256 of the saved file

### Phase 3: pipeline, UI and fairness (G15)
- [ ] `pipeline.decide(application)`: a single entry point that runs submit → rules → model →
      routing → audit and returns the decision, confidence, reasons and audit ID
- [ ] Streamlit/Flask applicant form plus an officer review screen (based on `v_review_backlog`)
- [ ] Fairness runs through `sp_run_fairness` and a dashboard (disparate-impact ratio ≥ 0.80)

### Phase 4: evidence for the review
- [ ] Run `test_scenarios.py` end to end through the pipeline. Check that 100 % of decisions are
      logged with a source and timestamp
- [ ] Fault injection (database down, model crash), and a reproducibility check over 3 runs
- [ ] Fill in the KPI and "Minimum Engineering Evidence" tables from the synopsis with real numbers

---

## Running what exists today

**Database prototype.** In MySQL 8 Workbench, run `database/01`–`06`, then `08` (tests). The full
steps are in [`database/README.md`](database/README.md). For the demo page, run
`bash rule_ui/setup.sh` once, then `bash rule_ui/run.sh` and open http://127.0.0.1:5000.

**ML model.** This needs issue 1 fixed first. Then, from the repo root:

```bash
pip install pandas numpy scikit-learn xgboost shap joblib pytest
python -m model_training.train
pytest -q model_training/test_scenarios.py
```

