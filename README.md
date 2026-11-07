# CogniLend

**A hybrid rule-and-ML system for explainable, fair loan decisioning.**

TY AIML Mini Project · Walchand College of Engineering, Sangli · Apni Leap Initiative · AY 2026-27
Guide: **Dr. V. N. Waghmare** · Groups: **G10** Core ML · **G12** Rules + DBMS · **G15** Fairness + Integration

---

## Overview

Loan decisions are usually made either by rigid rule engines, which cannot adapt to non-standard but creditworthy applicants, or by opaque ML models, which are hard to explain and audit. CogniLend combines both: a forward-chaining policy rule layer handles hard eligibility and regulatory checks, and a constrained, interpretable decision tree handles the data-driven part. Every decision is confidence-scored, logged to a tamper-evident audit trail, and checked for fairness.

## Novelty Features

CogniLend introduces several features that extend beyond conventional rule-based and ML-driven loan prediction systems.
1. Stress Twin Indicator
- Simulates 1,000 possible financial scenarios over a 12-month period using Monte Carlo simulation.
- Evaluates income drops, unexpected expenses, salary delays and combined financial stress.
- Calculates shortfall probability, recovery time and a Financial Resilience Score (0–100).
- Evaluates alternative loan terms to improve borrower affordability.
- Operates independently as an advisory tool without directly influencing loan decisions.
  
2. Fairness Audit & Bias Diagnostics
- Measures Disparate Impact across gender, age groups and dependent categories.
- Uses the 80% fairness threshold and 95% bootstrap confidence intervals.
- Compares fairness across rule-based, ML-based and complete decision pipelines.
- Identifies potential bias through rule-ablation and proxy-feature experiments.
- Includes synthetic bias-injection tests to validate bias detection.
  
3. Bayesian Confidence Estimation
- Estimates prediction confidence using Bayesian Beta posterior distributions.
- Generates 90% credible intervals to quantify prediction uncertainty.
- Considers training sample support at individual decision-tree leaves.
- Routes low-confidence predictions to human review.
  
4. Explainable AI (XAI)
- Traces individual predictions through decision-tree paths.
- Identifies the conditions influencing each loan decision.
- Provides feature-level contributions to approval probability.
- Highlights missing and imputed applicant information.
  
5. Tamper-Evident Audit Trail
- Maintains decision records using SHA-256 hash chaining.
- Links audit entries through previous-record hashes.
- Detects record tampering and inconsistencies through chain verification.
- Preserves decision traceability and accountability.
  
6. Hybrid Rule-ML Decision Engine
- Combines forward-chaining policy rules with a constrained entropy-based Decision Tree.
- Applies hard rules for immediate rejection of policy violations.
- Routes soft-rule violations and uncertain predictions to human review.
- Maintains explainable and traceable decision outcomes.

Each application ends in one of three outcomes:

| Decision | Meaning |
|---|---|
| **Approved** | The application satisfies the policy rules and the model is sufficiently confident |
| **Rejected** | A hard policy rule fired, or the model rejects with sufficient confidence |
| **Human Review** | A soft rule fired, or model confidence is too low, so the case goes to a loan officer |

Alongside the decision, the system returns a confidence value with a credible interval, a human-readable reason, the decision-tree path, and an audit-log ID. An **advisory stress twin** (a Monte Carlo cash-flow stress test) is shown separately and never changes the decision.

---

## Architecture

Every application passes through these layers in order:

```text
Streamlit UI
     │
     ▼
Contract validation
     │
     ▼
L1  Policy rules        forward chaining   (HARD = reject, SOFT = review)
     │
     ▼
FR-10 lock
     │
     ▼
L2  Constrained entropy tree (depth ≤ 4, ≤ 15 nodes) + Bayesian confidence
     │
     ▼
L3  Audit DB            hash-chained, append-only
     │
     ▼
L4  Disparate-impact fairness audit
     │
     ▼
Approved / Rejected / Human Review
```

| Layer | Component | Responsibility |
|---|---|---|
| L1 | Policy Rule Engine | Hard and soft eligibility rules (e.g. minimum age, blacklist status, maximum DTI); a hard failure rejects immediately and cites the rule |
| FR-10 | Decision Lock | Controls concurrent decision processing |
| L2 | ML Prediction | Constrained entropy-based decision tree with Bayesian confidence and a credible interval |
| L3 | Audit Database | Append-only, hash-chained decision records (rule or model source, confidence, timestamp) |
| L4 | Fairness Audit | Disparate-impact ratio across applicant subgroups; the threshold is 0.80 |

Low-confidence predictions are routed to human review rather than silently auto-decided.

---

## Machine Learning Approach

- **Model:** custom entropy-based decision tree
- **Constraints:** depth ≤ 4, nodes ≤ 15
- **Confidence:** Bayesian estimate with a credible interval
- **Benchmarking:** compared against Random Forest and XGBoost to establish an accuracy ceiling
- **Split:** 70 / 15 / 15 (train / validation / test); preprocessing is fitted on the training set only to avoid leakage
- **Explainability:** every prediction carries its tree path and a readable reason

---

## Data

| Dataset | Role |
|---|---|
| `data/synthetic/loans_raw.csv` | **Primary.** Deterministic synthetic dataset used for training, validation and testing |
| `Loan.csv` | Secondary real-world benchmark (pending availability) |
| `loan_applications_raw.csv` (earlier team dataset) | Replaced by the synthetic dataset; not used for training. Kept with the phase-wise preprocessing work in the **v1.0-legacy** release |

**Primary dataset**

- Generated by `src/cognilend/data/synthetic.py` with seed `42`
- 9,847 labelled records
- SHA-256: `084ecd3ca85b3cd788e7f282a1293fbb978d7265ad2141880e7ae1ca06ea39a7`
- Labels come from a latent repayment-risk score with logistic noise and are independent of the hard policy rules R01–R07, so the model cannot simply relearn the rule engine
- A deliberate gender-group bias is injected so the fairness audit has something to detect

**Protected attributes and features**

- `Gender`, `Marital_Status` and the derived `Age_Band` are protected and excluded from model inputs
- `Property_Area` is also excluded from model inputs
- `Age` is used by the policy rules and to derive `Age_Band`, but is not a direct model input

See [`docs/data_decision.md`](docs/data_decision.md) for the full rationale.

---

## Getting Started

### Quick start: one click after cloning

**You only need two things installed:**

- **Git** (to clone the repository)
- **Python 3.11 or newer**, from <https://www.python.org/downloads/>. On Windows, tick **Add python.exe to PATH** during installation.

**1. Clone the repository**

```bash
git clone https://github.com/Suyashh19/Cognilend.git
cd Cognilend
```

**2. Launch**

| System | What to do |
|---|---|
| **Windows** | Double-click **`RUN_ME.bat`** in the `Cognilend` folder |
| **macOS / Linux** | Run `./run.sh` in a terminal (or `bash run.sh`) |

**3. Use the app** at <http://localhost:8501>. To stop it, close the window (Windows) or press `Ctrl+C`.

That is all. The launcher does everything else by itself:

| First run (a few minutes, once) | Every later run (seconds) |
|---|---|
| Creates a private Python environment (`.venv`) and installs every package from `requirements.txt` | Skips setup |
| Prepares the data and trains the decision tree | |
| Trains the confidence model | |
| Creates the database and decides the 7 demo cases | |
| Runs the model comparison | |
| Starts the app | Starts the app |

Each setup step runs only when its output is missing, so if the first run is interrupted, launching again
continues where it stopped. Nothing is installed outside the project folder.

**If something goes wrong**

| Message or problem | Fix |
|---|---|
| `Python 3.11 or newer is required` | Install Python 3.11+ (tick *Add python.exe to PATH*), then launch again |
| Windows "Open File - Security Warning … Unknown Publisher" when starting `RUN_ME.bat` | Appears only for files from a downloaded ZIP (not after `git clone`). The script is plain text you can read in Notepad, so click **Run** (untick *Always ask* to stop the prompt). To avoid it: before extracting, right-click the ZIP → **Properties** → tick **Unblock** → **OK**; or, for an already extracted folder, run `Get-ChildItem -Recurse <folder> \| Unblock-File` in PowerShell |
| `./run.sh: Permission denied` | Run `bash run.sh` instead |
| Port 8501 already in use | Close the other window or app using it, then launch again |
| `Setup failed` (Windows) or `run.sh` stops with an error | Read the error message, fix it, then launch again; setup resumes |

### For developers

The same steps are available one at a time. On Windows PowerShell use `scripts\tasks.ps1 <task>`; on
macOS or Linux (or Git Bash, if `make` is installed) use `make <task>`.

```powershell
scripts\tasks.ps1 setup     # creates .venv, installs pinned requirements and the package
scripts\tasks.ps1 train     # preprocessing (70/15/15, train-only fit) + constrained tree
scripts\tasks.ps1 reports   # benchmark, confidence/routing, explanations, rule analysis,
                            # test-set evaluation, 3-run reproducibility, fairness audit
scripts\tasks.ps1 seed      # fresh DB: full test set decided, fairness stored, 7 demo cases
scripts\tasks.ps1 app       # start the app
```

**Running the tests on a fresh clone:** some tests check report files that the one-click launcher does not
create. Launch the app once (or run `setup`, `train`, `reports`, `seed`), then:

```powershell
scripts\tasks.ps1 reports   # if not run yet
scripts\tasks.ps1 kpi       # lock load test + full suite with coverage (about 10 minutes)
scripts\tasks.ps1 test      # pytest suite
```

Without `reports` and `kpi`, 4 tests fail with "file not found"; that is expected, not a bug. Run the tests
before submitting changes; see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the recommended workflow.

If PowerShell refuses to run the script, use
`powershell -ExecutionPolicy Bypass -File scripts\tasks.ps1 <task>`.

### Other commands

| Command | Purpose |
|---|---|
| `scripts\tasks.ps1 all` | Run the whole pipeline end to end (`scripts/run_all.py`) |
| `scripts\tasks.ps1 kpi` | 500-request lock load test, then the full suite with coverage, producing `artifacts/reports/kpi_report.md` |
| `scripts\tasks.ps1 screens` | Screenshots of every page and demo case, saved to `artifacts/reports/screens/` (needs Chrome or Edge) |

---

## Demo Scenarios

Open **New Application** with `?demo=` set to one of:

| Scenario | Demonstrates |
|---|---|
| `hard_reject` | Hard policy rejection |
| `auto_approve` | Automatic approval |
| `auto_reject` | Model-driven rejection |
| `soft_review` | Soft-rule routing to manual review |
| `low_confidence` | Low-confidence routing to human review |
| `lock` | Decision-lock behaviour |
| `malformed` | Contract validation of bad input |

---

## Repository Layout

```text
Cognilend/
├── app/                    Streamlit UI (presentation only)
│   ├── streamlit_app.py    entry point: registers every page and its URL
│   ├── common.py           shared page setup, sidebar menu, decision card
│   ├── views/              one file per page: home, new_application, review_queue,
│   │                       audit_explorer, model_and_policy, fairness,
│   │                       model_comparison, stress_twin, style_guide
│   ├── ui/                 components, charts, format, theme, max_amount_panel
│   └── assets/             logo, styles.css
├── .streamlit/             config.toml (Streamlit theme and server settings)
├── config/                 settings, policies_v1 (rules with rationale and source),
│                           data contract, features, fairness, fraud registry,
│                           synthetic generator, stress twin (every threshold is defined here)
├── data/
│   ├── synthetic/          loans_raw.csv (primary dataset)
│   ├── raw/                placeholder for the real-world benchmark (empty)
│   └── processed/          generated (git-ignored): parquet splits, cognilend.db
├── src/cognilend/
│   ├── config.py           loads config/*.yaml and project paths
│   ├── data/               contract, synthetic (generator), loaders, preprocess
│   ├── rules/              facts, rules, engine
│   ├── ml/                 entropy, tree, benchmark, compare, confidence, explain, tree_plot
│   ├── db/                 models, audit, lock, repository
│   ├── fairness/           disparate_impact
│   ├── stress_twin/        simulator
│   ├── max_amount/         maximum-approvable-amount advisor: dry_run, search, suggestion_store
│   ├── pipeline.py         single entry point: rules → model → audit
│   └── demo.py             the seven demo cases
├── scripts/                generators, evaluations, report builders, tasks.ps1
│   └── max_amount/         evaluation and screenshots for the advisor
│                           (every reported number comes from one of these)
├── tests/                  pytest suite (evidence gates in test_evidence_gates.py)
│   └── max_amount/         advisor tests
├── docs/                   data decision, rule justification, SQL audit queries, final report,
│                           presentation, one progress report per step (progress/, ui/, explainer/)
├── evidence/max_amount/    committed evidence for the advisor: baseline, evaluation, screenshots
├── artifacts/              generated (git-ignored): models/, encoders/, reports/ (KPI report,
│                           benchmark, routing, fairness, reproducibility, screens)
├── RUN_ME.bat / run.sh     one-click launchers (Windows / macOS + Linux)
├── Makefile                same tasks as scripts/tasks.ps1, for macOS / Linux / Git Bash
├── requirements.txt        pinned dependencies
├── pyproject.toml          installs src/cognilend as a package (no dependencies listed here)
├── pytest.ini              test settings (tests/ folder, src/ on the path)
└── CONTRIBUTING.md         contributor workflow
```

---

## Testing and Evaluation

The suite covers data-contract validation, rule-engine behaviour, the ML pipeline, confidence estimation, decision routing, fairness evaluation, audit logging, decision-lock behaviour, reproducibility and app integration.

Key project targets (full table in the synopsis):

| Area | Target |
|---|---|
| Validation accuracy | ≥ 80%, with a train-validation gap ≤ 15% |
| Interpretability | Tree depth ≤ 4, nodes ≤ 15 |
| Rule correctness | 100% of hard-rule violations caught before the model |
| Audit completeness | 100% of decisions logged with source and timestamp |
| Fairness | Disparate-impact ratio ≥ 0.80 across measured subgroups |
| Reproducibility | Same input gives the same decision across 3 runs |

Engineering-evidence scenarios include rule-versus-model conflict, rare profiles, missing or invalid fields, DB write failure and fairness-threshold breach. Generated reports are written to `artifacts/reports/`.

### Understanding a decision

- **Approved** means the policy rules passed and the constrained tree was sufficiently confident in approval.
- **Rejected** means a hard policy rule fired, or the model rejected with sufficient confidence.
- **Human Review** means a soft rule fired or the model did not have enough confidence for an automatic decision.
- The **confidence interval** describes uncertainty in the model's approval estimate; it is not a guarantee of repayment.
- The **Stress Twin** is advisory only and never changes the decision.

---

## Tech Stack

| Category | Technology |
|---|---|
| Language | Python 3.11+ |
| ML | scikit-learn, XGBoost (benchmark), NumPy, pandas, SciPy, custom entropy tree |
| Frontend | Streamlit, Plotly, Matplotlib |
| Database | SQLite through SQLAlchemy (hash-chained audit store) |
| Testing | pytest, pytest-cov, Streamlit AppTest, Playwright (screenshots) |
| Tooling | Git and GitHub, PowerShell task runner, Makefile |

---

## Scope and Limitations

CogniLend is an academic project, not a production lending platform.

- The primary training and evaluation data is synthetic.
- The secondary real-world benchmark (`Loan.csv`) is pending, so no real-world results are claimed.
- Fairness results on synthetic data do not establish fairness in real-world lending.
- Decisions should not replace qualified human assessment at an actual financial institution.
- Out of scope: multi-branch deployment, real-time core-banking integration, live regulatory API feeds.

---

## Project Versions

| Version | What it contains |
|---|---|
| **v2 (current, `main`)** | Compact structure: only the files the app, tests and scripts use, with clearer folder names (`app/views`, `app/ui`, `src/cognilend/max_amount`, `evidence/`) |
| **v1.0-legacy** (GitHub release) | Commit `78be163`: the complete project before the cleanup, including the `archive/` folder (phase-wise preprocessing, earlier team datasets, legacy model code and outputs), the MySQL prototype, the old Flask rule UI, duplicate notebooks, unused code and the one-time old-vs-new UI regression checks. Frozen for history |

Progress reports for each step are kept in [`docs/`](docs/).

---

## Team and Academic Information

| Detail | Information |
|---|---|
| Programme | B.Tech Artificial Intelligence and Machine Learning (Third Year) |
| Institution | Walchand College of Engineering, Sangli |
| Initiative | Apni Leap |
| Academic Year | 2026-27 |
| Guide | Dr. V. N. Waghmare |
| Project Coordinator | Mr. G. S. Bhosale |
| Groups | G10 Core ML · G12 Rules + DBMS · G15 Fairness + Integration |

---

*Building loan decisioning systems that are interpretable, auditable, and fairness-aware.*
