# CogniLend — Database Layer (G12: Rules + DBMS)

MySQL 8.0 implementation of Layer 1 (policy rules) and Layer 3 (DBMS / audit), plus the
database side of Layer 4 (fairness) and human-in-the-loop routing.

> ⚠️ **Status: PROTOTYPE / RAW TEST IMPLEMENTATION, not final.**
> This folder proves out the design (rules stored as data, append-only decision log,
> hash-chained audit, review queue, fairness runs) and its edge-case tests. It is **not yet
> wired to the rest of the repo**, and some parts will be rebuilt during integration:
>
> - **Dataset mismatch.** The schema and `07_import_dataset.sql` were written for Kaggle
>   `Loan_Default.csv` (`dtir1`, `LTV`, `Credit_Worthiness`, …). The team's pipeline in
>   `preprocessing/` and `model_training/` uses `loan_applications_raw.csv` (CIBIL, FOIR,
>   employment type, co-applicant income, existing EMI, collateral, …). The applicant and
>   loan columns, the import script and `v_model_features` must be re-aligned to that dataset.
> - **Two rule sets.** `model_training/loan_engine.py` has its own rules R1–R7 (FOIR slabs, RBI LTV
>   slabs, experience by employment type). This folder seeds a different R01–R10. There should be
>   **one** source of truth (see "Integration plan" below).
> - Paths, user passwords (`ChangeMe_*`) and thresholds here are placeholders for local testing.
>
> The final database will be built with the agreed stack (MySQL/PostgreSQL + a Python
> data-access layer) during the integration phase, using this prototype as the reference.

## Integration plan (draft, to be agreed with G10 and G15)

**Principle:** Python owns *computation* (cleaning, features, the model). The database owns
*policy thresholds, state and the audit trail*. Each fact is computed once, in one place.

```
UI (Streamlit/Flask, G15)
  └─► cognilend/pipeline.py  decide(application)          ← single entry point
        1. db.submit(payload)            → sp_submit_application   (validate + immutable snapshot)
        2. F = engine.featurize(payload) → loan_engine.clean/Imputer/build_features (G10 code, unchanged)
        3. db.run_rules(app_id, facts=F) → sp_run_rule_layer       (thresholds read from policy_rule)
              HARD fail → RULE_REJECTED, stop
        4. p, path = model.predict(F)    → sp_record_prediction    (or sp_record_model_failure)
              low confidence / soft flag → review_queue
        5. return decision + reasons + audit id
  Fairness (G15): sp_run_fairness on a schedule / from a dashboard
```

Steps:

1. **One rule catalogue.** Move `POLICY` + `RULE_TEXT` from `loan_engine.py` into `policy_rule`
   rows (rule set v2.0): `R1_MIN_AGE`, `R2_MAX_MATURITY_AGE`, `R3_MIN_CIBIL`, `R4_FOIR`, `R5_LTV`,
   `R6_MIN_INCOME`, `R7_MIN_EXPERIENCE`, plus the DB-only ones worth keeping (blacklist,
   loan stacking, re-apply abuse). Slab rules (FOIR, LTV, maturity age by employment type) become
   either derived `*_limit` facts or a `rule_param` table.
2. **Facts come from Python.** Change `sp_run_rule_layer` to take a `facts JSON` argument built by
   `build_features()` (`foir`, `foir_limit`, `ltv`, `ltv_cap`, `age_at_maturity`, …) instead of
   re-deriving them in SQL. That way the model and the rules see identical numbers.
   `loan_engine.evaluate_rules()` is kept only as an offline/training helper that reads the same
   thresholds from the DB (or from an exported JSON).
3. **Re-align the schema** to the real dataset columns (employment type, work experience,
   co-applicant income, existing EMI, CIBIL incl. `-1` = new-to-credit, collateral value,
   property area, marital status) and rewrite `07_import_dataset.sql` for `loan_applications_raw.csv`.
4. **`db.py` data-access layer** (one module, used by everyone): `submit`, `run_rules`,
   `record_prediction`, `record_failure`, `claim_review`, `resolve_review`, `run_fairness`, with
   the outbox fallback from §7. No other code writes SQL.
5. **Register the model.** After `train.py`, insert into `model_version` with the SHA-256 of the
   saved model file and `sp_activate_model`.
6. **Map decision thresholds.** `DECISION['approve_at'/'reject_below']` in `loan_engine.py`
   becomes `model_version.confidence_threshold` (or two columns), so the routing rule is stored with
   the model that used it.
7. **End-to-end test**: run `model_training/test_scenarios.py` through `pipeline.decide()` and check
   every row lands in `decision` with a source and timestamp (KPI: audit completeness = 100 %).

---

## 1. How the whole system works (end to end)

```
Applicant (Streamlit/Flask form)
   │  JSON payload + idempotency key
   ▼
sp_submit_application ──invalid──► INVALID + every problem listed (nothing stored, attempt audited)
   │ CREATED  (inputs frozen as an immutable snapshot)
   ▼
LAYER 1  sp_run_rule_layer   (policy rules stored as DATA, versioned)
   │  derive facts (age, age at maturity, LTV, loan/income, blacklist, open apps, recent rejections)
   │  evaluate EVERY active rule → rule_evaluation rows
   ├── any HARD rule fails ──► RULE_REJECTED  (decision source = RULE, all reasons listed) ── END
   ├── SOFT rule fails / data missing ──► PENDING_MODEL + soft_referral = TRUE
   └── all pass ──► PENDING_MODEL
   ▼
LAYER 2  Python: read v_model_features → Decision Tree → probability + tree path
   │  sp_record_prediction   (or sp_record_model_failure if the model crashes)
   ├── confidence ≥ threshold AND no soft flag ──► AUTO_APPROVED / AUTO_REJECTED ── END
   └── low confidence OR soft flag OR model failure ──► PENDING_REVIEW + review_queue
   ▼
HUMAN   sp_claim_review → sp_resolve_review (written justification, override tracked)
   └──► OFFICER_APPROVED / OFFICER_REJECTED ── END
   ▼
LAYER 3  (runs throughout) decision log (append-only) + hash-chained audit_log
LAYER 4  sp_run_fairness → disparate-impact ratio per subgroup → flags into audit_log
```

**Guarantees that are enforced by the database itself** (they hold even if someone runs a
manual `UPDATE` in Workbench):

| Guarantee | How it is enforced |
|---|---|
| A hard rule can never be overridden | No transition out of `RULE_REJECTED` in `status_transition`; trigger `trg_app_bu` rejects illegal transitions |
| Every decision is logged | Status only changes via procedures that insert a `decision` row in the same transaction; `v_kpi_audit_completeness` |
| History cannot be edited | `decision`, `rule_evaluation`, `model_prediction`, `audit_log` are append-only (triggers) |
| Tampering is detectable | `audit_log` is a SHA-256 hash chain; `v_audit_chain_check` must return 0 rows |
| Decisions are reproducible | Each decision stores `rule_set_id` + `model_id` (with artifact SHA-256 and seed); used rule sets/models are frozen |
| Inputs cannot be changed after submission | `trg_app_bu` blocks edits to snapshot columns |
| Only one active rule set / model | Generated column + `UNIQUE` (MySQL's partial-unique-index trick) |
| The model never sees protected attributes | `v_model_features` excludes gender/age/dependents; the ML DB user can only read that view |

---

## 2. Files and run order

| # | File | What it does |
|---|---|---|
| 01 | `01_schema.sql` | Creates DB `cognilend`: 18 tables, keys, CHECK constraints (**drops the DB first!**) |
| 02 | `02_seed_reference.sql` | Status machine, users, rule set v1 (10 rules), placeholder model, sample blacklist entry |
| 03 | `03_triggers.sql` | Immutability, state machine, audit hash chain, version freezing |
| 04 | `04_procedures.sql` | The pipeline API (submit → rules → prediction → review → fairness) |
| 05 | `05_views.sql` | KPI views, explanation view, ML feature view, tamper check |
| 06 | `06_security_and_jobs.sql` | Least-privilege roles/users, hourly SLA escalation event |
| 07 | `07_import_dataset.sql` | Loads Kaggle `Loan_Default.csv` via staging with row-level error capture |
| 08 | `08_edge_case_tests.sql` | 50+ automated assertions = your "Minimum Engineering Evidence" |

---

## 3. Step-by-step in MySQL Workbench

1. **Install** MySQL Server 8.0.16+ and Workbench. Check: `SELECT VERSION();`
2. Open a connection as `root`.
3. Workbench → *Edit → Preferences → SQL Editor*: **untick "Safe Updates"** (it blocks some
   statements in the scripts), then reconnect.
4. For each file `01` → `06`: *File → Open SQL Script*, then **Execute All (⚡ lightning icon,
   Ctrl+Shift+Enter)**. Do not use "execute current statement" — the `DELIMITER $$` blocks
   need the whole script.
5. Run `08_edge_case_tests.sql`. The last two result tabs show every test and the
   pass/fail totals. All should say `PASS`.
6. Dataset: put `Loan_Default.csv` in `CogniLend/data/`, follow STEP A in `07_import_dataset.sql`
   (enable `local_infile` + `OPT_LOCAL_INFILE=1`), fix the path, execute. Read every result of STEP D.
7. **ER diagram for your report:** *Database → Reverse Engineer* → select `cognilend` → Workbench
   draws the EER diagram. Export as PNG (*File → Export → Export as PNG*).
8. Try the pipeline by hand:

```sql
USE cognilend;
CALL sp_submit_application('demo-1',
  JSON_OBJECT('id_hash', SHA2('ABCDE1234F',256), 'full_name','Asha Patil',
              'date_of_birth','1995-04-12','gender','F','income_monthly',65000,
              'credit_score',742,'dtir',32.5,'loan_amount',1500000,'term_months',240,
              'property_value',2500000,'occupancy_type','pr','credit_type','CIB'),
  'LIVE', @id, @outcome, @msg);
SELECT @id, @outcome, @msg;

CALL sp_run_rule_layer(@id, @outcome, @msg);           SELECT @outcome, @msg;
CALL sp_record_prediction(@id, 1, 0.91,
     JSON_ARRAY('credit_score > 700.5','dtir <= 38.5'), JSON_ARRAY('good score'), 12,
     @outcome, @msg);                                   SELECT @outcome, @msg;

SELECT * FROM v_decision_explanation WHERE application_id = @id;
SELECT * FROM audit_log ORDER BY audit_id DESC LIMIT 5;
```

> Re-running `01_schema.sql` **wipes everything** (it starts with `DROP DATABASE`). Never run
> it against data you want to keep.

---

## 4. Edge cases handled (and where)

### Input and data quality
| Scenario | Behaviour | Where |
|---|---|---|
| Malformed / missing required fields | `INVALID` with **all** problems listed, nothing stored, attempt written to audit_log as `BLOCKED` | `sp_submit_application` (T08) |
| Impossible date (`2001-02-30`), future DOB, age > 120 | INVALID | same |
| Text in a number field (`"12%"`, `"abc"`), 20-digit numbers | INVALID, no overflow crash | `fn_jnum` (T08f) |
| Unknown category (`occupancy_type = "villa"`) | INVALID (the model could not encode it) | whitelist checks |
| Gender given as `M`/`male`/`Female`/blank | Normalised; blank → `Not_Disclosed` (never rejected for it) | submit |
| No credit history (thin-file / NTC applicant) | Accepted; rule marks `MISSING_REFER` → human review | R05 `on_missing=REFER` (T07) |
| Unsecured loan (no property) | LTV rule skipped, not failed | R07 `on_missing=SKIP` |
| Income = 0 | Hard reject R04 (no division-by-zero anywhere: LTV/LTI use `IF(x>0, …)`) | rules |
| Dataset row with bad values | Row goes to `import_error` with a code; the other 148k load | `sp_import_staging` |
| Windows line endings in CSV | `\r` stripped from last column | import |

### Process and concurrency
| Scenario | Behaviour | Where |
|---|---|---|
| Double-click / network retry | Same idempotency key → `DUPLICATE`, returns original id | UNIQUE + handler (T09) |
| Two workers process same application | `SELECT … FOR UPDATE` row lock; second sees `ALREADY_PROCESSED` | every procedure |
| Two officers resolve the same review | Claim locks it to one officer; second gets `INVALID` | `sp_claim_review` (T11b) |
| Resolve twice / flip a decision | Blocked: review already resolved | T11g |
| Model crashes, times out, returns NaN | `SYSTEM_FALLBACK` → human, priority 1 | `sp_record_model_failure` (T10) |
| Model returns prediction for rule-rejected app | Ignored (`ALREADY_PROCESSED`) | T02b |
| Stale model version used after a switch | `INVALID: not the active version` | `sp_record_prediction` |
| No active rule set | Refuses to decide (fail closed) | `sp_run_rule_layer` |
| Python crashes between layers | Application stays in RECEIVED/PENDING_MODEL, visible in `v_stuck_applications`, safe to re-run | views |
| Review not handled in time | Hourly event escalates to priority 1; never dropped | `ev_escalate_reviews` (T18) |
| Applicant withdraws | Allowed only before a final decision | `sp_withdraw_application` (T16) |

### Fraud, abuse and compliance
| Scenario | Behaviour | Where |
|---|---|---|
| Blacklisted identity (with expiry) | Hard reject | R01 (T03) |
| Same PAN, different date of birth | Blocked as identity mismatch, audited | submit (T14) |
| Several applications at once (loan stacking) | Soft rule → human | R09 (T15) |
| Re-applying with tweaked numbers to "probe" the model | ≥3 rejections in 30 days → human | R10 |
| Someone edits a threshold after decisions were made | Blocked; must clone into a new version | `trg_rule_bu` (T13) |
| Someone re-tunes a model already in use | Blocked | `trg_model_bu` (T17b) |
| Officer edits DB directly to approve | State-machine trigger blocks it | T02c |
| Someone deletes/edits an audit row | Blocked by trigger; if triggers are dropped, hash chain breaks | T12, `v_audit_chain_check` |
| Rejection must state reasons | All failed rules listed in `reason_text` | T04 |
| Officer bias | `v_officer_overrides` shows each officer's override rate and direction | views |
| Raw PAN/Aadhaar leak | Only a SHA-256 hash is stored | `applicant.id_hash` |

### Fairness
| Scenario | Behaviour |
|---|---|
| Group below the 0.80 ratio | `FLAGGED` + alert in audit_log (T19a) |
| Tiny subgroup (e.g. 3 people) | `INSUFFICIENT_SAMPLE`, not a false alarm (T19c) |
| No approvals at all in window | `NO_APPROVALS_OVERALL` (no division by zero) |
| Empty time window | Run recorded, message "No decisions in window" |
| Model bias vs whole-system bias | `MODEL_ONLY` scope (raw predictions) vs `ALL_FINAL` (after rules + humans) |

---

## 5. Gaps in the current synopsis — fix these before review

1. **Label meaning (important).** Your dataset matches Kaggle *Loan_Default.csv*
   (148,670 rows, `dtir1`, `LTV`, `Credit_Worthiness` …). In that dataset **`Status = 1` means
   the loan defaulted** (~25 %), not "approved". The synopsis says 1 = Approved. Run STEP D-2
   in `07_import_dataset.sql` and check the source. If confirmed, reframe Layer 2 as *"predict
   default risk; approve when predicted risk is low"*. This is also more defensible in a viva.
2. **Selection bias.** A default dataset only contains loans that *were already approved*.
   The model never saw people the bank turned away. Mention this as a limitation ("reject
   inference" is the standard term).
3. **Target leakage.** `rate_of_interest`, `Interest_rate_spread` and `Upfront_charges` are
   reportedly missing almost only for defaulted loans. The model would learn "missing ⇒
   default". STEP D-3 checks it. Drop those columns and do not impute them.
4. **80 % accuracy is below a trivial baseline.** With 75/25 classes, predicting the majority
   class every time already scores 75 %. Report **balanced accuracy, minority-class recall,
   F1 and ROC-AUC** alongside accuracy.
5. **A depth-4, ≤15-node tree has at most 8 leaves.** So it can only produce about 8 distinct
   probabilities, which makes confidence routing coarse. Using a *separate* Naive Bayes model
   for confidence can disagree with the tree's own label. It is better to calibrate the tree's
   own probabilities (`CalibratedClassifierCV`) and choose the threshold from a
   coverage-vs-accuracy curve.
6. **SMOTE on categorical columns** creates impossible values (e.g. "loan_type = 1.4").
   Use **SMOTENC**, or `class_weight='balanced'`. Apply it only inside the training fold.
7. **Dependents are not in this dataset.** The fairness layer can't measure them on historical
   data, so say so or drop them. Age is only a band, and `<25` cannot confirm a minimum age of 21.
   Gender includes `Joint` and `Sex Not Available`.
8. **Removing gender from features does not remove bias.** Proxies such as Region, loan type
   and income can encode it. That is why Layer 4 audits outcomes, and why it matters.
9. **Rules can discriminate too.** The age-at-maturity rule treats people differently by age.
   Document the business justification for every hard rule.
10. **"DB write failure → decision still returned"** conflicts with "100 % decisions logged".
    Resolution: write the decision to a local *outbox* file first, show the applicant a
    *provisional* result, and replay the outbox into MySQL with the same idempotency key
    (safe to replay). See §7.
11. **Income units.** Confirm that dataset `income` is monthly. The column is named
    `income_monthly`, and the loan-to-income rule depends on it.

---

## 6. Improvements beyond the synopsis (already implemented)

- Rules stored as **data**, not code. The rule set is versioned, so changing policy never
  rewrites history.
- **HARD vs SOFT** rules, plus an explicit **missing-data policy** per rule (FAIL / REFER / SKIP).
- **All** failed reasons are recorded, which an adverse-action notice needs.
- Immutable **input snapshot**, so a decision always shows exactly the data it used.
- **Tamper-evident hash-chained audit log.**
- **Officer override monitoring.** Human-in-the-loop can be biased too.
- **Fraud and abuse signals:** identity mismatch, loan stacking, model probing, and a blacklist
  with expiry.
- **Least-privilege DB roles.** The app can only call procedures, and ML only reads the
  de-identified view.
- **SLA escalation** for the review queue.
- **Idempotent bulk import** with a per-row error log and data-quality checks.

Further ideas if time permits: data retention/anonymisation (DPDP Act 2023), a reason-code
table (standard codes instead of free text), a Streamlit officer dashboard on
`v_review_backlog`, a daily fairness run via EVENT, and publishing the audit chain head daily
(e.g. committed to Git) so even a DB admin cannot silently rebuild the chain.

---

## 7. Integration contract for G10 / G15 (Python)

```python
import json, uuid, hashlib, mysql.connector

conn = mysql.connector.connect(host="localhost", user="cl_app",
                               password="...", database="cognilend", autocommit=True)
cur = conn.cursor()

def call(proc, *args, n_out):
    res = cur.callproc(proc, (*args, *([None] * n_out)))
    return res[-n_out:]

pan_hash = hashlib.sha256((PEPPER + pan.upper()).encode()).hexdigest()   # never send raw PAN
key = str(uuid.uuid4())                        # generate ONCE per form submit, reuse on retry
app_id, outcome, msg = call("sp_submit_application", key, json.dumps(payload), "LIVE", n_out=3)

outcome, msg = call("sp_run_rule_layer", app_id, n_out=2)
if outcome in ("PASS", "PASS_REFER"):
    try:
        cur.execute("SELECT * FROM v_model_features WHERE application_id=%s", (app_id,))
        p, path, reasons = predict(cur.fetchone())      # G10's code
        outcome, msg = call("sp_record_prediction", app_id, MODEL_ID, float(p),
                            json.dumps(path), json.dumps(reasons), latency_ms, n_out=2)
    except Exception as e:
        outcome, msg = call("sp_record_model_failure", app_id, str(e)[:500], n_out=2)
```

**Getting the tree path** (for `decision_path`), sklearn:

```python
node_ids = clf.decision_path(X_row).indices
t = clf.tree_
path = [f"{feat_names[t.feature[n]]} {'<=' if X_row[0, t.feature[n]] <= t.threshold[n] else '>'} {t.threshold[n]:.2f}"
        for n in node_ids if t.feature[n] >= 0]
```

**Handling DB outages (outbox pattern):** wrap each `call()`. On `mysql.connector.Error`,
append `{"proc":…, "args":…, "ts":…}` to `outbox.jsonl` (flush + `os.fsync`), tell the user
"provisional, reference <key>", and have a replay script re-send the file later. Replays are
safe because of the idempotency key and the `ALREADY_PROCESSED` checks.

**Registering G10's real model:**

```sql
INSERT INTO model_version (model_name, algorithm, version_label, artifact_sha256, random_seed,
       max_depth, node_count, train_accuracy, val_accuracy, confidence_threshold, feature_list, trained_at)
VALUES ('cognilend_dt','DecisionTree','v1.0','<sha256 of model.pkl>',42,4,15,0.83,0.81,0.75,
        JSON_ARRAY('income_monthly','credit_score', ...), UTC_TIMESTAMP(3));
CALL sp_activate_model(LAST_INSERT_ID());
```

**Fairness (G15):**

```sql
CALL sp_run_fairness('gender', 'ALL_FINAL', '2026-01-01', '2027-01-01', 30, 0.800, 5, @run, @msg);
SELECT @msg;  SELECT * FROM fairness_result WHERE run_id = @run;
```

---

## 8. Tuning rules on historical data

A hard rule that rejects many borrowers who repaid is a bad rule. After the import:

```sql
-- run Layer 1 on N historical applications
CALL sp_run_rules_batch('HISTORICAL_IMPORT', 5000, @done);
SELECT * FROM v_rule_trigger_stats;
-- how many GOOD borrowers (did not default) did each hard rule reject?
SELECT pr.rule_code, SUM(a.dataset_status = 0) AS good_borrowers_rejected, COUNT(*) AS rejected
  FROM rule_evaluation re
  JOIN policy_rule pr ON pr.rule_id = re.rule_id AND pr.severity = 'HARD'
  JOIN loan_application a ON a.application_id = re.application_id
 WHERE re.outcome = 'FAIL'
 GROUP BY pr.rule_code;
```

Adjust thresholds with `sp_clone_rule_set` → `UPDATE policy_rule …` on the new set →
`sp_activate_rule_set`. Report the before/after numbers. That is strong evidence in a review.

**Known first fix — R03 (age at maturity ≤ 65):** most loans in this dataset are 360 months
(30 years). With age bands, anyone in `45-54` or above gets 45 + 30 = 75 > 65 and is
hard-rejected. On a sample, R03 alone rejected most historical applications. Options: raise the
limit to 70–75 (common for Indian home loans), make it SOFT, or drop it for the historical
evaluation. Whichever you pick, write down why.

---

## 9. Roadmap for G12 (4 members, ~10 weeks)

**Roles**

| Member | Owns | Deliverables |
|---|---|---|
| **M1 — Schema & data** | 01, 07 | ER diagram, normalisation note (3NF + why snapshot columns are deliberate), dataset import, data-quality report |
| **M2 — Rule engine** | 02, rule parts of 04 | Rule catalogue with a business justification per rule, threshold tuning on history (§8), rule-versioning demo |
| **M3 — Workflow & integration** | 04 (review/model procs), Python `db.py`, outbox | Integration with G10's model and G15's UI, fault-injection demo |
| **M4 — Audit, security & QA** | 03, 05, 06, 08 | KPI dashboard queries, tamper demo, role/permission demo, test report |

Everyone should understand the whole flow in §1; any member can be asked about any part in a viva.

**Timeline**

| Week | Milestone | Done when |
|---|---|---|
| 1 | Everyone installs MySQL 8 + Workbench, runs 01–06 and 08 | All tests PASS on every laptop |
| 2 | Import real dataset (07); label/leakage/units checks sent to G10 | `v_import_quality` reviewed, findings documented |
| 3 | EER diagram + data dictionary; agree the integration contract (§7) with G10/G15 | Signed-off JSON payload + procedure list |
| 4 | Rule tuning on historical data (§8); v1.1 rule set if needed | Before/after table of rejection rates |
| 5 | Python `db.py` wrapper + outbox/replay; stub model end-to-end | Form → decision → explanation works with the placeholder model |
| 6 | Plug in G10's real model (`sp_activate_model`); tree path in `decision_path` | Real predictions logged with SHA-256 of model file |
| 7 | Officer review screen (with G15) on `v_review_backlog` + fairness runs | Review → override → audit visible in UI |
| 8 | Fault injection: stop MySQL mid-run, kill Python between layers, two Workbench tabs resolving the same review | Evidence screenshots for every row of the synopsis's "Minimum Engineering Evidence" table |
| 9 | Performance: time the 148k import, `EXPLAIN` key queries, add indexes if needed | Numbers in report |
| 10 | Report chapter, demo script, viva prep (§5, §9) | Rehearsed 10-minute demo |

**Concurrency test (week 8, by hand):** open two Workbench tabs (two separate connections).
1. Tab 1: `START TRANSACTION; SELECT * FROM review_queue WHERE review_id = <id> FOR UPDATE;`
   (this simulates officer A mid-claim; don't commit yet)
2. Tab 2: `CALL sp_claim_review(<id>, 4, @o, @m);`. This **waits** on the row lock.
3. Tab 1: `UPDATE review_queue SET status='IN_PROGRESS', assigned_to=3 WHERE review_id=<id>; COMMIT;`
4. Tab 2 unblocks. `SELECT @o, @m;` → `INVALID / Already claimed by another officer`.

(Calling a procedure inside your own `START TRANSACTION` does not hold its lock, because
each procedure's own `START TRANSACTION` implicitly commits the outer one.)

**Git hygiene:** commit only the `.sql`, `.py` and `.md` files. Never commit the CSV (it's
large), real passwords, or `outbox.jsonl`.

---

## 10. Known limitations (be upfront about these in the viva)

- A MySQL `root` user can still drop triggers and rebuild the hash chain. Publishing the
  chain head externally closes that gap.
- The rule engine does single-pass fact derivation plus rule evaluation. That is
  forward-chaining with one inference level, which is enough for eligibility policy but not a
  general inference engine.
- `fn_jnum` accepts plain decimals only (`65000`, `32.5`), not `6.5e4` or `65,000`. The
  frontend should send clean numbers.
- Timestamps are UTC. Convert to IST only for display.
