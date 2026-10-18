# Step 07: Persistence and audit

Date: 2026-10-15.

## What was built

- **`db/models.py`** defines 10 tables with SQLAlchemy 2.x, using portable types (SQLite in dev, PostgreSQL-compatible):

  | Table | Contents |
  |---|---|
  | `applicants` | applicant id, name hash, date of birth, age, gender, marital status, dependents, employment type |
  | `loans` | loan id, applicant id, collateral id, type, amount, tenure, status, `application_json` |
  | `decisions` | decision id, loan id, batch id, source RULE/MODEL/HUMAN, outcome, confidence, reason, fired rules, `tree_path_json`, model prediction, model version, policy version, audit seq |
  | `rule_results` | every rule evaluated per decision: fired / passed / exempt / not applicable / not evaluated, with value and threshold |
  | `policy_versions` | YAML text and SHA-256 |
  | `model_registry` | artefact path, SHA-256, metrics |
  | `audit_log` | the hash chain |
  | `review_queue` | cases waiting for, or closed by, an officer |
  | `fairness_reports` | per-subgroup DI results; the column is called `group_name` because `group` is an SQL keyword |
  | `loan_locks` | active approval locks |

  `audit_log` is append-only, enforced three ways: SQLite `BEFORE UPDATE/DELETE` triggers, an equivalent PostgreSQL plpgsql trigger (DDL included), and an ORM guard that raises `AppendOnlyError`.
- **`db/audit.py`**: `hash = sha256(prev_hash + canonical_json({seq, event_type, created_at, payload}))`, chained from a GENESIS hash of 64 zeros. The whole record is hashed, not just the payload, so a forged event type or timestamp is also caught. `verify_chain()` returns `OK` or the first broken seq with the reason (sequence gap, back-link mismatch or hash mismatch).
- **`db/lock.py`** (FR-10, G1): `acquire_for_approval()` runs inside the transaction that stores the approval.
  - Lock keys are `applicant:<id>` and `collateral:<id>`. `lock_key` is the primary key.
  - On SQLite every transaction starts with `BEGIN IMMEDIATE`. On PostgreSQL it uses `SELECT ... FOR UPDATE` plus the primary-key unique constraint.
  - If another loan holds an active lock, the approval is downgraded to **Human Review** with the reason given.
  - `release()` frees a loan's locks.
- **`db/repository.py`**:
  - `record_decision()` writes applicant, loan, the lock check, decision, rule results, review-queue entry and audit event in **one transaction**.
  - `register_versions()` writes the policy and model registry rows and their audit events.
  - `complete_review()` records an officer's decision.
  - `FallbackLog` is a JSONL file of failed writes, with `replay()`.
  - SQLite runs in WAL mode with a 60 s busy timeout.
- **DB failure handling** (in the pipeline): if `record_decision` raises, the decision is still returned with `persisted=False` and a `fallback_id`, and the full record goes to `artifacts/fallback/decisions_fallback.jsonl`. An **Approved** decision becomes **Human Review**, because without the DB its lock cannot be verified.
- **`docs/audit_queries.sql`** has 11 queries. They cover: all decisions for an applicant, rule rejections by rule, coverage = logged / made, loans without a decision, a loan's full trail with hashes, the rule results of a loan, the split by source, the open review queue, active locks, versions in force, and flagged fairness rows.

## Commands

```
python -m pytest tests/test_db.py -s     -> 19 passed
python -m pytest                         -> 260 passed in 86.69s
```

## Acceptance checks

| Check | Evidence |
|---|---|
| Tampering with one audit row is reported at that row | `test_tampering_one_row_is_reported_at_that_row` with payload / event_type / created_at each edited on seq 4 → `first_broken_seq == 4`. Also: rewriting a hash is caught at the next link (`..._breaks_the_next_link`), a deleted row is reported as a gap, and triggers plus the ORM guard block UPDATE and DELETE |
| 50 concurrent threads approving the same collateral → exactly 1 approval | `test_50_concurrent_approvals_same_collateral_exactly_one`: 1 Approved, 49 Human Review, all persisted, exactly 1 loan with APPROVED status in the DB, chain OK |
| Lock latency recorded | `artifacts/reports/lock_latency.json`. Two runs today gave p50 **43 ms / 202 ms**, p95 **846 ms / 1,395 ms**, max about 1.6 s. This is time inside `record_decision`, including the wait for SQLite's single write lock: 50 writers queue behind it, so the tail grows with contention. Uncontended single decisions take about 30–45 ms. |
| Fault injection: DB raises → no crash, decision returned, fallback written, nothing lost | `test_db_failure_returns_decision_and_writes_fallback`: 7 applications, including a `None` input. All 7 get a decision; 7 fallback lines are written with matching ids; the approval is downgraded; replay into a working DB stores all 7 and the chain verifies. `test_replay_keeps_failures_pending` covers a replay that fails again. |
| SQL examples are valid | `test_every_audit_query_runs` executes all 11 queries and checks Q1–Q5 results |

Also tested: human review completion, which creates a HUMAN decision with its own `human_review_completed` audit event, closes the queue entry and sets the loan status; and that an officer cannot approve a second loan on locked collateral.

## Open issues

- The lock-latency tail comes from SQLite serialising every writer. PostgreSQL row locks would serialise only conflicting keys. If production latency matters, measure again on PostgreSQL.
- `name_hash` and `dob` exist in the schema but stay empty, because the dataset has no names or dates of birth (age is stored instead).
- The PostgreSQL trigger DDL is included but untested, since no PostgreSQL server is available here.
