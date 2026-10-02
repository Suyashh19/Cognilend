-- =====================================================================
-- CogniLend :: 08_edge_case_tests.sql
-- Automated evidence for the "Minimum Engineering Evidence" table.
-- Safe to re-run: every run uses fresh keys (@run prefix).
-- Results:  SELECT * FROM test_result WHERE run_tag = @run;
-- =====================================================================
USE cognilend;

CREATE TABLE IF NOT EXISTS test_result (
    test_id   INT AUTO_INCREMENT PRIMARY KEY,
    run_tag   VARCHAR(20)  NOT NULL,
    test_name VARCHAR(120) NOT NULL,
    passed    BOOLEAN      NOT NULL,
    detail    VARCHAR(1000) NULL,
    run_at    DATETIME(3)  NOT NULL DEFAULT (UTC_TIMESTAMP(3))
);

DROP PROCEDURE IF EXISTS sp_t;
DROP PROCEDURE IF EXISTS sp_try;
DROP PROCEDURE IF EXISTS sp_test_bulk;
DROP FUNCTION  IF EXISTS fn_test_payload;

DELIMITER $$

CREATE PROCEDURE sp_t(IN p_name VARCHAR(120), IN p_cond BOOLEAN, IN p_detail VARCHAR(1000))
    INSERT INTO test_result (run_tag, test_name, passed, detail)
    VALUES (@run, p_name, COALESCE(p_cond, FALSE), p_detail)$$

-- run arbitrary SQL, report whether it FAILED (for "this must be blocked" tests)
CREATE PROCEDURE sp_try(IN p_sql TEXT, OUT p_failed BOOLEAN, OUT p_msg VARCHAR(1000))
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        GET DIAGNOSTICS CONDITION 1 p_msg = MESSAGE_TEXT;
        SET p_failed = TRUE;
    END;
    SET p_failed = FALSE, p_msg = NULL;
    SET @dyn = p_sql;
    PREPARE st FROM @dyn;
    EXECUTE st;
    DEALLOCATE PREPARE st;
END$$

CREATE FUNCTION fn_test_payload(p_pan VARCHAR(40), p_age INT, p_gender VARCHAR(10),
                                p_income DECIMAL(15,2), p_score INT, p_dtir DECIMAL(6,2),
                                p_amount DECIMAL(15,2), p_term INT, p_property DECIMAL(15,2))
RETURNS JSON DETERMINISTIC NO SQL
RETURN JSON_OBJECT(
    'id_hash', SHA2(p_pan, 256),
    'full_name', CONCAT('Test ', p_pan),
    'date_of_birth', IF(p_age IS NULL, NULL, DATE_FORMAT(UTC_DATE() - INTERVAL p_age YEAR - INTERVAL 10 DAY, '%Y-%m-%d')),
    'gender', p_gender, 'dependents', 1,
    'income_monthly', p_income, 'credit_score', p_score, 'dtir', p_dtir,
    'credit_type', 'CIB', 'co_applicant_credit_type', 'EXP', 'credit_worthiness', 'l1',
    'loan_amount', p_amount, 'term_months', p_term, 'loan_type', 'type1', 'loan_purpose', 'p3',
    'property_value', p_property, 'occupancy_type', 'pr')$$

-- n applicants through the full pipeline with a fixed model probability
CREATE PROCEDURE sp_test_bulk(IN p_prefix VARCHAR(20), IN p_gender VARCHAR(10), IN p_n INT, IN p_prob DECIMAL(6,5))
BEGIN
    DECLARE i INT DEFAULT 0;
    DECLARE v_id BIGINT UNSIGNED;
    DECLARE v_o VARCHAR(20);
    DECLARE v_m VARCHAR(1000);
    WHILE i < p_n DO
        CALL sp_submit_application(CONCAT(@run, p_prefix, i),
             fn_test_payload(CONCAT(@run, p_prefix, i), 35, p_gender, 90000, 760, 25, 1000000, 180, 2500000),
             'TEST', v_id, v_o, v_m);
        CALL sp_run_rule_layer(v_id, v_o, v_m);
        CALL sp_record_prediction(v_id, @model, p_prob, NULL, NULL, 5, v_o, v_m);
        SET i = i + 1;
    END WHILE;
END$$

DELIMITER ;

SET @run   = CONCAT('R', DATE_FORMAT(UTC_TIMESTAMP(3), '%H%i%s%f'));
SET @t0    = UTC_TIMESTAMP(3) - INTERVAL 1 SECOND;
SET @model = (SELECT model_id FROM model_version WHERE is_active);

-- ---------------------------------------------------------------------
-- T01 Happy path: good applicant, confident model -> AUTO_APPROVED
-- ---------------------------------------------------------------------
CALL sp_submit_application(CONCAT(@run,'-T01'), fn_test_payload(CONCAT(@run,'P01'), 35, 'F', 80000, 780, 30, 1500000, 240, 2500000), 'TEST', @a1, @o, @m);
CALL sp_t('T01a submit valid application', @o = 'CREATED', @m);
CALL sp_run_rule_layer(@a1, @o, @m);
CALL sp_t('T01b all rules pass', @o = 'PASS', @m);
CALL sp_record_prediction(@a1, @model, 0.93, JSON_ARRAY('credit_score > 700.5','dtir <= 38.5'), JSON_ARRAY('high credit score','low DTI'), 4, @o, @m);
CALL sp_t('T01c high confidence -> auto approve', @o = 'APPROVED' AND (SELECT status FROM loan_application WHERE application_id=@a1) = 'AUTO_APPROVED', @m);
CALL sp_t('T01d 10 rule evaluations logged', (SELECT COUNT(*) FROM rule_evaluation WHERE application_id=@a1) = (SELECT COUNT(*) FROM policy_rule pr JOIN rule_set rs USING(rule_set_id) WHERE rs.is_active AND pr.is_active), NULL);

-- ---------------------------------------------------------------------
-- T02 Hard rule (under-age) -> rejected with reason, model never consulted
-- ---------------------------------------------------------------------
CALL sp_submit_application(CONCAT(@run,'-T02'), fn_test_payload(CONCAT(@run,'P02'), 19, 'M', 30000, 720, 20, 200000, 36, NULL), 'TEST', @a2, @o, @m);
CALL sp_run_rule_layer(@a2, @o, @m);
CALL sp_t('T02a under-age -> RULE rejected with reason', @o = 'REJECTED' AND @m LIKE '%R02_MIN_AGE%', @m);
CALL sp_record_prediction(@a2, @model, 0.99, NULL, NULL, 1, @o, @m);
CALL sp_t('T02b model cannot override a hard rule', @o = 'ALREADY_PROCESSED' AND (SELECT status FROM loan_application WHERE application_id=@a2) = 'RULE_REJECTED', @m);
CALL sp_try(CONCAT('UPDATE loan_application SET status=''AUTO_APPROVED'' WHERE application_id=', @a2), @f, @m);
CALL sp_t('T02c manual UPDATE to approved is blocked (state machine)', @f AND @m LIKE 'Illegal application status%', @m);

-- ---------------------------------------------------------------------
-- T03 Blacklisted identity
-- ---------------------------------------------------------------------
-- a fresh blacklisted identity per run: reusing one fixed ID would trip the
-- identity-mismatch check on later days (its date of birth is age-based)
INSERT INTO fraud_registry (id_hash, reason, source)
VALUES (SHA2(CONCAT(@run,'BLK'), 256), 'Test blacklist entry', 'TEST');
CALL sp_submit_application(CONCAT(@run,'-T03'), fn_test_payload(CONCAT(@run,'BLK'), 40, 'M', 90000, 800, 20, 500000, 60, NULL), 'TEST', @a3, @o, @m);
CALL sp_run_rule_layer(@a3, @o, @m);
CALL sp_t('T03 blacklisted applicant rejected', @o = 'REJECTED' AND @m LIKE '%R01_BLACKLIST%', @m);

-- ---------------------------------------------------------------------
-- T04 Several hard failures -> ALL reasons listed (adverse-action notice)
-- ---------------------------------------------------------------------
CALL sp_submit_application(CONCAT(@run,'-T04'), fn_test_payload(CONCAT(@run,'P04'), 30, 'M', 40000, 510, 62, 300000, 60, NULL), 'TEST', @a4, @o, @m);
CALL sp_run_rule_layer(@a4, @o, @m);
CALL sp_t('T04 multiple failures all reported', @o = 'REJECTED' AND @m LIKE '%R05_MIN_SCORE%' AND @m LIKE '%R06_MAX_DTI%', @m);

-- ---------------------------------------------------------------------
-- T05 Low model confidence -> human review, not a silent hard call
-- ---------------------------------------------------------------------
CALL sp_submit_application(CONCAT(@run,'-T05'), fn_test_payload(CONCAT(@run,'P05'), 45, 'M', 70000, 690, 35, 1200000, 180, 2000000), 'TEST', @a5, @o, @m);
CALL sp_run_rule_layer(@a5, @o, @m);
CALL sp_record_prediction(@a5, @model, 0.61, NULL, NULL, 3, @o, @m);
CALL sp_t('T05 low confidence -> REFERRED + review queue', @o = 'REFERRED' AND (SELECT reason FROM review_queue WHERE application_id=@a5) = 'LOW_CONFIDENCE', @m);

-- ---------------------------------------------------------------------
-- T06 Soft rule (loan > 5x annual income) overrides even a confident model
-- ---------------------------------------------------------------------
CALL sp_submit_application(CONCAT(@run,'-T06'), fn_test_payload(CONCAT(@run,'P06'), 30, 'F', 20000, 800, 20, 2000000, 240, 5000000), 'TEST', @a6, @o, @m);
CALL sp_run_rule_layer(@a6, @o, @m);
CALL sp_t('T06a soft rule -> PASS_REFER', @o = 'PASS_REFER' AND @m LIKE '%R08%', @m);
CALL sp_record_prediction(@a6, @model, 0.97, NULL, NULL, 3, @o, @m);
CALL sp_t('T06b confident model still goes to human', @o = 'REFERRED' AND (SELECT reason FROM review_queue WHERE application_id=@a6) = 'SOFT_RULE', @m);

-- ---------------------------------------------------------------------
-- T07 Thin-file applicant (no credit score) -> referred, not crashed
-- ---------------------------------------------------------------------
CALL sp_submit_application(CONCAT(@run,'-T07'), fn_test_payload(CONCAT(@run,'P07'), 26, 'M', 45000, NULL, 15, 300000, 60, NULL), 'TEST', @a7, @o, @m);
CALL sp_t('T07a missing credit score accepted', @o = 'CREATED', @m);
CALL sp_run_rule_layer(@a7, @o, @m);
CALL sp_t('T07b missing score -> PASS_REFER', @o = 'PASS_REFER', @m);
CALL sp_record_prediction(@a7, @model, 0.88, NULL, NULL, 3, @o, @m);
CALL sp_t('T07c routed as MISSING_DATA', @o = 'REFERRED' AND (SELECT reason FROM review_queue WHERE application_id=@a7) = 'MISSING_DATA', @m);

-- ---------------------------------------------------------------------
-- T08 Malformed input -> graceful INVALID listing every problem, nothing stored
-- ---------------------------------------------------------------------
SET @before = (SELECT COUNT(*) FROM loan_application);
CALL sp_submit_application(CONCAT(@run,'-T08'),
     JSON_OBJECT('id_hash','not-a-hash','full_name','A','date_of_birth','2001-02-30',
                 'credit_score','abc','loan_amount',-5,'term_months',0,'dtir','12%','occupancy_type','villa'),
     'TEST', @a8, @o, @m);
CALL sp_t('T08a malformed input -> INVALID', @o = 'INVALID' AND @a8 IS NULL, @m);
CALL sp_t('T08b every error reported', @m LIKE '%id_hash%' AND @m LIKE '%full_name%' AND @m LIKE '%date_of_birth%' AND @m LIKE '%credit_score%' AND @m LIKE '%loan_amount%' AND @m LIKE '%term_months%' AND @m LIKE '%dtir%' AND @m LIKE '%occupancy%', @m);
CALL sp_t('T08c nothing inserted', (SELECT COUNT(*) FROM loan_application) = @before, NULL);
CALL sp_submit_application(NULL, JSON_ARRAY(1,2), 'TEST', @x, @o, @m);
CALL sp_t('T08d non-object JSON -> INVALID', @o = 'INVALID', @m);
CALL sp_submit_application(NULL, NULL, 'TEST', @x, @o, @m);
CALL sp_t('T08e NULL payload -> INVALID', @o = 'INVALID', @m);
CALL sp_submit_application(CONCAT(@run,'-T08f'), JSON_SET(fn_test_payload(CONCAT(@run,'P08f'),30,'M',1,700,1,1,12,NULL), '$.loan_amount', 99999999999999999999), 'TEST', @x, @o, @m);
CALL sp_t('T08f absurdly large number -> INVALID (no overflow crash)', @o = 'INVALID', @m);

-- ---------------------------------------------------------------------
-- T09 Double-submit / network retry -> same application, no duplicate
-- ---------------------------------------------------------------------
CALL sp_submit_application(CONCAT(@run,'-T01'), fn_test_payload(CONCAT(@run,'P01'), 35, 'F', 80000, 780, 30, 1500000, 240, 2500000), 'TEST', @a9, @o, @m);
CALL sp_t('T09 idempotent resubmission', @o = 'DUPLICATE' AND @a9 = @a1, @m);

-- ---------------------------------------------------------------------
-- T10 Model crashes / returns NaN -> SYSTEM_FALLBACK to human (priority 1)
-- ---------------------------------------------------------------------
CALL sp_submit_application(CONCAT(@run,'-T10'), fn_test_payload(CONCAT(@run,'P10'), 50, 'F', 120000, 750, 25, 800000, 120, 3000000), 'TEST', @a10, @o, @m);
CALL sp_run_rule_layer(@a10, @o, @m);
CALL sp_record_prediction(@a10, @model, NULL, NULL, NULL, NULL, @o, @m);
CALL sp_t('T10 NaN probability -> fallback to human', @o = 'REFERRED' AND (SELECT CONCAT(reason, priority) FROM review_queue WHERE application_id=@a10) = 'MODEL_FAILURE1', @m);

-- ---------------------------------------------------------------------
-- T11 Human review workflow (claim, wrong officer, weak reason, override, double resolve)
-- ---------------------------------------------------------------------
SET @r5 = (SELECT review_id FROM review_queue WHERE application_id = @a5);
CALL sp_claim_review(@r5, 3, @o, @m);
CALL sp_t('T11a officer_a claims review', @o = 'OK', @m);
CALL sp_resolve_review(@r5, 4, 'APPROVED', 'Looks fine to me, verified salary slips.', @o, @m);
CALL sp_t('T11b other officer cannot resolve claimed item', @o = 'INVALID', @m);
CALL sp_resolve_review(@r5, 3, 'REJECTED', 'no', @o, @m);
CALL sp_t('T11c justification required', @o = 'INVALID', @m);
CALL sp_resolve_review(@r5, 5, 'REJECTED', 'Auditor should not be able to decide this.', @o, @m);
CALL sp_t('T11d auditor cannot decide', @o = 'INVALID', @m);
CALL sp_resolve_review(@r5, 3, 'REJECTED', 'Employer could not be verified; bank statements show irregular income.', @o, @m);
CALL sp_t('T11e officer overrides model lean', @o = 'OK' AND (SELECT d.is_override FROM loan_application a JOIN decision d ON d.decision_id=a.current_decision_id WHERE a.application_id=@a5) = 1, @m);
CALL sp_t('T11f override supersedes model decision (history kept)', (SELECT COUNT(*) FROM decision WHERE application_id=@a5) = 2, NULL);
CALL sp_resolve_review(@r5, 3, 'APPROVED', 'Trying to flip the decision a second time.', @o, @m);
CALL sp_t('T11g cannot resolve twice', @o = 'INVALID', @m);

-- ---------------------------------------------------------------------
-- T12 Append-only / immutability guarantees
-- ---------------------------------------------------------------------
CALL sp_try(CONCAT('UPDATE decision SET outcome=''APPROVED'' WHERE application_id=', @a2), @f, @m);
CALL sp_t('T12a decision rows cannot be edited', @f AND @m LIKE 'decision is append-only%', @m);
CALL sp_try('DELETE FROM audit_log ORDER BY audit_id LIMIT 1', @f, @m);
CALL sp_t('T12b audit rows cannot be deleted', @f AND @m LIKE 'audit_log is append-only%', @m);
CALL sp_try(CONCAT('UPDATE loan_application SET income_monthly = 999999 WHERE application_id=', @a1), @f, @m);
CALL sp_t('T12c application inputs frozen after submit', @f AND @m LIKE 'Application inputs are immutable%', @m);
CALL sp_try(CONCAT('DELETE FROM loan_application WHERE application_id=', @a1), @f, @m);
CALL sp_t('T12d applications cannot be deleted', @f AND @m LIKE 'Applications are never deleted%', @m);
CALL sp_try(CONCAT('DELETE FROM rule_evaluation WHERE application_id=', @a2), @f, @m);
CALL sp_t('T12e rule evaluations cannot be deleted', @f AND @m LIKE 'rule_evaluation is append-only%', @m);

-- ---------------------------------------------------------------------
-- T13 Policy change = new version; used version is frozen
-- ---------------------------------------------------------------------
SET @rs_old = (SELECT rule_set_id FROM rule_set WHERE is_active);
CALL sp_try(CONCAT('UPDATE policy_rule SET threshold = 40 WHERE rule_code=''R06_MAX_DTI'' AND rule_set_id=', @rs_old), @f, @m);
CALL sp_t('T13a used rule set cannot be edited in place', @f AND @m LIKE 'Rule set already used%', @m);
CALL sp_clone_rule_set(@rs_old, CONCAT('t', RIGHT(@run, 12)), 2, @rs_new);
UPDATE policy_rule SET threshold = 45 WHERE rule_code = 'R06_MAX_DTI' AND rule_set_id = @rs_new;
CALL sp_activate_rule_set(@rs_new);
CALL sp_t('T13b new version activated', (SELECT rule_set_id FROM rule_set WHERE is_active) = @rs_new, NULL);
CALL sp_t('T13c old decisions still point to old version', (SELECT rule_set_id FROM decision WHERE application_id=@a2 LIMIT 1) = @rs_old, NULL);
CALL sp_try('UPDATE rule_set SET is_active = TRUE', @f, @m);
CALL sp_t('T13d two active rule sets impossible', @f AND @m LIKE 'Duplicate entry%', @m);

-- ---------------------------------------------------------------------
-- T14 Identity fraud signal: same ID, different date of birth
-- ---------------------------------------------------------------------
CALL sp_submit_application(CONCAT(@run,'-T14'), fn_test_payload(CONCAT(@run,'P01'), 52, 'F', 80000, 780, 30, 100000, 24, NULL), 'TEST', @a14, @o, @m);
CALL sp_t('T14 identity mismatch blocked', @o = 'INVALID' AND @m LIKE 'Identity mismatch%', @m);

-- ---------------------------------------------------------------------
-- T15 Loan stacking: second application while one is pending
-- ---------------------------------------------------------------------
CALL sp_submit_application(CONCAT(@run,'-T15'), fn_test_payload(CONCAT(@run,'P07'), 26, 'M', 45000, 700, 15, 100000, 24, NULL), 'TEST', @a15, @o, @m);
CALL sp_run_rule_layer(@a15, @o, @m);
CALL sp_t('T15 parallel application -> referred', @o = 'PASS_REFER' AND @m LIKE '%R09%', @m);

-- ---------------------------------------------------------------------
-- T16 Withdrawals
-- ---------------------------------------------------------------------
CALL sp_withdraw_application(@a1, 'changed mind', @o, @m);
CALL sp_t('T16a cannot withdraw a final decision', @o = 'INVALID', @m);
CALL sp_withdraw_application(@a15, 'applied elsewhere', @o, @m);
CALL sp_t('T16b pending application withdrawn', @o = 'OK', @m);

-- ---------------------------------------------------------------------
-- T17 Model registry guards
-- ---------------------------------------------------------------------
CALL sp_record_prediction(@a7, 999999, 0.9, NULL, NULL, 1, @o, @m);
CALL sp_t('T17a unknown model rejected', @o = 'INVALID', @m);
CALL sp_try(CONCAT('UPDATE model_version SET confidence_threshold = 0.55 WHERE model_id=', @model), @f, @m);
CALL sp_t('T17b used model cannot be silently re-tuned', @f AND @m LIKE 'Model already used%', @m);

-- ---------------------------------------------------------------------
-- T18 Review SLA: overdue items are escalated, never dropped
-- ---------------------------------------------------------------------
UPDATE review_queue SET sla_due_at = UTC_TIMESTAMP(3) - INTERVAL 1 HOUR WHERE application_id = @a6;
CALL sp_escalate_overdue_reviews(@n);
CALL sp_t('T18 overdue review escalated', (SELECT CONCAT(status, priority) FROM review_queue WHERE application_id=@a6) = 'ESCALATED1', CONCAT(@n, ' escalated'));

-- ---------------------------------------------------------------------
-- T19 Fairness breach: intentionally skewed synthetic subgroup
-- 30 male applicants all approved, 30 female applicants 1/3 approved
-- ---------------------------------------------------------------------
CALL sp_test_bulk('-FM', 'M', 30, 0.95);
CALL sp_test_bulk('-FA', 'F', 10, 0.95);
CALL sp_test_bulk('-FR', 'F', 20, 0.05);
CALL sp_run_fairness('gender', 'MODEL_ONLY', @t0, UTC_TIMESTAMP(3) + INTERVAL 1 SECOND, 20, 0.800, 5, @run_id, @m);
CALL sp_t('T19a skewed subgroup FLAGGED', (SELECT status FROM fairness_result WHERE run_id=@run_id AND group_value='Female') = 'FLAGGED', @m);
CALL sp_t('T19b breach surfaced in audit log', EXISTS (SELECT 1 FROM audit_log WHERE table_name='fairness_run' AND record_id=@run_id), NULL);
CALL sp_run_fairness('gender', 'MODEL_ONLY', @t0, UTC_TIMESTAMP(3) + INTERVAL 1 SECOND, 1000, 0.800, 5, @run_id2, @m);
CALL sp_t('T19c small groups -> INSUFFICIENT_SAMPLE, not a false alarm', NOT (SELECT any_flagged FROM fairness_run WHERE run_id=@run_id2), @m);

-- ---------------------------------------------------------------------
-- T20 KPI views
-- ---------------------------------------------------------------------
CALL sp_t('T20a zero rule-vs-model conflicts', (SELECT COUNT(*) FROM v_kpi_rule_violations) = 0, NULL);
CALL sp_t('T20b 100% of decisions logged', (SELECT coverage_pct FROM v_kpi_audit_completeness) = 100, NULL);
CALL sp_t('T20c audit hash chain intact', (SELECT COUNT(*) FROM v_audit_chain_check) = 0 AND (SELECT COUNT(*) FROM audit_log) > 50, CONCAT((SELECT COUNT(*) FROM audit_log), ' audit rows verified'));

-- ---------------------------------------------------------------------
-- T21 Reproducibility: identical inputs -> identical rule outcome
-- ---------------------------------------------------------------------
CALL sp_submit_application(CONCAT(@run,'-T21a'), fn_test_payload(CONCAT(@run,'P21a'), 33, 'M', 50000, 600, 49, 900000, 120, NULL), 'TEST', @b1, @o, @m);
CALL sp_run_rule_layer(@b1, @o1, @m1);
CALL sp_submit_application(CONCAT(@run,'-T21b'), fn_test_payload(CONCAT(@run,'P21b'), 33, 'M', 50000, 600, 49, 900000, 120, NULL), 'TEST', @b2, @o, @m);
CALL sp_run_rule_layer(@b2, @o2, @m2);
CALL sp_t('T21 same input -> same decision', @o1 IN ('PASS','PASS_REFER','REJECTED') AND @o1 = @o2 AND @m1 = @m2, CONCAT(@o1, ' / ', @o2));

-- ---------------------------------------------------------------------
-- Restore the original rule set so the DB is left as seeded
-- ---------------------------------------------------------------------
CALL sp_activate_rule_set(@rs_old);

-- ========================== RESULTS ==========================
SELECT test_name, IF(passed, 'PASS', '** FAIL **') AS result, detail
  FROM test_result WHERE run_tag = @run ORDER BY test_id;
SELECT SUM(passed) AS passed, SUM(NOT passed) AS failed, COUNT(*) AS total
  FROM test_result WHERE run_tag = @run;
