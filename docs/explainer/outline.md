# CogniLend Explained — Outline (for approval)

Each chapter follows the same pattern: plain-language summary → analogy → the idea → how it works in our project
(real file, real function, real numbers) → **In one line** → **Likely viva questions**.
Every number comes from `facts.json` and is cited with its source file.
Figures F1–F20 are planned in D1. "Toy" marks illustrative made-up examples.

---

**0. How to read this document**
How each chapter is laid out, how to read a citation like `[artifacts/reports/dt_metrics.json]`, what "toy example" means, and a suggested reading order for the viva (Chapters 1 → 15 → 26 first).

**1. The project in 2 minutes**
The story of one application from form to answer: contract check → 11 rules → constrained tree → confidence → route → audit log. Fig F1 (architecture) and F2 (story flowchart). The four possible outcomes and how often each occurred on the 1,478 test applications [pipeline_eval.md].

**2. Problem, motivation, objectives, scope, requirements, KPIs**
Why banks need explainable, fair, auditable decisions. Functional requirements FR-1…FR-10 (FR-7/8 not in the brief) and the NFRs, using `docs/traceability.md`. The KPI list with targets. This chapter states only the targets; results come in Ch 20.

**3. Tools primer**
Python, Jupyter (legacy notebooks only), pandas, NumPy, scikit-learn, imbalanced-learn (SMOTE), XGBoost (benchmark only), SQLAlchemy + SQLite, Streamlit, pytest, git, YAML, joblib, matplotlib, playwright. For each tool: what it is, one everyday analogy, and where we use it.

**4. Banking basics**
Loan, principal, interest, tenure, EMI with the formula and a full worked example for one real applicant, then their FOIR and LTV step by step. Also covers CIBIL, FOIR slabs, the RBI LTV slabs, loan-to-income, age at maturity, collateral and new-to-credit (CIBIL −1).

**5. Datasets**
5.1 The synthetic Indian dataset: why we generated it, how (applicant → latent repayment score → label + noise; rules not used to make the label), its 17 columns, the deliberate defects with counts [config/synthetic.yaml] and the deliberately injected historical bias.
5.2 Data contract, 18 fields [config/data_contract.yaml].
5.3 Sample raw rows.
5.4 **Status — Loan.csv:** not supplied, so the label finding and benchmark were not run. The tooling exists and is tested on a stand-in. The unused `data/raw/loan` file is explained.

**6. Data preprocessing**
Normalise text → repair defects (sign errors, tenure in years) → remove duplicates and unlabelled rows (10,000 → 9,847) → 70/15/15 stratified split → banking features → IQR capping → imputation → encoding → scaling → SMOTE (train only). One real row is followed BEFORE → AFTER through every step. Also covers data leakage and why we fit only on train (F5), and the protected-attribute side table.

**7. Machine-learning basics**
Classification, features vs label, train/val/test, overfitting, generalization gap (0.0232), accuracy, precision, recall, F1, ROC-AUC. Our real test confusion matrix (451/162/144/721), with every metric computed by hand and matched to dt_metrics.json (F8).

**8. The Decision Tree**
How a tree decides; entropy and information gain worked by hand on a 10-row toy example (every log2 shown). Why depth ≤ 4 and ≤ 15 nodes. Our real tree (8 leaves; root split CIBIL ≤ 742) with every split in plain English (F7). One applicant's path read aloud. The from-scratch entropy and its 1e-9 check against scipy. KPI status: validation accuracy 0.7827 against the 0.80 target, **missed**.

**9. SMOTE and class imbalance**
The problem; how SMOTE makes synthetic points (F9 toy scatter); our counts 2,857/4,035 → 4,035/4,035; why train only (Gate 3); why leaf confidence counts use real rows, not SMOTE rows.

**10. Benchmark models**
Random Forest ("many trees voting"), Gradient Boosting and XGBoost ("each tree fixes the last one's mistakes"). Results table and F10. Interpretability cost 0.0751. Why we still chose the tree.

**11. Confidence scoring and routing**
Beta posterior (k+1)/(n+2) with the 47/50 vs 2/2 worked example. Credible interval and leaf support. Our τ = 0.70 and n_min = 30, and how τ was tuned on validation. The routing split (test: 894 auto / 584 review, auto accuracy 0.8893), Brier scores, F11. Status: the 90 % auto-accuracy target was **missed**.

**12. Explainability**
Decision path in original units, the one-sentence reason (real demo reasons), path contributions summing to the leaf probability, and known vs unseen/rare profiles (Gate 2: 0 of 335 auto-decided). SHAP not done (exact path contributions instead).

**13. The rule engine**
Expert systems and forward chaining with a step-by-step trace (F12). HARD vs SOFT. A table of all 11 rules from policies_v1.yaml (ID, type, meaning, threshold, rationale, pass/fail example), verified by script. Also covers policy versioning, invalid-input handling, how often each rule fired on training data, and the rules changed from the synopsis.

**14. The database and audit trail**
The 10 tables with an ER diagram (F13) and what one decision writes to each (real rows from a freshly seeded demo DB). A hash chain worked with 3 records, including tampering detection (F14). Append-only triggers. The lock layer as "two people booking the last train seat" (F15), with load-test evidence (500 requests, 50 approvals, max 1 per collateral). The DB-failure fallback log (Gate 4). PostgreSQL DDL included but untested.

**15. The full pipeline**
Sequence diagram (F16). Three real applicants run through the code now — HARD reject, auto-approve, human review — showing every layer's output.

**16. Fairness**
What bias means here. DI and the 80 % rule with a round-number toy example, then our real table per subgroup and layer (label / rules-only / model-only / pipeline), with F17. Status: **missed**. The lowest value is 0.366 for age ≤ 25, caused by age-linked rules and the label, not the model (model-only ≥ 0.866). Why gender, marital status and age band are excluded, and the proxy test.

**17. The application (UI)**
Screenshot-led walk through the home page and all 6 pages; what every button does; the officer review flow.

**18. Add-on: Maximum Approvable Amount**
Why it exists and how it works: classify the rejection → candidate amounts from FOIR/LTV caps and tree breakpoints → confirmation with a side-effect-free dry run. A real worked example, a "not possible" example, and F18. Evaluation: 557 rejected cases, 145 possible, 145 confirmed by the normal pipeline. Screenshots.

**19. Loan Stress Twin (implemented, advisory)**
Monte Carlo cash-flow stress test, the shocks, the metrics, the resilience score, and the real example (resilience 35.3). It never changes a decision. Thresholds are illustrative.

**20. Testing**
What a unit test is. The 7 evidence gates, each with the test that proves it. The KPI PASS/FAIL table from kpi_report.md. Test counts from a **fresh pytest run in D4**: the 314-test JUnit file predates the add-on, and the add-on log is incomplete.

**21. Limitations, changes from the synopsis, future work**
Every deviation from changes_from_synopsis.md and every missed KPI, each with a one-line viva answer.

**22. Code map**
Folder tree; a table per folder (file | purpose | main functions | who calls it); dependency diagram (F19); the 10 most important functions line by line.

**23. How to run the project**
A guide for someone who has never used a terminal on Windows: setup, train, test, seed, launch the app; expected output; common errors.

**24. Glossary**
80+ terms, A–Z.

**25. Viva question bank**
60+ questions grouped by topic, including hard "why not X?" questions.

**26. One-page cheat sheet**
Architecture picture, key numbers, KPIs with results, 10 one-line answers.

---

**No chapter is dropped.** Every part of the requested outline exists in the code, except Loan.csv, which is handled as a Status note inside Ch 5.
