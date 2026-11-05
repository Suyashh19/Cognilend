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
| `data/synthetic/loan_applications_raw.csv` | Reference only; earlier team dataset, not used for training |

**Primary dataset**

- Generated by `src/cognilend/data/synthetic.py` with seed `42`
- 9,847 labelled records
- SHA-256: `084ecd3ca85b3cd788e7f282a1293fbb978d7265ad2141880e7ae1ca06ea39a7`
- Labels come from a latent repayment-risk score with logistic noise and are independent of policy rules R1–R7, so the model cannot simply relearn the rule engine
- A deliberate gender-group bias is injected so the fairness audit has something to detect

**Protected attributes and features**

- `Gender`, `Marital_Status` and the derived `Age_Band` are protected and excluded from model inputs
- `Property_Area` is also excluded from model inputs
- `Age` is used by the policy rules and to derive `Age_Band`, but is not a direct model input

See [`docs/data_decision.md`](docs/data_decision.md) for the full rationale.

---

## Getting Started

### Option A: run from the shared ZIP

1. Install **Python 3.11 or newer** (on Windows, tick *Add python.exe to PATH*).
2. Unzip, then double-click `RUN_ME.bat` (Windows) or run `bash run.sh` (macOS / Linux).
3. The first run installs everything into `.venv` (a few minutes), then opens the app at <http://localhost:8501>.

The trained models and the seeded demo database ship with the ZIP, so nothing needs retraining.

### Option B: from the repository

```bash
git clone https://github.com/Suyashh19/Cognilend.git
cd Cognilend
```

Windows PowerShell (`make <task>` works the same in Git Bash):

```powershell
scripts\tasks.ps1 setup     # creates .venv, installs pinned requirements and the package
scripts\tasks.ps1 train     # preprocessing (70/15/15, train-only fit) + constrained tree
scripts\tasks.ps1 reports   # benchmark, confidence/routing, explanations, rule analysis,
                            # test-set evaluation, 3-run reproducibility, fairness audit
scripts\tasks.ps1 seed      # fresh DB: full test set decided, fairness stored, 7 demo cases
streamlit run app/streamlit_app.py
```

Open <http://localhost:8501>.

### Linux and macOS

```bash
chmod +x run.sh
./run.sh
```

For development, run `make test` before submitting changes. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the recommended workflow.

### Other commands

| Command | Purpose |
|---|---|
| `scripts\tasks.ps1 test` | Run the pytest suite |
| `scripts\tasks.ps1 kpi` | 500-request lock load test, then the full suite with coverage, producing `kpi_report.md` |
| `scripts\tasks.ps1 screens` | Screenshots of every page and demo case, saved to `artifacts/reports/screens/` |

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
├── config/                 settings, policies_v1 (rules with rationale and source),
│                           data contract, fairness, synthetic generator, stress twin
│                           (every threshold is defined here)
├── data/synthetic/         loans_raw.csv
├── src/cognilend/
│   ├── data/               contract, generator, preprocessing
│   ├── rules/              facts, rules, engine
│   ├── ml/                 entropy, tree, benchmark, confidence, explain, tree_plot
│   ├── db/                 models, audit, lock, repository
│   ├── fairness/
│   ├── stress_twin/
│   ├── pipeline.py
│   └── demo.py
├── scripts/                generators, evaluations, report builders
│                           (every reported number comes from one of these)
├── tests/                  pytest suite (evidence gates in test_evidence_gates.py)
├── docs/                   data decision, rule justification, SQL audit queries,
│                           one progress report per step
└── artifacts/reports/      KPI report, benchmark, routing, fairness, reproducibility, screens
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
| ML | scikit-learn, XGBoost (benchmark), NumPy, pandas, custom entropy tree |
| Frontend | Streamlit |
| Database | SQL-based audit store |
| Testing | pytest |
| Tooling | Git and GitHub, PowerShell task runner |

---

## Scope and Limitations

CogniLend is an academic project, not a production lending platform.

- The primary training and evaluation data is synthetic.
- The secondary real-world benchmark (`Loan.csv`) is pending, so no real-world results are claimed.
- Fairness results on synthetic data do not establish fairness in real-world lending.
- Decisions should not replace qualified human assessment at an actual financial institution.
- Out of scope: multi-branch deployment, real-time core-banking integration, live regulatory API feeds.

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
