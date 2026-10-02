-- =====================================================================
-- CogniLend :: 05_views.sql
-- Reporting views — one per KPI / engineering-evidence item in the
-- synopsis, plus the ML feature view and the audit-chain verifier.
-- =====================================================================
USE cognilend;

-- ---------------------------------------------------------------------
-- Features for G10's model. Protected attributes (gender, age, dependents)
-- are deliberately ABSENT: the model cannot use what it cannot see.
-- They stay in loan_application for Layer-4 fairness auditing only.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_model_features AS
SELECT application_id, source,
       income_monthly, credit_score, credit_type, co_applicant_credit_type,
       credit_worthiness, dtir, loan_amount, term_months, loan_type, loan_purpose,
       property_value, ltv, occupancy_type,
       dataset_status                               -- label (historical rows only)
  FROM loan_application;

-- ---------------------------------------------------------------------
-- One row per application: the full human-readable explanation
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_decision_explanation AS
SELECT a.application_id, a.application_ref, a.status, a.submitted_at,
       d.outcome            AS final_outcome,
       d.decision_source,
       d.confidence,
       d.reason_text,
       u.username           AS decided_by,
       d.decided_at,
       d.is_override,
       (SELECT GROUP_CONCAT(CONCAT(pr.rule_code, '=', re.outcome) ORDER BY pr.priority SEPARATOR ', ')
          FROM rule_evaluation re JOIN policy_rule pr ON pr.rule_id = re.rule_id
         WHERE re.application_id = a.application_id)                   AS rule_trace,
       mp.prob_approve, mp.decision_path, mp.top_reasons,
       rs.version_label     AS rule_set_version,
       mv.version_label     AS model_version
  FROM loan_application a
  LEFT JOIN decision d          ON d.decision_id = a.current_decision_id
  LEFT JOIN app_user u          ON u.user_id = d.decided_by
  LEFT JOIN model_prediction mp ON mp.prediction_id = d.prediction_id
  LEFT JOIN rule_set rs         ON rs.rule_set_id = d.rule_set_id
  LEFT JOIN model_version mv    ON mv.model_id = d.model_id;

-- ---------------------------------------------------------------------
-- KPI: Audit completeness — must be 100 %
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_kpi_audit_completeness AS
SELECT COUNT(*)                                                    AS decided_applications,
       SUM(a.current_decision_id IS NOT NULL)                      AS with_logged_decision,
       ROUND(100 * SUM(a.current_decision_id IS NOT NULL) / NULLIF(COUNT(*), 0), 2) AS coverage_pct,
       SUM(d.decided_at IS NULL OR d.decision_source IS NULL)      AS missing_source_or_time
  FROM loan_application a
  JOIN app_status s ON s.status_code = a.status
  LEFT JOIN decision d ON d.decision_id = a.current_decision_id
 WHERE (s.is_terminal AND a.status <> 'WITHDRAWN') OR a.status = 'PENDING_REVIEW';

-- ---------------------------------------------------------------------
-- KPI: Rule correctness / "rule vs model conflict" — must return 0 rows.
-- Any application with a failed HARD rule that ended up APPROVED, or
-- that the model was even consulted on, is a pipeline bug.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_kpi_rule_violations AS
SELECT a.application_id, a.status, d.outcome, d.decision_source
  FROM loan_application a
  LEFT JOIN decision d ON d.decision_id = a.current_decision_id
 WHERE EXISTS (SELECT 1 FROM rule_evaluation re JOIN policy_rule pr ON pr.rule_id = re.rule_id
                WHERE re.application_id = a.application_id
                  AND pr.severity = 'HARD' AND re.outcome IN ('FAIL','MISSING_FAIL'))
   AND (d.outcome = 'APPROVED'
        OR EXISTS (SELECT 1 FROM model_prediction mp WHERE mp.application_id = a.application_id));

-- ---------------------------------------------------------------------
-- KPI: Confidence routing — auto-decided vs human-review split
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_kpi_routing_split AS
SELECT mv.version_label AS model_version,
       COUNT(*) AS predictions,
       SUM(d.outcome IN ('APPROVED','REJECTED')) AS auto_decided,
       SUM(d.outcome = 'REFERRED')               AS sent_to_human,
       ROUND(100 * SUM(d.outcome IN ('APPROVED','REJECTED')) / COUNT(*), 2) AS auto_pct
  FROM model_prediction mp
  JOIN model_version mv ON mv.model_id = mp.model_id
  JOIN decision d ON d.prediction_id = mp.prediction_id AND d.decision_source = 'MODEL'
 GROUP BY mv.version_label;

-- ---------------------------------------------------------------------
-- Rule trigger stats — use to TUNE thresholds (a rule that rejects 40 %
-- of good historical borrowers is a bad rule)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_rule_trigger_stats AS
SELECT rs.version_label, pr.rule_code, pr.severity,
       COUNT(*)                            AS evaluated,
       SUM(re.outcome = 'PASS')            AS passed,
       SUM(re.outcome = 'FAIL')            AS failed,
       SUM(re.outcome LIKE 'MISSING%')     AS missing,
       SUM(re.outcome = 'SKIPPED')         AS skipped,
       ROUND(100 * SUM(re.outcome = 'FAIL') / COUNT(*), 2) AS fail_pct
  FROM rule_evaluation re
  JOIN policy_rule pr ON pr.rule_id = re.rule_id
  JOIN rule_set rs    ON rs.rule_set_id = pr.rule_set_id
 GROUP BY rs.version_label, pr.rule_code, pr.severity, pr.priority
 ORDER BY rs.version_label, pr.priority;

-- ---------------------------------------------------------------------
-- Human review backlog — nothing is ever silently dropped
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_review_backlog AS
SELECT r.review_id, r.application_id, r.reason, r.priority, r.status,
       u.username AS assigned_to, r.created_at, r.sla_due_at,
       TIMESTAMPDIFF(HOUR, r.created_at, UTC_TIMESTAMP(3)) AS age_hours,
       (r.sla_due_at < UTC_TIMESTAMP(3)) AS is_overdue
  FROM review_queue r
  LEFT JOIN app_user u ON u.user_id = r.assigned_to
 WHERE r.status <> 'RESOLVED'
 ORDER BY r.priority, r.sla_due_at;

-- ---------------------------------------------------------------------
-- Officer override monitoring — humans can be biased too
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_officer_overrides AS
SELECT u.username,
       COUNT(*)                                    AS reviews_resolved,
       SUM(d.is_override)                          AS overrides,
       SUM(d.is_override AND d.outcome='APPROVED') AS overrides_to_approve,
       SUM(d.is_override AND d.outcome='REJECTED') AS overrides_to_reject,
       ROUND(100 * SUM(d.is_override) / COUNT(*), 2) AS override_pct
  FROM decision d JOIN app_user u ON u.user_id = d.decided_by
 WHERE d.decision_source = 'OFFICER'
 GROUP BY u.username;

-- ---------------------------------------------------------------------
-- Latest fairness result per attribute/scope
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_fairness_latest AS
SELECT fr.run_id, fr.attribute_name, fr.scope, fr.run_at, fr.reference_group,
       r.group_value, r.n_decided, r.n_approved, r.approval_rate, r.di_ratio, r.status
  FROM fairness_run fr
  JOIN fairness_result r ON r.run_id = fr.run_id
 WHERE fr.run_id = (SELECT MAX(f2.run_id) FROM fairness_run f2
                     WHERE f2.attribute_name = fr.attribute_name AND f2.scope = fr.scope);

-- ---------------------------------------------------------------------
-- Tamper check — must return 0 rows. A row appears if any audit entry
-- was edited, deleted, or inserted out of chain.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_audit_chain_check AS
SELECT audit_id, table_name, record_id,
       CASE WHEN recomputed <> row_hash THEN 'CONTENT_ALTERED' ELSE 'CHAIN_BROKEN' END AS problem
  FROM (SELECT a.*,
               LAG(row_hash) OVER (ORDER BY audit_id) AS expected_prev,
               SHA2(CONCAT_WS('|', prev_hash, table_name, record_id, action,
                              COALESCE(CAST(payload AS CHAR), ''),
                              DATE_FORMAT(created_at, '%Y-%m-%d %H:%i:%s.%f')), 256) AS recomputed
          FROM audit_log a) x
 WHERE recomputed <> row_hash
    OR prev_hash <> COALESCE(expected_prev, REPEAT('0', 64))
UNION ALL
-- newest rows deleted: the stored chain head no longer matches the last row
SELECT NULL, 'audit_chain_head', 1, 'TAIL_TRUNCATED'
  FROM audit_chain_head h
 WHERE h.last_hash <> COALESCE((SELECT row_hash FROM audit_log ORDER BY audit_id DESC LIMIT 1), REPEAT('0', 64));

-- ---------------------------------------------------------------------
-- Stuck applications — sitting in a non-terminal state too long
-- (e.g. Python crashed between rule layer and model layer)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_stuck_applications AS
SELECT a.application_id, a.status, a.status_updated_at,
       TIMESTAMPDIFF(MINUTE, a.status_updated_at, UTC_TIMESTAMP(3)) AS minutes_in_status
  FROM loan_application a
 WHERE a.status IN ('RECEIVED','PENDING_MODEL')
   AND a.status_updated_at < UTC_TIMESTAMP(3) - INTERVAL 15 MINUTE
   AND a.source <> 'HISTORICAL_IMPORT';

-- ---------------------------------------------------------------------
-- Import data-quality summary
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_import_quality AS
SELECT b.batch_id, b.file_name, b.rows_staged, b.rows_loaded, b.rows_rejected,
       e.error_code, COUNT(e.error_id) AS n
  FROM import_batch b
  LEFT JOIN import_error e ON e.batch_id = b.batch_id
 GROUP BY b.batch_id, b.file_name, b.rows_staged, b.rows_loaded, b.rows_rejected, e.error_code;
