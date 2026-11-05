# Feature-parity checklist (baseline UI on `main`)

Every page, input, button, message, table, chart and flow of the UI as it was before the redesign.
Line references point at the baseline files on `main` (`git show main:<file>`). Each item is ticked (U7) with
the evidence that proves it still works (screenshot in `docs/ui/after/` or a check in `docs/ui/regression/`).

Legend for fields: name (label) · backend key · type · unit · validation (bounds come from `config/data_contract.yaml`).

## 0. App shell
_Evidence: after/screens/*.png (all URLs open; menu in every shot); tests/test_app.py page renders._
- [x] P0.1 Multipage app, entry `app/streamlit_app.py`; pages auto-listed in the sidebar from `app/pages/` (7 pages)
- [x] P0.2 Page URLs: `/`, `/New_Application`, `/Officer_Review_Queue`, `/Audit_Explorer`, `/Model_and_Policy`, `/Fairness_Dashboard`, `/Stress_Twin`, `/Model_Comparison` (used by `scripts/screenshots.py`, `scripts/addons/max_amount_screens.py`, README)
- [x] P0.3 Browser tab title `CogniLend - <page>` and wide layout (`common.py:21` `st.set_page_config`)
- [x] P0.4 Page title `h1` on every page (`common.py:22` `st.title`) — screenshot scripts wait for `h1`

## 1. Home (`streamlit_app.py`)
_Evidence: after/screens/home.png (H2–H6 tiles + chain status); H8 demo links._
- [x] H1 Intro paragraph: rules → tree → audit DB → fairness; three outcomes (`:12` markdown)
- [x] H2 Metric **Approved** count (`:19`, `repo().summary()['decisions']`)
- [x] H3 Metric **Rejected** count (`:19`)
- [x] H4 Metric **Human Review** count (`:19`)
- [x] H5 Metric **Open reviews** (`:20`, `summary()['open_reviews']`)
- [x] H6 Caption `Audit chain: <status> (<n> events)` (`:22`, `repo().verify_chain()`)
- [x] H7 Error `Database not reachable: … Run python scripts/seed_demo.py` when the DB fails (`:24`)
- [x] H8 Page list + demo-case list (`?demo=` names) (`:25`)

## 2. New Application (`pages/1_New_Application.py`)
_Evidence: after/screens/new_application_form.png, demo_*.png, max_amount_*.png; regression/ui_checks.md; regression/calls/diff.md (form_*, json_*); tests/addons/test_ui_panel.py (page compared with main)._
### Messages
- [x] N1 Caption: "Submit an application to see the policy checks … Gender and marital status are collected for fairness auditing only …" (`:14`)
- [x] N2 `?demo=<name>` deep link runs `demo.run_case(pipeline, name)` once per session (`demo_done`) and shows the result (`:18-22`)
- [x] N3 Caption `Demo case: **<title>** (expected: <decision>)` (`:23`)
- [x] N4 Tabs **Application form** / **Raw JSON (any input, incl. malformed)** (`:25`)
### Form fields (`st.form('application')`, `:27-52`)
- [x] F1 Loan ID (optional) · `Loan_ID` · text · — · empty → omitted (`:29`)
- [x] F2 Applicant ID, e.g. PAN (optional) · `Applicant_ID` · text · — · empty → omitted (`:30`)
- [x] F3 Collateral ID (optional, secured loans) · `Collateral_ID` · text · — · empty → omitted (`:31`)
- [x] F4 Age (years) · `Age` · int · years · 18–75, default 35 (`:33`)
- [x] F5 Gender (audit only, not used to decide) · `Gender` · category `'' / Male / Female / Transgender` · '' → omitted (`:34`)
- [x] F6 Marital status (audit only) · `Marital_Status` · category `'' / Married / Single / Divorced / Widowed` · '' → omitted (`:35`)
- [x] F7 Dependents · `Dependents` · int 0/1/2/3 (3 shown as "3+") · default 1 (`:36`)
- [x] F8 Employment type · `Employment_Type` · category Salaried / SEP / SENP · default Salaried (`:38`)
- [x] F9 Work experience / business vintage (years) · `Work_Experience` · int · years · 0–57, default 10 (`:39`)
- [x] F10 Monthly income (₹) · `Monthly_Income` · int · ₹/month · 1–100,000,000 step 1000, default 150,000 (`:40`)
- [x] F11 Co-applicant income (₹/month, 0 = none) · `Coapplicant_Income` · int · ₹/month · 0–100,000,000 step 1000; 0 → omitted (`:41`)
- [x] F12 Existing EMIs (₹/month) · `Existing_EMI` · int · ₹/month · 0–100,000,000 step 500, default 0 (always sent) (`:43`)
- [x] F13 New to credit (no CIBIL score) · checkbox → `CIBIL_Score = -1` (`:44`)
- [x] F14 CIBIL score · `CIBIL_Score` · int · points · 300–900, default 780; disabled when F13 ticked (`:45`)
- [x] F15 Property area · `Property_Area` · category Urban / Semi-Urban / Rural · default Urban (`:46`)
- [x] F16 Loan type · `Loan_Type` · category Home / Vehicle / Personal / Business · default Home (`:48`)
- [x] F17 Loan amount (₹) · `Loan_Amount` · int · ₹ · 10,000–1,000,000,000 step 10000, default 3,000,000 (`:49`)
- [x] F18 Tenure (months) · `Loan_Tenure` · int · months · 6–360, default 240 (`:50`)
- [x] F19 Collateral value (₹, 0 = unsecured) · `Collateral_Value` · int · ₹ · 0–10,000,000,000 step 10000, default 5,000,000; 0 → omitted (`:51`)
- [x] F20 Button **Submit application** (primary) → `pipeline().decide(app)` with None-valued keys dropped; stored as `session_state['last_app']` / `['result']` (`:52-61`)
### Raw JSON tab
- [x] J1 Text area **Application JSON**, pre-filled with the malformed demo application (`:64`)
- [x] J2 Button **Submit JSON** → `json.loads` → `pipeline().decide(payload)` (any payload, incl. non-dict) (`:66-74`)
- [x] J3 Error `Not valid JSON: …` when the text is not JSON (`:71`)
### Result (`common.decision_card`, below a divider `:77`)
- [x] R1 Outcome headline `## :blue[Approved]` / `:orange[Rejected]` / `:violet[Human Review]` (`common.py:44`)
- [x] R2 Metric **Confidence** (2 dp, help: "Estimated approval probability …") (`common.py:47`)
- [x] R3 Metric **90% credible interval** `lo - hi`, or "rule decision" (`common.py:50`)
- [x] R4 Metric **Audit-log ID** (or "not stored") (`common.py:52`)
- [x] R5 Metric **Decided by** RULE / MODEL (`common.py:53`)
- [x] R6 **Reason** heading + caption + info box with the backend reason (`common.py:54-56`)
- [x] R7 Caption: loan id · applicant id · policy · model (or "not consulted") · leaf support (`common.py:57`)
- [x] R8 Warning when the DB write failed: fallback log id (`common.py:60`)
- [x] R9 Error `Invalid input in: <fields>` for malformed input (`common.py:62`)
- [x] R10 **Policy rules** list: every rule evaluation as ✗ fired (red HARD / orange SOFT) / ✓ passed / – other, with value and threshold (`common.py:65-70`)
- [x] R11 "Rules not evaluated: the input failed contract validation." for invalid input (`common.py:68`)
- [x] R12 **Decision tree** figure with this applicant's path highlighted (`draw_tree`) + the path as bullet text (`common.py:72-76`)
- [x] R13 "Model not consulted (HARD rule or invalid input; FR-6)." (`common.py:78`)
### Max approvable amount (add-on, `components/max_amount_panel.py`)
- [x] M1 Button **See maximum approvable amount** directly below a **Rejected** result only; hidden when `config/features.yaml` flag is off (`:84`, `:75-79`)
- [x] M2 Spinner "Searching for the highest amount that would be approved..." and result cached in session state per decision (`:86`)
- [x] M3 Possible: success "**Can be approved up to ₹X**" + explanation (`:54`)
- [x] M4 Metrics **Requested**, **Reduction** (with −%), **EMI at ₹X (n months)**, **Confidence at max** (`:56-59`)
- [x] M5 Caption "Deciding limit: **…** · model · policy · n amounts checked in t ms" (`:60`)
- [x] M6 Caption "Suggestion only, not an approval. …" (`:63`)
- [x] M7 Expander **Re-apply with ₹X**: caption + JSON of the same application with the new amount, no Loan_ID; nothing auto-submitted (`:65-69`)
- [x] M8 Not possible: info "**No lower amount can be approved**" + why (`:51`)
- [x] M9 Not applicable / error messages as info (`:43`, `:46`)
- [x] M10 Suggestion logging is best effort (DB error never hides the result) (`:30-38`)
### Other models
- [x] O1 Expander **Other models (advisory only, not used for the decision)** with `compare.advise(...)` table + caption, only when the model was consulted (`1_New_Application.py:84-88`)
- [x] O2 Caption `Advisory models unavailable: …` on error (`1_New_Application.py:89-91`)

## 3. Officer Review Queue (`pages/2_Officer_Review_Queue.py`)
_Evidence: after/screens/review_queue.png; calls/diff.md officer_record_decision; tests/test_app.py::test_officer_review_records_human_decision._
- [x] Q1 Caption "`n` open cases (newest first). Deciding here records a separate HUMAN decision …" (`:13`, `repo().list_reviews('OPEN')`)
- [x] Q2 Success "No open reviews." when empty (`:16`)
- [x] Q3 Table: review_id, loan_id, applicant_id, loan_type, amount, model_recommendation, confidence, source, reason (`:19`)
- [x] Q4 Select **Case** `#id - loan_id` (`:22`)
- [x] Q5 "**Why it is here:** <reason>" (`:24`)
- [x] Q6 Form: **Officer ID** text (default `officer-1`), **Decision** radio Approved / Rejected, **Note (required)** text area (`:25-28`)
- [x] Q7 Button **Record decision** → `pipeline().complete_review(review_id, officer, outcome, notes)` (`:29-35`)
- [x] Q8 Error "A note is required." when the note is blank (no backend call) (`:32`)
- [x] Q9 Success "Recorded HUMAN decision <id> (audit-log ID <seq>)." / Error "Not approved: <reason> (audit-log ID …)" (lock) (`:36-38`)
- [x] Q10 **Recently closed** table: review_id, loan_id, officer_decision, notes (`list_reviews('CLOSED', limit=20)`) (`:41-43`)

## 4. Audit Explorer (`pages/3_Audit_Explorer.py`)
_Evidence: after/screens/audit_explorer.png; calls/diff.md audit_verify_chain; tests/test_app.py::test_audit_explorer_verify_chain_button._
- [x] A1 Text input **Loan ID or applicant ID (prefix search)**, default from `?q=` or `DEMO` (`:13`)
- [x] A2 Button **Verify chain** (primary) → `repo().verify_chain()`, result kept in session (`:15-18`)
- [x] A3 Success "Audit chain OK: n events verified." / Error "Audit chain BROKEN at seq s: problem" (`:22-24`)
- [x] A4 Caption "n decisions" (`repo().decision_history(term)`) (`:27`)
- [x] A5 Table: decision_id, loan_id, applicant_id, source, outcome, confidence, fired_rules, policy_version, model_version, audit_seq, created_at (`:30`)
- [x] A6 Select **Decision** + "**Reason:** …" (`:33-35`)
- [x] A7 Audit event `#seq` `event_type` at time; prev_hash / hash code block; payload JSON (`repo().audit_event(seq)`) (`:37-40`)

## 5. Model & Policy (`pages/4_Model_and_Policy.py`)
_Evidence: after/screens/model_and_policy.png (benchmark table + versions tables in expanders / bottom)._
- [x] MP1 **Versions in force**: policies table and models table (`repo().versions()`) (`:19-22`)
- [x] MP2 Metrics: Val accuracy, Test accuracy, Gap (train-val), Depth, Nodes, KPI val >= 0.80 met / NOT met (`dt_metrics.json`) (`:24-32`)
- [x] MP3 Full tree figure (`draw_tree`) + caption on units (`:33-34`)
- [x] MP4 **Benchmark** table from `benchmark.csv` (`:36-39`)
- [x] MP5 Routing caption tau / n_min / auto share / accuracy (`routing.json`) (`:40-44`)
- [x] MP6 **Policy rules** table: id, type, name, condition, rationale, source (`load_rules(load_policy('v1'))`) (`:46-48`)

## 6. Fairness Dashboard (`pages/5_Fairness_Dashboard.py`)
_Evidence: after/screens/fairness_dashboard.png; calls/diff.md fairness_rerun._
- [x] FD1 Button **Rerun fairness audit** (primary) → spinner → `disparate_impact.run()` → success "Fairness audit rerun and stored." (`:16-19`)
- [x] FD2 Warning "No fairness runs stored yet …" and stop when there are no runs (`:23-24`)
- [x] FD3 Caption "Last run: <mode> at <time> UTC, …" (`:28`)
- [x] FD4 Success "DI >= 0.80 holds for every subgroup …" or error listing flagged subgroups with DI and n (`:36-38`)
- [x] FD5 DI figure (`disparate_impact.figure(rows)`), all three modes, 0.80 line (`:40`)
- [x] FD6 Table (pipeline mode): group, subgroup, n, approval_rate, di, ci_low, ci_high, flagged, insufficient (`:41`)
- [x] FD7 Caption "Evidence gate: injected SYNTHETIC-BREACH subgroup DI …, flagged = …" (`:47`)
- [x] FD8 Expander **Full fairness report (mitigation analysis, contribution shift)** with `fairness.md` (`:51-52`)

## 7. Stress Twin (`pages/6_Stress_Twin.py`)
_Evidence: after/screens/stress_twin.png; calls/diff.md stress_twin_default (same StressInputs)._
- [x] ST1 Warning "Advisory panel only …" (`:14`)
- [x] ST2 Form inputs: Monthly income mean (₹) 0–10,000,000 = 80,000; Income variability CV 0–2 = 0.15; Income credit day 1–28 = 1; Essential expenses (₹/month) 0–10,000,000 = 35,000; Existing EMIs (₹/month) 0–10,000,000 = 5,000; Proposed loan amount (₹) 0–1,000,000,000 = 1,500,000; Annual interest rate 0–0.5 = 0.105; Tenure (months) 1–360 = 60; EMI due day 1–28 = 5; Liquid savings (₹) 0–1,000,000,000 = 60,000, in `st.form("stress_form")` (`:17-33`)
- [x] ST3 Button **Run stress test** → `simulate(StressInputs(...))`, `alternatives(...)`; runs once on first load (`:35-42`)
- [x] ST4 Band · resilience heading + caption on paths / horizon / bands (`:44-45`)
- [x] ST5 Error "Insufficient data: …" (`:50`)
- [x] ST6 Metrics: Total EMI after loan, Buffer coverage, Headline shortfall probability (`:53-55`)
- [x] ST7 Scenario table (7 columns) and **Alternative terms** table when not Resilient (`:59-62`)

## 8. Model Comparison (`pages/7_Model_Comparison.py`)
_Evidence: after/screens/model_comparison.png (bar chart now Plotly)._
- [x] MC1 Intro: only the decision tree decides (`:13`)
- [x] MC2 Button **Run comparison** / **Re-run comparison** → spinner → `benchmark.run()` → rerun (`:18-22`)
- [x] MC3 Info "No benchmark yet …" (`:25`)
- [x] MC4 Test-set results table + bar chart (accuracy, F1, ROC AUC) (`:31-34`)
- [x] MC5 Metric **Accuracy given up for explainability** (`:37`)
- [x] MC6 "Why the decision tree decides" bullet list (`:41-42`)

## 9. Demo flows (each must show the same decision, confidence, reason, fired rules and audit id)
_Evidence: after/screens/demo_*.png vs baseline/screens/demo_*.png (same seeded DB: same decision, confidence, reason, audit ID); calls/diff.md demo_*; ui_checks.md flag-off rows._
- [x] D1 `hard_reject` → Rejected · RULE · R01 · model not consulted
- [x] D2 `auto_approve` → Approved · MODEL
- [x] D3 `auto_reject` → Rejected · MODEL
- [x] D4 `soft_review` → Human Review · RULE · S01
- [x] D5 `low_confidence` → Human Review · MODEL
- [x] D6 `lock` → Human Review · RULE · "Lock (FR-10)"
- [x] D7 `malformed` → Rejected · RULE · invalid input (Age, Monthly_Income)
- [x] D8 Max amount possible (FOIR rejection via Raw JSON) → "Can be approved up to ₹…"
- [x] D9 Max amount not possible (`auto_reject`) → "No lower amount can be approved"
- [x] D10 Feature flag off → no max-amount button on any Rejected screen

## 10. Not part of the running UI
- `app/counterfactual_section.py` is an unused snippet (imports `cognilend.explain.counterfactual`, which does not exist); no page imports it. Left untouched.
