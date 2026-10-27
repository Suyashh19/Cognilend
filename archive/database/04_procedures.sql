-- =====================================================================
-- CogniLend :: 04_procedures.sql
-- The pipeline API. The Python app should ONLY call these procedures
-- (never raw INSERT/UPDATE) so every edge case is handled in one place.
--
-- Every procedure returns OUT p_outcome / p_message instead of crashing:
--   sp_submit_application   -> CREATED | DUPLICATE | INVALID | ERROR
--   sp_run_rule_layer       -> REJECTED | PASS | PASS_REFER | ALREADY_PROCESSED | NOT_FOUND | ERROR
--   sp_record_prediction    -> APPROVED | REJECTED | REFERRED | ALREADY_PROCESSED | NOT_FOUND | INVALID | ERROR
--   sp_record_model_failure -> REFERRED | ALREADY_PROCESSED | NOT_FOUND | ERROR
--   sp_claim_review / sp_resolve_review / sp_withdraw_application -> OK | INVALID | ERROR ...
-- =====================================================================
USE cognilend;

DELIMITER $$

-- =====================================================================
-- Helper functions
-- =====================================================================

-- JSON field -> trimmed text; NULL if missing, JSON null or empty string
CREATE FUNCTION fn_jtxt(p JSON, k VARCHAR(64)) RETURNS VARCHAR(255)
DETERMINISTIC NO SQL
BEGIN
    DECLARE v JSON;
    SET v = JSON_EXTRACT(p, CONCAT('$.', k));
    IF v IS NULL OR JSON_TYPE(v) = 'NULL' THEN RETURN NULL; END IF;
    RETURN NULLIF(TRIM(JSON_UNQUOTE(v)), '');
END$$

-- JSON field -> number; NULL if missing OR not a valid number
-- (caller distinguishes the two with fn_jtxt)
CREATE FUNCTION fn_jnum(p JSON, k VARCHAR(64)) RETURNS DECIMAL(20,4)
DETERMINISTIC NO SQL
BEGIN
    DECLARE t VARCHAR(255);
    SET t = fn_jtxt(p, k);
    IF t IS NULL OR CHAR_LENGTH(t) > 16 OR NOT REGEXP_LIKE(t, '^-?[0-9]+(\\.[0-9]+)?$') THEN
        RETURN NULL;
    END IF;
    RETURN CAST(t AS DECIMAL(20,4));
END$$

-- age -> band, using the SAME bands as the Kaggle dataset so live and
-- historical data can be compared in fairness reports
CREATE FUNCTION fn_age_band(p_age INT) RETURNS VARCHAR(10)
DETERMINISTIC NO SQL
RETURN CASE
    WHEN p_age IS NULL THEN NULL
    WHEN p_age < 25 THEN '<25'
    WHEN p_age < 35 THEN '25-34'
    WHEN p_age < 45 THEN '35-44'
    WHEN p_age < 55 THEN '45-54'
    WHEN p_age < 65 THEN '55-64'
    WHEN p_age < 75 THEN '65-74'
    ELSE '>74' END$$

-- lowest possible age in a band ('<25' -> NULL: could be under 21)
CREATE FUNCTION fn_band_min_age(p_band VARCHAR(10)) RETURNS INT
DETERMINISTIC NO SQL
RETURN CASE
    WHEN p_band REGEXP '^[0-9]+-[0-9]+$' THEN CAST(SUBSTRING_INDEX(p_band, '-', 1) AS UNSIGNED)
    WHEN p_band REGEXP '^>[0-9]+$'       THEN CAST(SUBSTRING(p_band, 2) AS UNSIGNED) + 1
    ELSE NULL END$$

CREATE FUNCTION fn_group_value(p_attr VARCHAR(20), p_gender VARCHAR(20), p_band VARCHAR(10), p_deps INT)
RETURNS VARCHAR(30)
DETERMINISTIC NO SQL
RETURN CASE p_attr
    WHEN 'gender'     THEN p_gender
    WHEN 'age_band'   THEN COALESCE(p_band, 'Unknown')
    WHEN 'dependents' THEN CASE WHEN p_deps IS NULL THEN 'Unknown'
                                WHEN p_deps >= 3   THEN '3+'
                                ELSE CAST(p_deps AS CHAR) END
    END$$

-- rule set that was used for an application (falls back to active set)
CREATE FUNCTION fn_app_rule_set(p_app_id BIGINT UNSIGNED) RETURNS INT UNSIGNED
READS SQL DATA
RETURN COALESCE(
    (SELECT pr.rule_set_id FROM rule_evaluation re
       JOIN policy_rule pr ON pr.rule_id = re.rule_id
      WHERE re.application_id = p_app_id LIMIT 1),
    (SELECT rule_set_id FROM rule_set WHERE is_active LIMIT 1))$$


-- =====================================================================
-- 1) SUBMIT — validate raw input, upsert applicant, freeze snapshot
-- p_payload example:
-- {"id_hash":"<sha256 hex>","full_name":"Asha Patil","date_of_birth":"1995-04-12",
--  "gender":"F","dependents":1,"income_monthly":65000,"credit_score":742,
--  "credit_type":"CIB","co_applicant_credit_type":"EXP","credit_worthiness":"l1",
--  "dtir":32.5,"loan_amount":1500000,"term_months":240,"loan_type":"type1",
--  "loan_purpose":"p3","property_value":2500000,"occupancy_type":"pr"}
-- =====================================================================
CREATE PROCEDURE sp_submit_application(
    IN  p_idempotency_key VARCHAR(64),
    IN  p_payload         JSON,
    IN  p_source          VARCHAR(20),
    OUT p_application_id  BIGINT UNSIGNED,
    OUT p_outcome         VARCHAR(20),
    OUT p_message         VARCHAR(1000))
proc: BEGIN
    DECLARE v_err, v_msg VARCHAR(1000) DEFAULT NULL;
    DECLARE v_errno INT;
    DECLARE v_id_hash CHAR(64);
    DECLARE v_name VARCHAR(100);
    DECLARE v_dob_txt VARCHAR(255);
    DECLARE v_dob DATE;
    DECLARE v_gender VARCHAR(20);
    DECLARE v_deps, v_income, v_score, v_dtir, v_amount, v_term, v_property DECIMAL(20,4);
    DECLARE v_credit_type, v_coapp_type, v_worth, v_loan_type, v_purpose, v_occ VARCHAR(20);
    DECLARE v_applicant_id BIGINT UNSIGNED;
    DECLARE v_old_dob DATE;
    DECLARE v_old_deleted BOOLEAN;
    DECLARE v_age INT;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        GET DIAGNOSTICS CONDITION 1 v_msg = MESSAGE_TEXT, v_errno = MYSQL_ERRNO;
        ROLLBACK;
        -- race: two identical submissions at the same moment -> second hits UNIQUE
        SET p_application_id = (SELECT application_id FROM loan_application
                                 WHERE idempotency_key = p_idempotency_key);
        IF v_errno = 1062 AND p_application_id IS NOT NULL THEN
            SET p_outcome = 'DUPLICATE', p_message = 'Already submitted with this idempotency key';
        ELSE
            SET p_application_id = NULL, p_outcome = 'ERROR', p_message = LEFT(v_msg, 1000);
        END IF;
    END;

    SET p_application_id = NULL;

    -- ---------- structural checks ----------
    IF p_payload IS NULL OR JSON_TYPE(p_payload) <> 'OBJECT' THEN
        SET p_outcome = 'INVALID', p_message = 'Payload must be a JSON object';
        LEAVE proc;
    END IF;
    IF p_source IS NULL OR p_source NOT IN ('LIVE', 'TEST') THEN
        SET p_outcome = 'INVALID', p_message = 'p_source must be LIVE or TEST';
        LEAVE proc;
    END IF;

    -- ---------- idempotency: same key => return the original ----------
    IF p_idempotency_key IS NOT NULL THEN
        SET p_application_id = (SELECT application_id FROM loan_application
                                 WHERE idempotency_key = p_idempotency_key);
        IF p_application_id IS NOT NULL THEN
            SET p_outcome = 'DUPLICATE', p_message = 'Already submitted with this idempotency key';
            LEAVE proc;
        END IF;
    END IF;

    -- ---------- extract ----------
    SET v_id_hash  = LOWER(fn_jtxt(p_payload, 'id_hash'));
    SET v_name     = fn_jtxt(p_payload, 'full_name');
    SET v_dob_txt  = fn_jtxt(p_payload, 'date_of_birth');
    -- STR_TO_DATE raises an error on '2001-02-30' in strict mode, so check
    -- the calendar arithmetically first and only then convert
    IF v_dob_txt REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
       AND CAST(SUBSTRING(v_dob_txt, 1, 4) AS UNSIGNED) >= 1900
       AND CAST(SUBSTRING(v_dob_txt, 6, 2) AS UNSIGNED) BETWEEN 1 AND 12
       AND CAST(SUBSTRING(v_dob_txt, 9, 2) AS UNSIGNED) BETWEEN 1 AND
           DAY(LAST_DAY(CONCAT(SUBSTRING(v_dob_txt, 1, 7), '-01'))) THEN
        SET v_dob = CAST(v_dob_txt AS DATE);
    END IF;
    SET v_gender   = CASE LOWER(fn_jtxt(p_payload, 'gender'))
                        WHEN 'male' THEN 'Male' WHEN 'm' THEN 'Male'
                        WHEN 'female' THEN 'Female' WHEN 'f' THEN 'Female'
                        WHEN 'joint' THEN 'Joint'
                        ELSE 'Not_Disclosed' END;
    SET v_deps     = fn_jnum(p_payload, 'dependents');
    SET v_income   = fn_jnum(p_payload, 'income_monthly');
    SET v_score    = fn_jnum(p_payload, 'credit_score');
    SET v_dtir     = fn_jnum(p_payload, 'dtir');
    SET v_amount   = fn_jnum(p_payload, 'loan_amount');
    SET v_term     = fn_jnum(p_payload, 'term_months');
    SET v_property = fn_jnum(p_payload, 'property_value');
    SET v_credit_type = UPPER(fn_jtxt(p_payload, 'credit_type'));
    SET v_coapp_type  = UPPER(fn_jtxt(p_payload, 'co_applicant_credit_type'));
    SET v_worth       = LOWER(fn_jtxt(p_payload, 'credit_worthiness'));
    SET v_loan_type   = LOWER(fn_jtxt(p_payload, 'loan_type'));
    SET v_purpose     = LOWER(fn_jtxt(p_payload, 'loan_purpose'));
    SET v_occ         = LOWER(fn_jtxt(p_payload, 'occupancy_type'));

    -- ---------- validate: collect ALL problems, not just the first ----------
    IF v_id_hash IS NULL OR NOT REGEXP_LIKE(v_id_hash, '^[0-9a-f]{64}$') THEN
        SET v_err = CONCAT_WS('; ', v_err, 'id_hash must be a 64-char SHA-256 hex string'); END IF;
    IF v_name IS NULL OR CHAR_LENGTH(v_name) < 2 OR CHAR_LENGTH(v_name) > 100 THEN
        SET v_err = CONCAT_WS('; ', v_err, 'full_name is required (2-100 chars)'); END IF;
    IF v_dob_txt IS NOT NULL AND v_dob IS NULL THEN
        SET v_err = CONCAT_WS('; ', v_err, 'date_of_birth must be a real date in YYYY-MM-DD'); END IF;
    IF v_dob > UTC_DATE() THEN
        SET v_err = CONCAT_WS('; ', v_err, 'date_of_birth is in the future'); END IF;
    IF v_dob < UTC_DATE() - INTERVAL 120 YEAR THEN
        SET v_err = CONCAT_WS('; ', v_err, 'date_of_birth implies age over 120'); END IF;

    -- numeric fields: present-but-not-a-number is an error; missing is allowed (rules decide)
    IF fn_jtxt(p_payload,'dependents')     IS NOT NULL AND (v_deps IS NULL OR v_deps < 0 OR v_deps > 20 OR v_deps <> FLOOR(v_deps)) THEN
        SET v_err = CONCAT_WS('; ', v_err, 'dependents must be a whole number 0-20'); END IF;
    IF fn_jtxt(p_payload,'income_monthly') IS NOT NULL AND (v_income IS NULL OR v_income < 0) THEN
        SET v_err = CONCAT_WS('; ', v_err, 'income_monthly must be a number >= 0'); END IF;
    IF fn_jtxt(p_payload,'credit_score')   IS NOT NULL AND (v_score IS NULL OR v_score < 300 OR v_score > 900 OR v_score <> FLOOR(v_score)) THEN
        SET v_err = CONCAT_WS('; ', v_err, 'credit_score must be a whole number 300-900 (omit it for no credit history)'); END IF;
    IF fn_jtxt(p_payload,'dtir')           IS NOT NULL AND (v_dtir IS NULL OR v_dtir < 0 OR v_dtir > 999) THEN
        SET v_err = CONCAT_WS('; ', v_err, 'dtir must be a percentage 0-999'); END IF;
    IF v_amount IS NULL OR v_amount <= 0 OR v_amount > 999999999 THEN
        SET v_err = CONCAT_WS('; ', v_err, 'loan_amount is required and must be > 0'); END IF;
    IF v_term IS NULL OR v_term < 1 OR v_term > 600 OR v_term <> FLOOR(v_term) THEN
        SET v_err = CONCAT_WS('; ', v_err, 'term_months is required, whole number 1-600'); END IF;
    IF fn_jtxt(p_payload,'property_value') IS NOT NULL AND (v_property IS NULL OR v_property <= 0) THEN
        SET v_err = CONCAT_WS('; ', v_err, 'property_value must be > 0 (omit for unsecured loans)'); END IF;

    -- categorical whitelists (the model cannot encode unseen categories)
    IF v_credit_type IS NOT NULL AND v_credit_type NOT IN ('EXP','EQUI','CRIF','CIB') THEN
        SET v_err = CONCAT_WS('; ', v_err, 'credit_type must be EXP/EQUI/CRIF/CIB'); END IF;
    IF v_coapp_type IS NOT NULL AND v_coapp_type NOT IN ('EXP','CIB') THEN
        SET v_err = CONCAT_WS('; ', v_err, 'co_applicant_credit_type must be EXP/CIB'); END IF;
    IF v_worth IS NOT NULL AND v_worth NOT IN ('l1','l2') THEN
        SET v_err = CONCAT_WS('; ', v_err, 'credit_worthiness must be l1/l2'); END IF;
    IF v_loan_type IS NOT NULL AND v_loan_type NOT IN ('type1','type2','type3') THEN
        SET v_err = CONCAT_WS('; ', v_err, 'loan_type must be type1/type2/type3'); END IF;
    IF v_purpose IS NOT NULL AND v_purpose NOT IN ('p1','p2','p3','p4') THEN
        SET v_err = CONCAT_WS('; ', v_err, 'loan_purpose must be p1-p4'); END IF;
    IF v_occ IS NOT NULL AND v_occ NOT IN ('pr','sr','ir') THEN
        SET v_err = CONCAT_WS('; ', v_err, 'occupancy_type must be pr/sr/ir'); END IF;

    IF v_err IS NOT NULL THEN
        INSERT INTO audit_log (table_name, record_id, action, payload)
        VALUES ('loan_application', 0, 'BLOCKED',
                JSON_OBJECT('reason', 'VALIDATION', 'errors', v_err,
                            'idempotency_key', p_idempotency_key, 'id_hash', v_id_hash));
        SET p_outcome = 'INVALID', p_message = LEFT(v_err, 1000);
        LEAVE proc;
    END IF;

    START TRANSACTION;

    -- ---------- applicant upsert with identity-consistency check ----------
    SELECT applicant_id, date_of_birth, is_deleted
      INTO v_applicant_id, v_old_dob, v_old_deleted
      FROM applicant WHERE id_hash = v_id_hash FOR UPDATE;

    IF v_applicant_id IS NOT NULL THEN
        IF v_old_deleted THEN
            ROLLBACK;
            SET p_outcome = 'INVALID', p_message = 'Applicant record is closed';
            LEAVE proc;
        END IF;
        IF v_old_dob IS NOT NULL AND v_dob IS NOT NULL AND v_old_dob <> v_dob THEN
            ROLLBACK;
            INSERT INTO audit_log (table_name, record_id, action, payload)
            VALUES ('applicant', v_applicant_id, 'BLOCKED',
                    JSON_OBJECT('reason', 'IDENTITY_MISMATCH', 'idempotency_key', p_idempotency_key));
            SET p_outcome = 'INVALID',
                p_message = 'Identity mismatch: date of birth differs from existing record for this ID (logged for fraud review)';
            LEAVE proc;
        END IF;
        -- update profile only if something actually changed (keeps audit log clean)
        UPDATE applicant
           SET full_name     = v_name,
               date_of_birth = COALESCE(date_of_birth, v_dob),
               gender        = IF(v_gender = 'Not_Disclosed', gender, v_gender),
               dependents    = COALESCE(v_deps, dependents)
         WHERE applicant_id = v_applicant_id
           AND (   NOT (full_name <=> v_name)
                OR (date_of_birth IS NULL AND v_dob IS NOT NULL)
                OR (v_gender <> 'Not_Disclosed' AND NOT (gender <=> v_gender))
                OR (v_deps IS NOT NULL AND NOT (dependents <=> v_deps)));
    ELSE
        INSERT INTO applicant (id_hash, full_name, date_of_birth, gender, dependents)
        VALUES (v_id_hash, v_name, v_dob, v_gender, v_deps);
        SET v_applicant_id = LAST_INSERT_ID();
    END IF;

    SELECT TIMESTAMPDIFF(YEAR, date_of_birth, UTC_DATE()), gender, dependents
      INTO v_age, v_gender, v_deps
      FROM applicant WHERE applicant_id = v_applicant_id;

    -- ---------- frozen snapshot ----------
    INSERT INTO loan_application
        (idempotency_key, applicant_id, source, age_at_application, age_band,
         gender_snapshot, dependents_snapshot, income_monthly, credit_score, credit_type,
         co_applicant_credit_type, credit_worthiness, dtir, loan_amount, term_months,
         loan_type, loan_purpose, property_value, occupancy_type)
    VALUES
        (p_idempotency_key, v_applicant_id, p_source, v_age, fn_age_band(v_age),
         v_gender, v_deps, v_income, v_score, v_credit_type,
         v_coapp_type, v_worth, v_dtir, v_amount, v_term,
         v_loan_type, v_purpose, v_property, v_occ);
    SET p_application_id = LAST_INSERT_ID();

    COMMIT;
    SET p_outcome = 'CREATED', p_message = 'Application received';
END$$


-- =====================================================================
-- 2) LAYER 1 — policy rules (forward-chaining: derive facts, then
--    evaluate EVERY active rule, log each result, decide)
-- =====================================================================
CREATE PROCEDURE sp_run_rule_layer(
    IN  p_app_id  BIGINT UNSIGNED,
    OUT p_outcome VARCHAR(20),
    OUT p_message VARCHAR(1000))
proc: BEGIN
    DECLARE v_done INT DEFAULT 0;
    DECLARE v_msg VARCHAR(1000);
    DECLARE v_status VARCHAR(30);
    DECLARE v_rs INT UNSIGNED;
    DECLARE v_facts JSON;
    DECLARE v_age INT;
    DECLARE v_applicant BIGINT UNSIGNED;
    DECLARE v_id_hash CHAR(64);
    DECLARE v_band VARCHAR(10);
    DECLARE v_income, v_score, v_dtir, v_ltv, v_amount DECIMAL(20,4);
    DECLARE v_term INT;
    -- cursor row
    DECLARE c_rule_id INT UNSIGNED;
    DECLARE c_code VARCHAR(30);
    DECLARE c_fact VARCHAR(40);
    DECLARE c_op VARCHAR(2);
    DECLARE c_thr DECIMAL(15,4);
    DECLARE c_sev VARCHAR(4);
    DECLARE c_missing VARCHAR(5);
    DECLARE c_reason VARCHAR(255);
    -- evaluation
    DECLARE v_val JSON;
    DECLARE v_num DECIMAL(20,4);
    DECLARE v_pass BOOLEAN;
    DECLARE v_res VARCHAR(15);
    DECLARE v_hard, v_soft INT DEFAULT 0;
    DECLARE v_hard_reasons, v_soft_reasons TEXT DEFAULT NULL;
    DECLARE v_dec_id BIGINT UNSIGNED;

    DECLARE cur_rules CURSOR FOR
        SELECT rule_id, rule_code, fact_key, operator, threshold, severity, on_missing, reason_text
          FROM policy_rule
         WHERE rule_set_id = v_rs AND is_active
         ORDER BY priority, rule_id;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        GET DIAGNOSTICS CONDITION 1 v_msg = MESSAGE_TEXT;
        ROLLBACK;
        SET p_outcome = 'ERROR', p_message = LEFT(v_msg, 1000);
    END;

    START TRANSACTION;

    SELECT a.status, a.applicant_id, ap.id_hash, a.age_at_application, a.age_band,
           a.income_monthly, a.credit_score, a.dtir, a.ltv, a.loan_amount, a.term_months
      INTO v_status, v_applicant, v_id_hash, v_age, v_band,
           v_income, v_score, v_dtir, v_ltv, v_amount, v_term
      FROM loan_application a JOIN applicant ap ON ap.applicant_id = a.applicant_id
     WHERE a.application_id = p_app_id
       FOR UPDATE;   -- locks the row: two workers cannot process the same app

    IF v_status IS NULL THEN
        ROLLBACK; SET p_outcome = 'NOT_FOUND', p_message = 'No such application'; LEAVE proc;
    END IF;
    IF v_status <> 'RECEIVED' THEN
        ROLLBACK; SET p_outcome = 'ALREADY_PROCESSED', p_message = CONCAT('Current status: ', v_status); LEAVE proc;
    END IF;

    SET v_rs = (SELECT rule_set_id FROM rule_set WHERE is_active);
    IF v_rs IS NULL THEN
        ROLLBACK; SET p_outcome = 'ERROR', p_message = 'No active rule set — refusing to decide without policy'; LEAVE proc;
    END IF;

    -- ---------- derive facts (the "working memory" of the rule engine) ----------
    SET v_age = COALESCE(v_age, fn_band_min_age(v_band));
    SET v_facts = JSON_OBJECT(
        'age',                   v_age,
        'age_at_maturity',       IF(v_age IS NULL, NULL, v_age + CEIL(v_term / 12)),
        'income_monthly',        v_income,
        'credit_score',          v_score,
        'dtir',                  v_dtir,
        'ltv',                   v_ltv,
        'loan_amount',           v_amount,
        'term_months',           v_term,
        'loan_to_annual_income', IF(v_income > 0, ROUND(v_amount / (v_income * 12), 4), NULL),
        -- IF(...,1,0): a bare EXISTS would become JSON true/false, not a number
        'is_blacklisted',        IF(EXISTS (SELECT 1 FROM fraud_registry f
                                             WHERE f.id_hash = v_id_hash
                                               AND (f.expires_at IS NULL OR f.expires_at > UTC_TIMESTAMP(3))), 1, 0),
        'open_applications',     (SELECT COUNT(*) FROM loan_application o
                                   WHERE o.applicant_id = v_applicant AND o.application_id <> p_app_id
                                     AND o.status IN ('RECEIVED','PENDING_MODEL','PENDING_REVIEW')),
        'rejections_last_30d',   (SELECT COUNT(*) FROM loan_application o
                                   WHERE o.applicant_id = v_applicant AND o.application_id <> p_app_id
                                     AND o.status IN ('RULE_REJECTED','AUTO_REJECTED','OFFICER_REJECTED')
                                     AND o.submitted_at >= UTC_TIMESTAMP(3) - INTERVAL 30 DAY));

    -- ---------- evaluate every rule ----------
    SET v_done = 0;
    OPEN cur_rules;
    rule_loop: LOOP
        FETCH cur_rules INTO c_rule_id, c_code, c_fact, c_op, c_thr, c_sev, c_missing, c_reason;
        IF v_done THEN LEAVE rule_loop; END IF;

        SET v_val = JSON_EXTRACT(v_facts, CONCAT('$.', c_fact));
        SET v_num = NULL;

        IF v_val IS NULL OR JSON_TYPE(v_val) = 'NULL' THEN
            -- missing data: never crash, never silently pass
            CASE c_missing
                WHEN 'SKIP'  THEN SET v_res = 'SKIPPED';
                WHEN 'REFER' THEN SET v_res = 'MISSING_REFER';
                ELSE              SET v_res = 'MISSING_FAIL';
            END CASE;
        ELSE
            SET v_num = IF(JSON_TYPE(v_val) = 'BOOLEAN',
                           IF(v_val = CAST('true' AS JSON), 1, 0),
                           CAST(JSON_UNQUOTE(v_val) AS DECIMAL(20,4)));
            SET v_pass = CASE c_op
                WHEN '>=' THEN v_num >= c_thr   WHEN '<=' THEN v_num <= c_thr
                WHEN '>'  THEN v_num >  c_thr   WHEN '<'  THEN v_num <  c_thr
                WHEN '='  THEN v_num =  c_thr   WHEN '!=' THEN v_num <> c_thr END;
            SET v_res = IF(v_pass, 'PASS', 'FAIL');
        END IF;

        IF v_res = 'FAIL' OR v_res = 'MISSING_FAIL' THEN
            IF c_sev = 'HARD' THEN
                SET v_hard = v_hard + 1;
                SET v_hard_reasons = CONCAT_WS(' | ', v_hard_reasons,
                        CONCAT(c_code, ': ', c_reason, IF(v_res = 'MISSING_FAIL', ' (required data missing)', '')));
            ELSE
                SET v_soft = v_soft + 1;
                SET v_soft_reasons = CONCAT_WS(' | ', v_soft_reasons, CONCAT(c_code, ': ', c_reason));
            END IF;
        ELSEIF v_res = 'MISSING_REFER' THEN
            SET v_soft = v_soft + 1;
            SET v_soft_reasons = CONCAT_WS(' | ', v_soft_reasons, CONCAT(c_code, ': data missing (', c_fact, ')'));
        END IF;

        INSERT INTO rule_evaluation (application_id, rule_id, outcome, observed_value, threshold_used)
        VALUES (p_app_id, c_rule_id, v_res, LEFT(CAST(v_num AS CHAR), 64), c_thr);
    END LOOP;
    CLOSE cur_rules;

    -- ---------- conclude ----------
    IF v_hard > 0 THEN
        INSERT INTO decision (application_id, decision_source, outcome, confidence, reason_text,
                              rule_set_id, decided_by)
        VALUES (p_app_id, 'RULE', 'REJECTED', 1.0,
                LEFT(CONCAT('Rejected by policy: ', v_hard_reasons), 1000), v_rs, 1);
        SET v_dec_id = LAST_INSERT_ID();
        UPDATE loan_application SET status = 'RULE_REJECTED', current_decision_id = v_dec_id
         WHERE application_id = p_app_id;
        SET p_outcome = 'REJECTED', p_message = LEFT(v_hard_reasons, 1000);
    ELSE
        UPDATE loan_application SET status = 'PENDING_MODEL', soft_referral = (v_soft > 0)
         WHERE application_id = p_app_id;
        IF v_soft > 0 THEN
            SET p_outcome = 'PASS_REFER', p_message = LEFT(CONCAT('Will go to human review: ', v_soft_reasons), 1000);
        ELSE
            SET p_outcome = 'PASS', p_message = 'All policy rules passed';
        END IF;
    END IF;

    COMMIT;
END$$


-- =====================================================================
-- 3) LAYER 2 — record the model's prediction and ROUTE it
-- =====================================================================
CREATE PROCEDURE sp_record_model_failure(
    IN  p_app_id  BIGINT UNSIGNED,
    IN  p_error   VARCHAR(500),
    OUT p_outcome VARCHAR(20),
    OUT p_message VARCHAR(1000))
proc: BEGIN
    DECLARE v_msg VARCHAR(1000);
    DECLARE v_status VARCHAR(30);
    DECLARE v_dec_id BIGINT UNSIGNED;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        GET DIAGNOSTICS CONDITION 1 v_msg = MESSAGE_TEXT;
        ROLLBACK;
        SET p_outcome = 'ERROR', p_message = LEFT(v_msg, 1000);
    END;

    START TRANSACTION;
    SELECT status INTO v_status FROM loan_application WHERE application_id = p_app_id FOR UPDATE;
    IF v_status IS NULL THEN
        ROLLBACK; SET p_outcome = 'NOT_FOUND', p_message = 'No such application'; LEAVE proc;
    END IF;
    IF v_status <> 'PENDING_MODEL' THEN
        ROLLBACK; SET p_outcome = 'ALREADY_PROCESSED', p_message = CONCAT('Current status: ', v_status); LEAVE proc;
    END IF;

    INSERT INTO decision (application_id, decision_source, outcome, reason_text, rule_set_id, decided_by)
    VALUES (p_app_id, 'SYSTEM_FALLBACK', 'REFERRED',
            LEFT(CONCAT('Model unavailable or returned invalid output: ', COALESCE(p_error, 'unknown error')), 1000),
            fn_app_rule_set(p_app_id), 1);
    SET v_dec_id = LAST_INSERT_ID();
    INSERT INTO review_queue (application_id, reason, priority, sla_due_at)
    VALUES (p_app_id, 'MODEL_FAILURE', 1, UTC_TIMESTAMP(3) + INTERVAL 24 HOUR);
    UPDATE loan_application SET status = 'PENDING_REVIEW', current_decision_id = v_dec_id
     WHERE application_id = p_app_id;
    COMMIT;
    SET p_outcome = 'REFERRED', p_message = 'Model failure — routed to human review (priority 1)';
END$$

CREATE PROCEDURE sp_record_prediction(
    IN  p_app_id        BIGINT UNSIGNED,
    IN  p_model_id      INT UNSIGNED,
    IN  p_prob_approve  DECIMAL(10,6),
    IN  p_decision_path JSON,
    IN  p_top_reasons   JSON,
    IN  p_latency_ms    INT UNSIGNED,
    OUT p_outcome       VARCHAR(20),
    OUT p_message       VARCHAR(1000))
proc: BEGIN
    DECLARE v_msg VARCHAR(1000);
    DECLARE v_status VARCHAR(30);
    DECLARE v_soft BOOLEAN;
    DECLARE v_thr DECIMAL(5,4);
    DECLARE v_active BOOLEAN;
    DECLARE v_conf DECIMAL(6,5);
    DECLARE v_label VARCHAR(10);
    DECLARE v_pred_id, v_dec_id BIGINT UNSIGNED;
    DECLARE v_flags TEXT;
    DECLARE v_missing INT;
    DECLARE v_reason VARCHAR(1000);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        GET DIAGNOSTICS CONDITION 1 v_msg = MESSAGE_TEXT;
        ROLLBACK;
        SET p_outcome = 'ERROR', p_message = LEFT(v_msg, 1000);
    END;

    -- model registry check (caller bug => INVALID, nothing written)
    SELECT confidence_threshold, is_active INTO v_thr, v_active
      FROM model_version WHERE model_id = p_model_id;
    IF v_thr IS NULL THEN
        SET p_outcome = 'INVALID', p_message = 'Unknown model_id'; LEAVE proc;
    END IF;
    IF NOT v_active THEN
        SET p_outcome = 'INVALID', p_message = 'Model is not the active version — re-predict with the active model'; LEAVE proc;
    END IF;

    -- garbage from the model (NaN -> NULL, out of range) => fail safe to a human
    IF p_prob_approve IS NULL OR p_prob_approve < 0 OR p_prob_approve > 1 THEN
        CALL sp_record_model_failure(p_app_id,
             CONCAT('invalid probability ', COALESCE(CAST(p_prob_approve AS CHAR), 'NULL')),
             p_outcome, p_message);
        LEAVE proc;
    END IF;

    START TRANSACTION;
    SELECT status, soft_referral INTO v_status, v_soft
      FROM loan_application WHERE application_id = p_app_id FOR UPDATE;
    IF v_status IS NULL THEN
        ROLLBACK; SET p_outcome = 'NOT_FOUND', p_message = 'No such application'; LEAVE proc;
    END IF;
    IF v_status <> 'PENDING_MODEL' THEN
        -- includes RULE_REJECTED: the model can never be recorded against a rule-rejected app
        ROLLBACK; SET p_outcome = 'ALREADY_PROCESSED', p_message = CONCAT('Current status: ', v_status); LEAVE proc;
    END IF;

    SET v_conf  = GREATEST(p_prob_approve, 1 - p_prob_approve);
    SET v_label = IF(p_prob_approve >= 0.5, 'APPROVED', 'REJECTED');

    INSERT INTO model_prediction (application_id, model_id, predicted_label, prob_approve, confidence,
                                  decision_path, top_reasons, latency_ms)
    VALUES (p_app_id, p_model_id, v_label, p_prob_approve, v_conf, p_decision_path, p_top_reasons, p_latency_ms);
    SET v_pred_id = LAST_INSERT_ID();

    IF v_soft OR v_conf < v_thr THEN
        SELECT GROUP_CONCAT(CONCAT(pr.rule_code, ': ', pr.reason_text) SEPARATOR ' | '),
               SUM(re.outcome = 'MISSING_REFER')
          INTO v_flags, v_missing
          FROM rule_evaluation re JOIN policy_rule pr ON pr.rule_id = re.rule_id
         WHERE re.application_id = p_app_id AND re.outcome IN ('FAIL','MISSING_REFER','MISSING_FAIL');

        SET v_reason = LEFT(CONCAT_WS('; ',
            CONCAT('Model leans ', v_label, ' with confidence ', v_conf),
            IF(v_conf < v_thr, CONCAT('below auto-decision threshold ', v_thr), NULL),
            IF(v_soft, CONCAT('Policy flags: ', v_flags), NULL)), 1000);

        INSERT INTO decision (application_id, decision_source, outcome, confidence, reason_text,
                              rule_set_id, model_id, prediction_id, decided_by)
        VALUES (p_app_id, 'MODEL', 'REFERRED', v_conf, v_reason,
                fn_app_rule_set(p_app_id), p_model_id, v_pred_id, 1);
        SET v_dec_id = LAST_INSERT_ID();

        INSERT INTO review_queue (application_id, reason, priority, sla_due_at)
        VALUES (p_app_id,
                CASE WHEN v_missing > 0 THEN 'MISSING_DATA' WHEN v_soft THEN 'SOFT_RULE' ELSE 'LOW_CONFIDENCE' END,
                IF(v_soft, 2, 3),
                UTC_TIMESTAMP(3) + INTERVAL 48 HOUR);

        UPDATE loan_application SET status = 'PENDING_REVIEW', current_decision_id = v_dec_id
         WHERE application_id = p_app_id;
        SET p_outcome = 'REFERRED', p_message = v_reason;
    ELSE
        SET v_reason = LEFT(CONCAT('Model ', v_label, ' (confidence ', v_conf, ')',
                                   IF(p_top_reasons IS NULL, '', CONCAT(' — key factors: ', CAST(p_top_reasons AS CHAR)))), 1000);
        INSERT INTO decision (application_id, decision_source, outcome, confidence, reason_text,
                              rule_set_id, model_id, prediction_id, decided_by)
        VALUES (p_app_id, 'MODEL', v_label, v_conf, v_reason,
                fn_app_rule_set(p_app_id), p_model_id, v_pred_id, 1);
        SET v_dec_id = LAST_INSERT_ID();
        UPDATE loan_application
           SET status = IF(v_label = 'APPROVED', 'AUTO_APPROVED', 'AUTO_REJECTED'),
               current_decision_id = v_dec_id
         WHERE application_id = p_app_id;
        SET p_outcome = v_label, p_message = v_reason;
    END IF;

    COMMIT;
END$$


-- =====================================================================
-- 4) HUMAN-IN-THE-LOOP
-- =====================================================================
CREATE PROCEDURE sp_claim_review(
    IN  p_review_id  BIGINT UNSIGNED,
    IN  p_officer_id INT UNSIGNED,
    OUT p_outcome    VARCHAR(20),
    OUT p_message    VARCHAR(1000))
proc: BEGIN
    DECLARE v_msg VARCHAR(1000);
    DECLARE v_status VARCHAR(20);
    DECLARE v_assigned INT UNSIGNED;
    DECLARE v_role VARCHAR(10);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        GET DIAGNOSTICS CONDITION 1 v_msg = MESSAGE_TEXT;
        ROLLBACK; SET p_outcome = 'ERROR', p_message = LEFT(v_msg, 1000);
    END;

    SELECT role INTO v_role FROM app_user WHERE user_id = p_officer_id AND is_active;
    IF v_role IS NULL OR v_role NOT IN ('OFFICER','ADMIN') THEN
        SET p_outcome = 'INVALID', p_message = 'User is not an active loan officer'; LEAVE proc;
    END IF;

    START TRANSACTION;
    SELECT status, assigned_to INTO v_status, v_assigned
      FROM review_queue WHERE review_id = p_review_id FOR UPDATE;
    IF v_status IS NULL THEN
        ROLLBACK; SET p_outcome = 'NOT_FOUND', p_message = 'No such review item'; LEAVE proc;
    END IF;
    IF v_status = 'RESOLVED' THEN
        ROLLBACK; SET p_outcome = 'INVALID', p_message = 'Review already resolved'; LEAVE proc;
    END IF;
    IF v_status = 'IN_PROGRESS' AND v_assigned <> p_officer_id THEN
        ROLLBACK; SET p_outcome = 'INVALID', p_message = 'Already claimed by another officer'; LEAVE proc;
    END IF;
    UPDATE review_queue SET status = 'IN_PROGRESS', assigned_to = p_officer_id WHERE review_id = p_review_id;
    COMMIT;
    SET p_outcome = 'OK', p_message = 'Claimed';
END$$

CREATE PROCEDURE sp_resolve_review(
    IN  p_review_id  BIGINT UNSIGNED,
    IN  p_officer_id INT UNSIGNED,
    IN  p_decision   VARCHAR(10),        -- APPROVED / REJECTED
    IN  p_reason     VARCHAR(1000),
    OUT p_outcome    VARCHAR(20),
    OUT p_message    VARCHAR(1000))
proc: BEGIN
    DECLARE v_msg VARCHAR(1000);
    DECLARE v_rstatus VARCHAR(20);
    DECLARE v_assigned INT UNSIGNED;
    DECLARE v_app BIGINT UNSIGNED;
    DECLARE v_astatus VARCHAR(30);
    DECLARE v_cur_dec BIGINT UNSIGNED;
    DECLARE v_model_label VARCHAR(10);
    DECLARE v_model_id INT UNSIGNED;
    DECLARE v_pred_id BIGINT UNSIGNED;
    DECLARE v_role VARCHAR(10);
    DECLARE v_dec_id BIGINT UNSIGNED;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        GET DIAGNOSTICS CONDITION 1 v_msg = MESSAGE_TEXT;
        ROLLBACK; SET p_outcome = 'ERROR', p_message = LEFT(v_msg, 1000);
    END;

    SELECT role INTO v_role FROM app_user WHERE user_id = p_officer_id AND is_active;
    IF v_role IS NULL OR v_role NOT IN ('OFFICER','ADMIN') THEN
        SET p_outcome = 'INVALID', p_message = 'User is not an active loan officer'; LEAVE proc;
    END IF;
    IF p_decision IS NULL OR p_decision NOT IN ('APPROVED','REJECTED') THEN
        SET p_outcome = 'INVALID', p_message = 'Decision must be APPROVED or REJECTED'; LEAVE proc;
    END IF;
    IF p_reason IS NULL OR CHAR_LENGTH(TRIM(p_reason)) < 20 THEN
        SET p_outcome = 'INVALID', p_message = 'A written justification of at least 20 characters is required'; LEAVE proc;
    END IF;

    START TRANSACTION;
    SELECT status, assigned_to, application_id INTO v_rstatus, v_assigned, v_app
      FROM review_queue WHERE review_id = p_review_id FOR UPDATE;
    IF v_rstatus IS NULL THEN
        ROLLBACK; SET p_outcome = 'NOT_FOUND', p_message = 'No such review item'; LEAVE proc;
    END IF;
    IF v_rstatus = 'RESOLVED' THEN
        ROLLBACK; SET p_outcome = 'INVALID', p_message = 'Review already resolved (double-submit?)'; LEAVE proc;
    END IF;
    IF v_rstatus = 'IN_PROGRESS' AND v_assigned <> p_officer_id THEN
        ROLLBACK; SET p_outcome = 'INVALID', p_message = 'Claimed by another officer'; LEAVE proc;
    END IF;

    SELECT status, current_decision_id INTO v_astatus, v_cur_dec
      FROM loan_application WHERE application_id = v_app FOR UPDATE;
    IF v_astatus <> 'PENDING_REVIEW' THEN
        ROLLBACK; SET p_outcome = 'INVALID', p_message = CONCAT('Application is ', v_astatus); LEAVE proc;
    END IF;

    SELECT predicted_label, model_id, prediction_id INTO v_model_label, v_model_id, v_pred_id
      FROM model_prediction WHERE application_id = v_app
     ORDER BY prediction_id DESC LIMIT 1;

    INSERT INTO decision (application_id, decision_source, outcome, reason_text, rule_set_id,
                          model_id, prediction_id, decided_by, supersedes_decision_id, is_override)
    VALUES (v_app, 'OFFICER', p_decision, TRIM(p_reason), fn_app_rule_set(v_app),
            v_model_id, v_pred_id, p_officer_id, v_cur_dec,
            (v_model_label IS NOT NULL AND v_model_label <> p_decision));
    SET v_dec_id = LAST_INSERT_ID();

    UPDATE loan_application
       SET status = IF(p_decision = 'APPROVED', 'OFFICER_APPROVED', 'OFFICER_REJECTED'),
           current_decision_id = v_dec_id
     WHERE application_id = v_app;
    UPDATE review_queue
       SET status = 'RESOLVED', assigned_to = p_officer_id, resolved_at = UTC_TIMESTAMP(3),
           resolution_decision_id = v_dec_id
     WHERE review_id = p_review_id;
    COMMIT;
    SET p_outcome = 'OK', p_message = CONCAT('Application ', p_decision,
        IF(v_model_label IS NOT NULL AND v_model_label <> p_decision, ' (overrides model)', ''));
END$$

CREATE PROCEDURE sp_withdraw_application(
    IN  p_app_id  BIGINT UNSIGNED,
    IN  p_reason  VARCHAR(255),
    OUT p_outcome VARCHAR(20),
    OUT p_message VARCHAR(1000))
proc: BEGIN
    DECLARE v_msg VARCHAR(1000);
    DECLARE v_status VARCHAR(30);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        GET DIAGNOSTICS CONDITION 1 v_msg = MESSAGE_TEXT;
        ROLLBACK; SET p_outcome = 'ERROR', p_message = LEFT(v_msg, 1000);
    END;

    START TRANSACTION;
    SELECT status INTO v_status FROM loan_application WHERE application_id = p_app_id FOR UPDATE;
    IF v_status IS NULL THEN
        ROLLBACK; SET p_outcome = 'NOT_FOUND', p_message = 'No such application'; LEAVE proc;
    END IF;
    IF (SELECT is_terminal FROM app_status WHERE status_code = v_status) THEN
        ROLLBACK; SET p_outcome = 'INVALID', p_message = CONCAT('Cannot withdraw: already final (', v_status, ')'); LEAVE proc;
    END IF;
    UPDATE loan_application SET status = 'WITHDRAWN' WHERE application_id = p_app_id;
    UPDATE review_queue SET status = 'RESOLVED', resolved_at = UTC_TIMESTAMP(3)
     WHERE application_id = p_app_id AND status <> 'RESOLVED';
    INSERT INTO audit_log (table_name, record_id, action, payload)
    VALUES ('loan_application', p_app_id, 'UPDATE', JSON_OBJECT('withdrawn_reason', p_reason));
    COMMIT;
    SET p_outcome = 'OK', p_message = 'Withdrawn';
END$$

-- Overdue reviews are ESCALATED, never dropped. Schedule it (see 05) or run manually.
CREATE PROCEDURE sp_escalate_overdue_reviews(OUT p_count INT)
BEGIN
    UPDATE review_queue
       SET status = 'ESCALATED', priority = 1
     WHERE status IN ('OPEN','IN_PROGRESS') AND sla_due_at < UTC_TIMESTAMP(3);
    SET p_count = ROW_COUNT();
    IF p_count > 0 THEN
        INSERT INTO audit_log (table_name, record_id, action, payload)
        VALUES ('review_queue', 0, 'UPDATE', JSON_OBJECT('escalated', p_count));
    END IF;
END$$


-- =====================================================================
-- 5) VERSIONING — rules and models
-- =====================================================================
CREATE PROCEDURE sp_clone_rule_set(
    IN  p_from_id   INT UNSIGNED,
    IN  p_new_label VARCHAR(20),
    IN  p_user      INT UNSIGNED,
    OUT p_new_id    INT UNSIGNED)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    START TRANSACTION;
    INSERT INTO rule_set (version_label, description, is_active, created_by)
    SELECT p_new_label, CONCAT('Cloned from ', version_label), FALSE, p_user
      FROM rule_set WHERE rule_set_id = p_from_id;
    SET p_new_id = LAST_INSERT_ID();
    INSERT INTO policy_rule (rule_set_id, rule_code, fact_key, operator, threshold, severity,
                             on_missing, priority, reason_text, is_active)
    SELECT p_new_id, rule_code, fact_key, operator, threshold, severity,
           on_missing, priority, reason_text, is_active
      FROM policy_rule WHERE rule_set_id = p_from_id;
    COMMIT;
END$$

CREATE PROCEDURE sp_activate_rule_set(IN p_rule_set_id INT UNSIGNED)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    IF NOT EXISTS (SELECT 1 FROM policy_rule WHERE rule_set_id = p_rule_set_id AND is_active) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Refusing to activate a rule set with no active rules';
    END IF;
    START TRANSACTION;
    UPDATE rule_set SET is_active = FALSE WHERE is_active AND rule_set_id <> p_rule_set_id;
    UPDATE rule_set SET is_active = TRUE  WHERE rule_set_id = p_rule_set_id;
    COMMIT;
END$$

CREATE PROCEDURE sp_activate_model(IN p_model_id INT UNSIGNED)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
    IF NOT EXISTS (SELECT 1 FROM model_version WHERE model_id = p_model_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown model_id';
    END IF;
    START TRANSACTION;
    UPDATE model_version SET is_active = FALSE WHERE is_active AND model_id <> p_model_id;
    UPDATE model_version SET is_active = TRUE  WHERE model_id = p_model_id;
    COMMIT;
END$$


-- =====================================================================
-- 6) LAYER 4 — fairness audit (disparate-impact ratio, four-fifths rule)
--   scope ALL_FINAL : final approve/reject outcomes (rules + model + officers)
--   scope MODEL_ONLY: what the model predicted, before any human touched it
--   reference group : the group with the HIGHEST approval rate among
--                     groups that meet p_min_group
-- =====================================================================
CREATE PROCEDURE sp_run_fairness(
    IN  p_attribute  VARCHAR(20),
    IN  p_scope      VARCHAR(20),
    IN  p_from       DATETIME(3),
    IN  p_to         DATETIME(3),
    IN  p_min_group  INT UNSIGNED,
    IN  p_threshold  DECIMAL(4,3),
    IN  p_user       INT UNSIGNED,
    OUT p_run_id     INT UNSIGNED,
    OUT p_message    VARCHAR(1000))
proc: BEGIN
    DECLARE v_ref VARCHAR(30);
    DECLARE v_ref_rate DECIMAL(10,6);
    DECLARE v_flagged INT;
    DECLARE v_groups INT;

    IF p_attribute NOT IN ('gender','age_band','dependents') OR p_scope NOT IN ('ALL_FINAL','MODEL_ONLY') THEN
        SET p_run_id = NULL, p_message = 'Invalid attribute or scope'; LEAVE proc;
    END IF;
    IF p_from IS NULL OR p_to IS NULL OR p_to <= p_from THEN
        SET p_run_id = NULL, p_message = 'Invalid time window'; LEAVE proc;
    END IF;

    DROP TEMPORARY TABLE IF EXISTS tmp_fair;
    CREATE TEMPORARY TABLE tmp_fair (group_value VARCHAR(30) PRIMARY KEY, n INT, n_app INT);

    IF p_scope = 'ALL_FINAL' THEN
        INSERT INTO tmp_fair
        SELECT fn_group_value(p_attribute, a.gender_snapshot, a.age_band, a.dependents_snapshot) g,
               COUNT(*), SUM(d.outcome = 'APPROVED')
          FROM loan_application a
          JOIN decision d ON d.decision_id = a.current_decision_id
         WHERE d.outcome IN ('APPROVED','REJECTED')
           AND d.decided_at >= p_from AND d.decided_at < p_to
         GROUP BY g;
    ELSE
        INSERT INTO tmp_fair
        SELECT fn_group_value(p_attribute, a.gender_snapshot, a.age_band, a.dependents_snapshot) g,
               COUNT(*), SUM(mp.predicted_label = 'APPROVED')
          FROM model_prediction mp
          JOIN loan_application a ON a.application_id = mp.application_id
         WHERE mp.predicted_at >= p_from AND mp.predicted_at < p_to
         GROUP BY g;
    END IF;

    SELECT COUNT(*) INTO v_groups FROM tmp_fair;
    SELECT group_value, n_app / n INTO v_ref, v_ref_rate
      FROM tmp_fair WHERE n >= p_min_group
     ORDER BY n_app / n DESC, n DESC LIMIT 1;

    INSERT INTO fairness_run (attribute_name, scope, window_start, window_end, min_group_size,
                              di_threshold, reference_group, run_by)
    VALUES (p_attribute, p_scope, p_from, p_to, p_min_group, p_threshold, v_ref, p_user);
    SET p_run_id = LAST_INSERT_ID();

    INSERT INTO fairness_result (run_id, group_value, n_decided, n_approved, approval_rate, di_ratio, status)
    SELECT p_run_id, group_value, n, n_app, n_app / n,
           IF(v_ref_rate > 0, (n_app / n) / v_ref_rate, NULL),
           CASE WHEN n < p_min_group                    THEN 'INSUFFICIENT_SAMPLE'
                WHEN v_ref_rate IS NULL OR v_ref_rate = 0 THEN 'NO_APPROVALS_OVERALL'
                WHEN group_value = v_ref                THEN 'REFERENCE'
                WHEN (n_app / n) / v_ref_rate < p_threshold THEN 'FLAGGED'
                ELSE 'OK' END
      FROM tmp_fair;

    SELECT COUNT(*) INTO v_flagged FROM fairness_result WHERE run_id = p_run_id AND status = 'FLAGGED';
    IF v_flagged > 0 THEN
        UPDATE fairness_run SET any_flagged = TRUE WHERE run_id = p_run_id;
        -- surfaced in the tamper-evident log, not hidden
        INSERT INTO audit_log (table_name, record_id, action, payload)
        SELECT 'fairness_run', p_run_id, 'INSERT',
               JSON_OBJECT('alert', 'DISPARATE_IMPACT', 'attribute', p_attribute, 'scope', p_scope,
                           'flagged_groups', JSON_ARRAYAGG(JSON_OBJECT('group', group_value, 'di', di_ratio)))
          FROM fairness_result WHERE run_id = p_run_id AND status = 'FLAGGED';
    END IF;

    DROP TEMPORARY TABLE tmp_fair;
    SET p_message = CASE
        WHEN v_groups = 0 THEN 'No decisions in window'
        WHEN v_ref IS NULL THEN 'No group meets the minimum sample size — result not conclusive'
        WHEN v_flagged > 0 THEN CONCAT(v_flagged, ' group(s) below DI threshold ', p_threshold)
        ELSE 'All groups within threshold' END;
END$$


-- =====================================================================
-- 7) BATCH — run Layer 1 over many RECEIVED applications
--    (rule tuning on historical data, or recovering stuck applications)
-- =====================================================================
CREATE PROCEDURE sp_run_rules_batch(
    IN  p_source VARCHAR(20),
    IN  p_limit  INT UNSIGNED,
    OUT p_done   INT UNSIGNED)
BEGIN
    DECLARE v_id BIGINT UNSIGNED;
    DECLARE v_o VARCHAR(20);
    DECLARE v_m VARCHAR(1000);
    SET p_done = 0;
    batch_loop: WHILE p_done < p_limit DO
        SET v_id = (SELECT application_id FROM loan_application
                     WHERE status = 'RECEIVED' AND source = p_source
                     ORDER BY application_id LIMIT 1);
        IF v_id IS NULL THEN LEAVE batch_loop; END IF;
        CALL sp_run_rule_layer(v_id, v_o, v_m);
        IF v_o = 'ERROR' THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Rule layer error during batch — see sp_run_rule_layer output';
        END IF;
        SET p_done = p_done + 1;
    END WHILE;
END$$

DELIMITER ;
