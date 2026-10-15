-- CogniLend audit queries. Standard SQL that runs on SQLite (dev) and PostgreSQL.
-- Named parameters (:applicant_id, :loan_id, :batch_id, :applications_in) are bound by the client
-- (SQLAlchemy text(), psql \set, or replace by hand). tests/test_db.py executes every query below.

-- Q1. All decisions for an applicant, oldest first (model/rule decisions and officer decisions).
SELECT d.decision_id, d.loan_id, d.source, d.outcome, d.confidence, d.reason,
       d.policy_version, d.model_version, d.audit_seq, d.created_at
FROM decisions d
JOIN loans l ON l.loan_id = d.loan_id
WHERE l.applicant_id = :applicant_id
ORDER BY d.created_at, d.decision_id;

-- Q2. All rule-based rejections, by rule (how often each HARD rule caused a rejection).
SELECT rr.rule_id, COUNT(*) AS rejections
FROM rule_results rr
JOIN decisions d ON d.decision_id = rr.decision_id
WHERE rr.fired = TRUE AND rr.rule_type = 'HARD' AND d.outcome = 'Rejected'
GROUP BY rr.rule_id
ORDER BY rejections DESC;

-- Q3. Decision-log coverage for a batch = decisions logged / applications made.
--     :applications_in is the number of applications submitted (from the caller / input file).
SELECT :batch_id AS batch_id,
       COUNT(*) AS logged,
       :applications_in AS made,
       1.0 * COUNT(*) / :applications_in AS coverage,
       SUM(CASE WHEN d.audit_seq IS NOT NULL THEN 1 ELSE 0 END) AS with_audit_event
FROM decisions d
WHERE d.batch_id = :batch_id;

-- Q4. Loans that have no logged decision at all (must be empty: FR-4).
SELECT l.loan_id
FROM loans l
WHERE NOT EXISTS (SELECT 1 FROM decisions d WHERE d.loan_id = l.loan_id);

-- Q5. Full trail of one loan: every decision with its audit-log entry and hash.
SELECT d.decision_id, d.source, d.outcome, d.reason, a.seq, a.event_type, a.hash, a.prev_hash, a.created_at
FROM decisions d
LEFT JOIN audit_log a ON a.seq = d.audit_seq
WHERE d.loan_id = :loan_id
ORDER BY a.seq;

-- Q6. Every rule evaluated for the decisions of one loan (fired, passed, exempt, not evaluated).
SELECT d.decision_id, rr.rule_id, rr.rule_type, rr.status, rr.value, rr.threshold
FROM rule_results rr
JOIN decisions d ON d.decision_id = rr.decision_id
WHERE d.loan_id = :loan_id
ORDER BY d.decision_id, rr.rule_id;

-- Q7. Outcome split by decision source (RULE / MODEL / HUMAN).
SELECT d.source, d.outcome, COUNT(*) AS n
FROM decisions d
GROUP BY d.source, d.outcome
ORDER BY d.source, d.outcome;

-- Q8. Open human-review queue, oldest first.
SELECT r.review_id, r.loan_id, r.reason, r.created_at
FROM review_queue r
WHERE r.status = 'OPEN'
ORDER BY r.created_at, r.review_id;

-- Q9. Active approval locks (FR-10): which loan holds each applicant / collateral.
SELECT k.lock_key, k.loan_id, k.acquired_at
FROM loan_locks k
WHERE k.released_at IS NULL
ORDER BY k.acquired_at;

-- Q10. Policy and model versions in force, with their file hashes.
SELECT 'policy' AS kind, version, sha256, activated_at AS at FROM policy_versions
UNION ALL
SELECT 'model' AS kind, version, sha256, created_at AS at FROM model_registry
ORDER BY kind, version;

-- Q11. Latest fairness audit: subgroups flagged below DI 0.80.
SELECT f.run_id, f.mode, f.group_name, f.subgroup, f.n, f.approval_rate, f.di_ratio, f.ci_low, f.ci_high
FROM fairness_reports f
WHERE f.flagged = TRUE
ORDER BY f.run_id, f.mode, f.group_name, f.subgroup;
