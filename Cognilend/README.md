# CogniLend

A hybrid rule-and-ML system for explainable, fair loan decisioning.
TY AIML mini project, WCE Sangli (Apni Leap, AY 2026-27). Guide: Dr. V. N. Waghmare.
Groups: G10 Core ML, G12 Rules + DBMS, G15 Fairness + Integration.

Every application passes through these layers in order:

```
Streamlit UI -> contract validation -> L1 policy rules (forward chaining; HARD = reject, SOFT = review)
             -> FR-10 lock -> L2 constrained entropy tree (depth <= 4, <= 15 nodes) + Bayesian confidence
             -> L3 audit DB (hash-chained, append-only) -> L4 disparate-impact audit
```

The output is **Approved / Rejected / Human Review**, together with a confidence (with a credible interval), a reason a person can read, the path through the tree, and an audit-log ID. An advisory **stress twin** (a Monte Carlo cash-flow test) is shown separately and never changes the decision.

## Run it (from the shared zip)

1. Install Python 3.11 or newer (on Windows, tick "Add python.exe to PATH").
2. Unzip, then double-click `RUN_ME.bat` (Windows) or run `bash run.sh` (macOS / Linux).
3. The first run installs everything into `.venv` (a few minutes). The app then opens at http://localhost:8501.

The trained models and the seeded demo database come with the zip, so nothing needs to be retrained.

## Quick start (Windows PowerShell; `make <task>` works the same in Git Bash)

```powershell
scripts\tasks.ps1 setup     # Python >= 3.11: creates .venv, installs pinned requirements and the package
scripts\tasks.ps1 train     # preprocessing (70/15/15, fitted on train only) + constrained tree
scripts\tasks.ps1 reports   # benchmark, confidence/routing, explanations, rule analysis,
                            # test-set evaluation, 3-run reproducibility, fairness audit
scripts\tasks.ps1 seed      # fresh DB: full test set decided, fairness stored, 7 demo cases
streamlit run app/streamlit_app.py
scripts\tasks.ps1 test      # pytest
scripts\tasks.ps1 kpi       # 500-request lock load test, then the full suite with coverage -> kpi_report.md
scripts\tasks.ps1 screens   # screenshots of every page and demo case -> artifacts/reports/screens/
```

To open a demo case, go to *New Application* with `?demo=` set to `hard_reject`, `auto_approve`, `auto_reject`, `soft_review`, `low_confidence`, `lock` or `malformed`.

## Layout

| Path | Contents |
|---|---|
| `config/` | settings, policies_v1 (rules with rationale and source), data contract, fairness, synthetic generator, stress twin. Every threshold is defined here. |
| `src/cognilend/` | `data` (contract, generator, preprocessing), `rules` (facts, rules, engine), `ml` (entropy, tree, benchmark, confidence, explain, tree_plot), `db` (models, audit, lock, repository), `fairness`, `stress_twin`, `pipeline.py`, `demo.py` |
| `app/` | Streamlit UI: presentation only |
| `scripts/` | generators, evaluations and report builders. Every reported number comes from one of these. |
| `tests/` | pytest suite (evidence gates in `test_evidence_gates.py`) |
| `docs/` | data decision, rule justification, SQL audit queries, one progress report per step |
| `artifacts/reports/` | generated reports (KPI report, benchmark, routing, fairness, reproducibility, screens) |
