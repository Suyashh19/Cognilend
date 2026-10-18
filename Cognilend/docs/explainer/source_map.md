# CogniLend — Source map

Every file the explainer draws on, with one line on what it does. Paths are relative to the project root.
Numbers are never taken from this page; they come from `facts.json`.

## 1. Core library — `src/cognilend/`

| File | What it does |
|---|---|
| `__init__.py` | Package marker: "hybrid rule-and-ML system for explainable, fair loan decisioning". |
| `config.py` | `load(name)` reads a YAML file from `config/`. All thresholds live in config, never in code. |
| `pipeline.py` | `DecisionPipeline.decide()` — the orchestrator: contract → rules → lock → tree → confidence routing → audit DB. |
| `demo.py` | Seven demo applications, one per decision path (hard reject, auto approve, auto reject, soft review, low confidence, lock, malformed). |
| **data/** | |
| `data/contract.py` | Input schema (FR-1): field names, types, units, valid ranges; `validate()` never crashes; `age_band()`. |
| `data/loaders.py` | `load_synthetic_raw()` (primary data); `load_loan_csv()` + label-investigation helpers for Loan.csv (file not supplied). |
| `data/synthetic.py` | Seeded generator of the synthetic Indian dataset: applicants → latent risk score → label → injected defects. |
| `data/preprocess.py` | Cleaning (normalise, repair, dedupe), 70/15/15 split, banking features (FOIR, LTI, coverage), IQR capping, imputation, encoding, scaling, SMOTE on train only; saves `preprocessor_v1`. |
| **ml/** | |
| `ml/entropy.py` | Entropy and information gain written from scratch in NumPy; checked against scipy to 1e-9. |
| `ml/tree.py` | Trains the constrained entropy tree (depth ≤ 4, ≤ 15 nodes), grid search, metrics, rule export, `dt_v1.joblib`. |
| `ml/tree_plot.py` | `draw_tree()` — matplotlib drawing of the tree in original units, optionally highlighting one applicant's path. |
| `ml/confidence.py` | Beta(1,1) posterior per leaf, `route()` with τ and n_min, τ tuning on validation, calibration plot, `confidence_v1.joblib`. |
| `ml/explain.py` | `Explainer`: feature-by-feature path in original units, one-sentence reason, path contributions. |
| `ml/benchmark.py` | Random Forest, Gradient Boosting, XGBoost vs the tree on the same test set; CV; `benchmark.csv/md`. |
| **rules/** | |
| `rules/facts.py` | Builds the fact base from an application: FOIR, FOIR limit, LTV, LTV cap, age at maturity, new-to-credit, registry hit… |
| `rules/rules.py` | `Rule` objects loaded from `config/policies_v1.yaml`. |
| `rules/engine.py` | Forward-chaining inference: derive facts, fire rules; HARD → REJECT, SOFT → REVIEW, else PASS; invalid input handled. |
| **db/** | |
| `db/models.py` | SQLAlchemy tables: applicants, loans, decisions, rule_results, policy_versions, model_registry, audit_log, review_queue, fairness_reports, loan_locks; append-only guard. |
| `db/repository.py` | `Repository`: records a decision in one transaction, review queue, chain verification; `FallbackLog` file when the DB fails. |
| `db/audit.py` | Hash-chained, append-only audit log: canonical JSON → SHA-256 linked to previous hash; `verify_chain()`. |
| `db/lock.py` | Lock layer (FR-10): blocks a second approval for the same applicant or collateral. |
| **fairness/** | |
| `fairness/disparate_impact.py` | DI ratio per subgroup (gender, age band, dependents) with bootstrap CIs, layer ablation (label / rules / model / pipeline), proxy removal, breach injection, report + chart. |
| **stress_twin/** | |
| `stress_twin/simulator.py` | Advisory Monte Carlo cash-flow stress test (income drop, expense spike, payment delay); resilience score; never changes a decision. |
| **addons/** (max-approvable-amount feature, untracked in git) | |
| `addons/dry_run.py` | `evaluate_without_saving()` — runs the real pipeline with no repository: no DB, no lock, no audit row. |
| `addons/max_amount.py` | `find_max_approvable_amount()` — classifies the rejection, builds candidate amounts from FOIR/LTV caps and tree breakpoints, confirms with the dry run. |
| `addons/suggestion_store.py` | Best-effort log of suggestions in a separate `amount_suggestions` table; read-only lookup of the decided application. |

## 2. App — `app/`

| File | What it does |
|---|---|
| `streamlit_app.py` | Home page and entry point (`streamlit run app/streamlit_app.py`). |
| `common.py` | Shared UI helpers: cached pipeline and repository, `decision_card()`, rule line formatting. |
| `pages/1_New_Application.py` | Application form → decision card (decision, confidence, reason, audit ID, path). Max-amount panel added here (2 lines). |
| `pages/2_Officer_Review_Queue.py` | Officer sees review cases and records a human decision. |
| `pages/3_Audit_Explorer.py` | Browse decisions and the audit log; "verify chain" button. |
| `pages/4_Model_and_Policy.py` | Tree image and rules, policy table, model/policy versions. |
| `pages/5_Fairness_Dashboard.py` | DI tables and chart per subgroup. |
| `pages/6_Stress_Twin.py` | Advisory stress-test page. |
| `components/max_amount_panel.py` | "See maximum approvable amount" button under a Rejected decision (behind a feature flag). |

## 3. Configuration — `config/`

| File | What it holds |
|---|---|
| `settings.yaml` | Seed, paths, split ratios, tree caps, KPI thresholds, τ and n_min, preprocessing and model grids, DB URL. |
| `policies_v1.yaml` | Policy v1: 7 HARD (R01–R07) + 4 SOFT (S01–S04) rules with thresholds, reasons, rationale, source; FOIR/LTV slabs; indicative rates. |
| `data_contract.yaml` | Every input field: dtype, unit, required, role, protected, model, valid range. |
| `fairness.yaml` | Protected attributes, DI threshold 0.80, subgroup bins, min group size, bootstrap settings. |
| `fraud_registry.yaml` | Applicant IDs on the internal fraud / wilful-defaulter list (rule R02). |
| `synthetic.yaml` | Every generator parameter: distributions, latent-score weights, injected bias and defects. |
| `stress_twin.yaml` | Shock sizes and bands for the stress twin (illustrative). |
| `features.yaml` | Add-on flag and parameters for the max-approvable-amount feature. |

## 4. Data — `data/`

| File | What it is |
|---|---|
| `synthetic/loans_raw.csv` | The raw (dirty) synthetic dataset the pipeline uses (path in `settings.yaml`). |
| `synthetic/loan_applications_raw.csv` | Another raw synthetic file (different hash); not on the configured path. |
| `synthetic/loan_applications_final.csv` | A cleaned export (9,847 rows); not read by the pipeline. |
| `synthetic/team_reference/*` | Team's own cleaned / semi-processed files and column-meaning document (reference only). |
| `raw/loan` | 10,000-row CSV with `Loan_Status` (dated 15 Oct). **Not read by any code**; not the Kaggle Loan.csv. |

## 5. Scripts — `scripts/`

| File | What it does |
|---|---|
| `run_all.py` | Rebuild everything from a fresh clone in order, then run the tests. |
| `seed_demo.py` | Fresh demo database + the 7 demo cases (for the app). |
| `evaluate_pipeline.py` | Whole test split through the pipeline on a fresh DB → `pipeline_eval.md`, `pipeline_decisions.csv`. |
| `kpi_report.py` | Runs pytest with coverage; writes `kpi_report.md` (KPI PASS/FAIL, gates). |
| `lock_load_test.py` | 500 concurrent requests on 50 collaterals through the full pipeline. |
| `reproducibility.py` | 3 fresh-DB runs; digest compared → `reproducibility.md`. |
| `rule_analysis.py` | Each threshold analysed on training data → `docs/rule_justification.md`. |
| `describe_synthetic.py` | Profiles the synthetic data → `synthetic_profile.json`. |
| `build_docs.py` | Generates final report, traceability, changes-from-synopsis, presentation from artefacts. |
| `screenshots.py` | Headless app screenshots → `artifacts/reports/screens/`. |
| `tasks.ps1`, `Makefile` | Task shortcuts. |
| `addons/max_amount_eval.py` | Max amount on every rejected test case, confirmed by the normal pipeline. |
| `addons/max_amount_screens.py` | Screenshots of the panel → `reports/screens/max_amount/`. |
| `addons/decisions_snapshot.py`, `file_hashes.py`, `regression_report.py` | Regression guard: prove the add-on changed no existing decision or file. |

## 6. Reports and artefacts

| File | What it holds |
|---|---|
| `artifacts/models/dt_v1.joblib`, `confidence_v1.joblib` | Trained tree; leaf confidence table. |
| `artifacts/encoders/preprocessor_v1.joblib` | Fitted preprocessing pipeline. |
| `artifacts/reports/dt_metrics.json` | Tree size, accuracies, gap, confusion matrices, SMOTE counts, information-gain ranking. |
| `artifacts/reports/tree_rules.txt`, `tree.png`, `tree.dot` | Tree in original units (text, image, dot). |
| `artifacts/reports/preprocess_summary.json` | Rows in/out, features, split sizes, class shares. |
| `artifacts/reports/synthetic_profile.json` | Dataset profile (rule-violation rates, label vs rules). |
| `artifacts/reports/benchmark.csv/md` | Tree vs RF / GB / XGBoost. |
| `artifacts/reports/routing.json/md`, `calibration.png` | τ tuning, routing split, Brier scores, reliability plot. |
| `artifacts/reports/rare_subset.json` | Gate 2: rare profiles and where they went. |
| `artifacts/reports/explanations.md`, `explain_shift.csv` | Sample explanations. |
| `artifacts/reports/pipeline_eval.md`, `pipeline_decisions.csv` | Test split through the full pipeline. |
| `artifacts/reports/fairness*.csv/md/png/json` | DI tables, ablation, τ sweep, proxy test, chart. |
| `artifacts/reports/rule_analysis.json` | Rule fire counts on training data. |
| `artifacts/reports/lock_load_test.json/md`, `lock_latency.json` | Concurrency evidence. |
| `artifacts/reports/reproducibility.md` | 3-run identity check. |
| `artifacts/reports/kpi_report.md`, `junit.xml`, `pytest_output.txt`, `coverage.json` | KPI table and test evidence (314 tests, pre add-on). |
| `artifacts/reports/demo_cases.json`, `stress_twin_example.json` | Demo outcomes; stress twin example. |
| `artifacts/reports/screens/*.png` | 13 app screenshots. |
| `artifacts/legacy/*` | Team's original XGBoost prototype and its fairness CSVs. |
| `reports/feature_max_amount_eval.md/csv` | Add-on evaluation on 557 rejected test cases. |
| `reports/screens/max_amount/*.png` | 5 add-on screenshots. |
| `reports/baseline/*`, `pytest_after_*.txt` | Pre-add-on baseline; `pytest_after_addons.txt` is **incomplete** (cut off). |

## 7. Tests — `tests/`

| File | What it proves |
|---|---|
| `test_smoke.py` | Modules import; configs load. |
| `test_contract.py` | Contract accepts clean rows, rejects bad values, never crashes on garbage, protected fields excluded. |
| `test_synthetic.py` | Generator deterministic; committed file matches; label not a function of rules; defects present. |
| `test_loaders.py` | Loan.csv label-investigation tooling on a toy frame; clear error when file missing. |
| `test_preprocess.py` | Defects fixed; split sizes; statistics fitted on train only; SMOTE changes train only. |
| `test_tree.py` | Entropy vs scipy (1,000 cases); information gain; caps; gap; honest KPI flag; reproducible. |
| `test_confidence.py` | Beta posterior; leaf counts are real rows; τ matches tuning; explanations and contributions. |
| `test_rules.py` | Every rule fires/passes at its boundary; malformed input handled. |
| `test_db.py` | Hash chain, tamper detection, append-only triggers, one transaction, lock incl. 50 concurrent threads. |
| `test_pipeline.py` | 100 % coverage, four-part output, none dropped, batch = single, HARD reject without model. |
| `test_fairness.py` | DI maths, small groups, breach detection, gender never changes a decision. |
| `test_benchmark.py` | Four models on one test set; Markdown numbers match CSV. |
| `test_evidence_gates.py` | The 7 evidence gates + NFR checks as one named index. |
| `test_stress_twin.py` | EMI formula and every stress metric. |
| `test_app.py` | Every Streamlit page renders; demo cards; officer review; verify-chain button. |
| `addons/test_dry_run.py` | Dry run equals the real decision for every test case, with no side effects. |
| `addons/test_max_amount.py` | Search correctness; every suggestion approved by the normal pipeline; runtime; protected fields unused. |
| `addons/test_suggestion_store.py` | Separate table only; core tables and chain untouched. |
| `addons/test_ui_panel.py` | Button only under Rejected; other screens unchanged; flag-off unchanged. |

## 8. Project documents — `docs/`

`final_report.md`, `presentation.md`, `traceability.md`, `changes_from_synopsis.md`, `data_decision.md`, `dataset_report.md`, `rule_justification.md`, `synopsis_references.md`, `audit_queries.sql` (11 queries), `weekly_tracker_october.md`, `feature_max_approvable_amount.md`, `progress/step_00…12.md`.

## 9. Legacy — `notebooks/legacy/`

The team's original notebooks and XGBoost prototype (`loan_engine.py`, `train.py`, `test_scenarios.py`). Kept for history; not used by the pipeline.

## 10. Not part of the project

`p.out` (a cProfile dump), `.claude/`, `.agents/`.
