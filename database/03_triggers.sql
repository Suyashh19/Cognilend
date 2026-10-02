-- =====================================================================
-- CogniLend :: 03_triggers.sql
-- Integrity guards that hold NO MATTER who writes to the DB
-- (Python app, Workbench, a teammate running a manual UPDATE ...).
-- =====================================================================
USE cognilend;

DELIMITER $$

-- ---------------------------------------------------------------------
-- Tamper-evident hash chain on audit_log
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_audit_hash BEFORE INSERT ON audit_log
FOR EACH ROW
BEGIN
    DECLARE v_prev CHAR(64);
    -- FOR UPDATE on the single head row serialises concurrent writers,
    -- so the chain never forks
    SELECT last_hash INTO v_prev FROM audit_chain_head WHERE id = 1 FOR UPDATE;
    SET NEW.prev_hash  = v_prev;
    SET NEW.created_at = UTC_TIMESTAMP(3);
    SET NEW.db_user    = CURRENT_USER();
    SET NEW.row_hash   = SHA2(CONCAT_WS('|', NEW.prev_hash, NEW.table_name, NEW.record_id, NEW.action,
                                        COALESCE(CAST(NEW.payload AS CHAR), ''),
                                        DATE_FORMAT(NEW.created_at, '%Y-%m-%d %H:%i:%s.%f')), 256);
    UPDATE audit_chain_head SET last_hash = NEW.row_hash WHERE id = 1;
END$$

-- ---------------------------------------------------------------------
-- Append-only tables: block UPDATE and DELETE
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_audit_no_upd BEFORE UPDATE ON audit_log FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_log is append-only'$$
CREATE TRIGGER trg_audit_no_del BEFORE DELETE ON audit_log FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_log is append-only'$$

CREATE TRIGGER trg_decision_no_upd BEFORE UPDATE ON decision FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'decision is append-only: insert a superseding decision instead'$$
CREATE TRIGGER trg_decision_no_del BEFORE DELETE ON decision FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'decision is append-only'$$

CREATE TRIGGER trg_ruleeval_no_upd BEFORE UPDATE ON rule_evaluation FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'rule_evaluation is append-only'$$
CREATE TRIGGER trg_ruleeval_no_del BEFORE DELETE ON rule_evaluation FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'rule_evaluation is append-only'$$

CREATE TRIGGER trg_pred_no_upd BEFORE UPDATE ON model_prediction FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'model_prediction is append-only'$$
CREATE TRIGGER trg_pred_no_del BEFORE DELETE ON model_prediction FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'model_prediction is append-only'$$

CREATE TRIGGER trg_fres_no_upd BEFORE UPDATE ON fairness_result FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'fairness_result is append-only'$$

CREATE TRIGGER trg_app_no_del BEFORE DELETE ON loan_application FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Applications are never deleted (use WITHDRAWN)'$$
CREATE TRIGGER trg_applicant_no_del BEFORE DELETE ON applicant FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Applicants are never hard-deleted (set is_deleted = TRUE)'$$

-- ---------------------------------------------------------------------
-- loan_application: inputs frozen, status follows the state machine,
-- current_decision_id must belong to this application
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_app_bu BEFORE UPDATE ON loan_application
FOR EACH ROW
BEGIN
    DECLARE v_owner BIGINT UNSIGNED;

    IF NOT (OLD.applicant_id <=> NEW.applicant_id)
       OR NOT (OLD.income_monthly <=> NEW.income_monthly)
       OR NOT (OLD.credit_score <=> NEW.credit_score)
       OR NOT (OLD.dtir <=> NEW.dtir)
       OR NOT (OLD.loan_amount <=> NEW.loan_amount)
       OR NOT (OLD.term_months <=> NEW.term_months)
       OR NOT (OLD.property_value <=> NEW.property_value)
       OR NOT (OLD.age_at_application <=> NEW.age_at_application)
       OR NOT (OLD.gender_snapshot <=> NEW.gender_snapshot)
       OR NOT (OLD.credit_type <=> NEW.credit_type)
       OR NOT (OLD.co_applicant_credit_type <=> NEW.co_applicant_credit_type)
       OR NOT (OLD.credit_worthiness <=> NEW.credit_worthiness)
       OR NOT (OLD.loan_type <=> NEW.loan_type)
       OR NOT (OLD.loan_purpose <=> NEW.loan_purpose)
       OR NOT (OLD.occupancy_type <=> NEW.occupancy_type)
       OR NOT (OLD.submitted_at <=> NEW.submitted_at)
       OR NOT (OLD.application_ref <=> NEW.application_ref)
       OR NOT (OLD.dataset_status <=> NEW.dataset_status) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Application inputs are immutable after submission; submit a new application';
    END IF;

    IF NOT (OLD.status <=> NEW.status) THEN
        IF NOT EXISTS (SELECT 1 FROM status_transition
                       WHERE from_status = OLD.status AND to_status = NEW.status) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Illegal application status transition';
        END IF;
        SET NEW.status_updated_at = UTC_TIMESTAMP(3);
    END IF;

    IF NEW.current_decision_id IS NOT NULL AND NOT (OLD.current_decision_id <=> NEW.current_decision_id) THEN
        SELECT application_id INTO v_owner FROM decision WHERE decision_id = NEW.current_decision_id;
        IF NOT (v_owner <=> NEW.application_id) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'current_decision_id belongs to a different application';
        END IF;
    END IF;
    IF OLD.current_decision_id IS NOT NULL AND NEW.current_decision_id IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A recorded decision cannot be unlinked';
    END IF;

    SET NEW.row_version = OLD.row_version + 1;
END$$

CREATE TRIGGER trg_app_au AFTER UPDATE ON loan_application
FOR EACH ROW
BEGIN
    IF NOT (OLD.status <=> NEW.status) THEN
        INSERT INTO audit_log (table_name, record_id, action, payload)
        VALUES ('loan_application', NEW.application_id, 'STATUS_CHANGE',
                JSON_OBJECT('from', OLD.status, 'to', NEW.status,
                            'decision_id', NEW.current_decision_id));
    END IF;
END$$

CREATE TRIGGER trg_app_ai AFTER INSERT ON loan_application
FOR EACH ROW
BEGIN
    -- historical bulk import is not audited row-by-row (148k rows); the
    -- import_batch row is its audit record
    IF NEW.source <> 'HISTORICAL_IMPORT' THEN
        INSERT INTO audit_log (table_name, record_id, action, payload)
        VALUES ('loan_application', NEW.application_id, 'INSERT',
                JSON_OBJECT('ref', NEW.application_ref, 'applicant_id', NEW.applicant_id,
                            'loan_amount', NEW.loan_amount, 'source', NEW.source));
    END IF;
END$$

-- ---------------------------------------------------------------------
-- decision: every decision is mirrored into the hash-chained audit log
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_decision_ai AFTER INSERT ON decision
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (table_name, record_id, action, payload)
    VALUES ('decision', NEW.decision_id, 'INSERT',
            JSON_OBJECT('application_id', NEW.application_id, 'source', NEW.decision_source,
                        'outcome', NEW.outcome, 'confidence', NEW.confidence,
                        'rule_set_id', NEW.rule_set_id, 'model_id', NEW.model_id,
                        'decided_by', NEW.decided_by, 'supersedes', NEW.supersedes_decision_id,
                        'is_override', NEW.is_override, 'reason', NEW.reason_text));
END$$

-- ---------------------------------------------------------------------
-- applicant: identity hash frozen; every profile change audited
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_applicant_bu BEFORE UPDATE ON applicant
FOR EACH ROW
BEGIN
    IF NOT (OLD.id_hash <=> NEW.id_hash) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Applicant identity hash cannot be changed';
    END IF;
    SET NEW.updated_at = UTC_TIMESTAMP(3);
END$$

CREATE TRIGGER trg_applicant_au AFTER UPDATE ON applicant
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (table_name, record_id, action, payload)
    VALUES ('applicant', NEW.applicant_id, 'UPDATE',
            JSON_OBJECT('old', JSON_OBJECT('name', OLD.full_name, 'dob', OLD.date_of_birth,
                                           'gender', OLD.gender, 'dependents', OLD.dependents,
                                           'is_deleted', OLD.is_deleted),
                        'new', JSON_OBJECT('name', NEW.full_name, 'dob', NEW.date_of_birth,
                                           'gender', NEW.gender, 'dependents', NEW.dependents,
                                           'is_deleted', NEW.is_deleted)));
END$$

-- ---------------------------------------------------------------------
-- policy_rule: once a rule set has produced ANY decision it is frozen.
-- Policy change = clone into a new version (sp_clone_rule_set).
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_rule_bi BEFORE INSERT ON policy_rule
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM decision WHERE rule_set_id = NEW.rule_set_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Rule set already used for decisions; clone it into a new version';
    END IF;
END$$

CREATE TRIGGER trg_rule_bu BEFORE UPDATE ON policy_rule
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM decision WHERE rule_set_id = OLD.rule_set_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Rule set already used for decisions; clone it into a new version';
    END IF;
END$$

CREATE TRIGGER trg_rule_bd BEFORE DELETE ON policy_rule
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM decision WHERE rule_set_id = OLD.rule_set_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Rule set already used for decisions; clone it into a new version';
    END IF;
END$$

CREATE TRIGGER trg_rule_au AFTER UPDATE ON policy_rule
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (table_name, record_id, action, payload)
    VALUES ('policy_rule', NEW.rule_id, 'UPDATE',
            JSON_OBJECT('rule_code', NEW.rule_code,
                        'old_threshold', OLD.threshold, 'new_threshold', NEW.threshold,
                        'old_active', OLD.is_active, 'new_active', NEW.is_active));
END$$

CREATE TRIGGER trg_ruleset_au AFTER UPDATE ON rule_set
FOR EACH ROW
BEGIN
    IF NOT (OLD.is_active <=> NEW.is_active) THEN
        INSERT INTO audit_log (table_name, record_id, action, payload)
        VALUES ('rule_set', NEW.rule_set_id, 'UPDATE',
                JSON_OBJECT('version', NEW.version_label, 'is_active', NEW.is_active));
    END IF;
END$$

-- ---------------------------------------------------------------------
-- model_version: a model that has made predictions is frozen
-- (only is_active may change)
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_model_bu BEFORE UPDATE ON model_version
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM model_prediction WHERE model_id = OLD.model_id)
       AND (   NOT (OLD.artifact_sha256      <=> NEW.artifact_sha256)
            OR NOT (OLD.confidence_threshold <=> NEW.confidence_threshold)
            OR NOT (OLD.max_depth            <=> NEW.max_depth)
            OR NOT (OLD.node_count           <=> NEW.node_count)
            OR NOT (OLD.feature_list         <=> NEW.feature_list)
            OR NOT (OLD.version_label        <=> NEW.version_label)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Model already used for predictions; register a new version';
    END IF;
END$$

CREATE TRIGGER trg_model_au AFTER UPDATE ON model_version
FOR EACH ROW
BEGIN
    IF NOT (OLD.is_active <=> NEW.is_active) THEN
        INSERT INTO audit_log (table_name, record_id, action, payload)
        VALUES ('model_version', NEW.model_id, 'UPDATE',
                JSON_OBJECT('model', NEW.model_name, 'version', NEW.version_label, 'is_active', NEW.is_active));
    END IF;
END$$

DELIMITER ;
