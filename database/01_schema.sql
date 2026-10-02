-- =====================================================================
-- CogniLend :: 01_schema.sql
-- Layer 3 (DBMS / Audit) — tables, keys, constraints
-- Target: MySQL 8.0.16+ (CHECK constraints are enforced from 8.0.16)
-- Run order: 01 -> 02 -> 03 -> 04 -> 05 -> (06 tests) -> (07 import)
--
-- Design principles
--   * CHECK constraints reject only PHYSICALLY IMPOSSIBLE data (age 250,
--     negative income). POLICY limits (age < 21, DTI > 50) are rules in
--     policy_rule, so they produce a graceful rejection WITH a reason
--     instead of a crash.
--   * Money is DECIMAL, never FLOAT.
--   * All timestamps are UTC, millisecond precision.
--   * Decisions, rule evaluations, predictions and audit rows are
--     append-only (enforced by triggers in 03_triggers.sql).
--   * Nothing is ever hard-deleted; FKs are RESTRICT (no CASCADE).
-- =====================================================================

DROP DATABASE IF EXISTS cognilend;
CREATE DATABASE cognilend CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE cognilend;

-- ---------------------------------------------------------------------
-- Staff / system users (loan officers, auditors, the pipeline itself)
-- ---------------------------------------------------------------------
CREATE TABLE app_user (
    user_id       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    full_name     VARCHAR(100) NOT NULL,
    role          ENUM('ADMIN','OFFICER','AUDITOR','SYSTEM') NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Applicant master. Raw PAN/Aadhaar is NEVER stored — only SHA-256 hash
-- (computed in the app layer with a secret salt/pepper).
-- ---------------------------------------------------------------------
CREATE TABLE applicant (
    applicant_id   BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    id_hash        CHAR(64)     NOT NULL,          -- SHA-256 hex of PAN
    full_name      VARCHAR(100) NOT NULL,
    date_of_birth  DATE         NULL,              -- NULL for historical rows (dataset has only age bands)
    gender         ENUM('Male','Female','Joint','Not_Disclosed') NOT NULL DEFAULT 'Not_Disclosed',
    dependents     TINYINT UNSIGNED NULL,
    email          VARCHAR(120) NULL,
    phone          VARCHAR(15)  NULL,
    region         VARCHAR(30)  NULL,
    is_deleted     BOOLEAN NOT NULL DEFAULT FALSE, -- soft delete only
    created_at     DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    updated_at     DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    CONSTRAINT uq_applicant_idhash UNIQUE (id_hash),
    CONSTRAINT chk_applicant_hash  CHECK (REGEXP_LIKE(id_hash, '^[0-9a-f]{64}$')),
    CONSTRAINT chk_applicant_deps  CHECK (dependents IS NULL OR dependents <= 20),
    CONSTRAINT chk_applicant_name  CHECK (CHAR_LENGTH(TRIM(full_name)) >= 2),
    CONSTRAINT chk_applicant_email CHECK (email IS NULL OR email LIKE '%_@_%._%'),
    CONSTRAINT chk_applicant_phone CHECK (phone IS NULL OR REGEXP_LIKE(phone, '^[0-9+]{10,15}$'))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Rule sets are VERSIONED. A decision always records which rule set
-- produced it => reproducible even after policy changes.
-- ---------------------------------------------------------------------
CREATE TABLE rule_set (
    rule_set_id   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    version_label VARCHAR(20)  NOT NULL UNIQUE,
    description   VARCHAR(255) NULL,
    is_active     BOOLEAN NOT NULL DEFAULT FALSE,
    -- generated column + UNIQUE = "at most ONE active rule set" (MySQL has
    -- no partial unique index; NULLs are allowed to repeat)
    active_flag   TINYINT GENERATED ALWAYS AS (IF(is_active, 1, NULL)) STORED,
    created_by    INT UNSIGNED NOT NULL,
    created_at    DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    CONSTRAINT uq_one_active_ruleset UNIQUE (active_flag),
    CONSTRAINT fk_ruleset_user FOREIGN KEY (created_by) REFERENCES app_user(user_id)
) ENGINE=InnoDB;

-- A rule = "<fact_key> <operator> <threshold>" must be TRUE to PASS.
-- severity HARD -> fail = reject ; SOFT -> fail = send to human review.
-- on_missing decides what happens when the fact is NULL (missing input).
CREATE TABLE policy_rule (
    rule_id       INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    rule_set_id   INT UNSIGNED NOT NULL,
    rule_code     VARCHAR(30)  NOT NULL,
    fact_key      VARCHAR(40)  NOT NULL,        -- key in the facts JSON built by sp_run_rule_layer
    operator      ENUM('>=','<=','>','<','=','!=') NOT NULL,
    threshold     DECIMAL(15,4) NOT NULL,
    severity      ENUM('HARD','SOFT') NOT NULL,
    on_missing    ENUM('FAIL','REFER','SKIP') NOT NULL DEFAULT 'REFER',
    priority      SMALLINT NOT NULL DEFAULT 100, -- lower = evaluated first
    reason_text   VARCHAR(255) NOT NULL,         -- human-readable adverse-action reason
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_rule_code_per_set UNIQUE (rule_set_id, rule_code),
    CONSTRAINT fk_rule_set FOREIGN KEY (rule_set_id) REFERENCES rule_set(rule_set_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- ML model registry (filled by G10). Hash of the pickled model file
-- proves which exact artifact made a prediction.
-- ---------------------------------------------------------------------
CREATE TABLE model_version (
    model_id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    model_name           VARCHAR(50)  NOT NULL,
    algorithm            VARCHAR(50)  NOT NULL,       -- DecisionTree / RandomForest / XGBoost
    version_label        VARCHAR(20)  NOT NULL,
    artifact_sha256      CHAR(64)     NOT NULL,
    random_seed          INT          NOT NULL,
    max_depth            TINYINT UNSIGNED NULL,
    node_count           SMALLINT UNSIGNED NULL,
    train_accuracy       DECIMAL(5,4) NULL,
    val_accuracy         DECIMAL(5,4) NULL,
    confidence_threshold DECIMAL(5,4) NOT NULL DEFAULT 0.7000,
    feature_list         JSON NOT NULL,
    is_active            BOOLEAN NOT NULL DEFAULT FALSE,
    active_flag          TINYINT GENERATED ALWAYS AS (IF(is_active, 1, NULL)) STORED,
    trained_at           DATETIME(3) NOT NULL,
    registered_at        DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    CONSTRAINT uq_model_version  UNIQUE (model_name, version_label),
    CONSTRAINT uq_one_active_model UNIQUE (active_flag),
    CONSTRAINT chk_model_thresh  CHECK (confidence_threshold BETWEEN 0.5 AND 1.0),
    CONSTRAINT chk_model_acc     CHECK ((train_accuracy IS NULL OR train_accuracy BETWEEN 0 AND 1)
                                    AND (val_accuracy   IS NULL OR val_accuracy   BETWEEN 0 AND 1)),
    CONSTRAINT chk_model_hash    CHECK (REGEXP_LIKE(artifact_sha256, '^[0-9a-f]{64}$'))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Blacklist / fraud registry (hashed IDs). Entries can expire.
-- ---------------------------------------------------------------------
CREATE TABLE fraud_registry (
    entry_id    BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    id_hash     CHAR(64) NOT NULL,
    reason      VARCHAR(255) NOT NULL,
    source      VARCHAR(50)  NOT NULL,
    listed_at   DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    expires_at  DATETIME(3) NULL,               -- NULL = permanent
    INDEX idx_fraud_hash (id_hash)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Allowed status transitions (state machine as DATA, enforced by trigger)
-- ---------------------------------------------------------------------
CREATE TABLE app_status (
    status_code  VARCHAR(30) PRIMARY KEY,
    is_terminal  BOOLEAN NOT NULL,
    description  VARCHAR(255) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE status_transition (
    from_status VARCHAR(30) NOT NULL,
    to_status   VARCHAR(30) NOT NULL,
    PRIMARY KEY (from_status, to_status),
    CONSTRAINT fk_st_from FOREIGN KEY (from_status) REFERENCES app_status(status_code),
    CONSTRAINT fk_st_to   FOREIGN KEY (to_status)   REFERENCES app_status(status_code)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Loan application = IMMUTABLE SNAPSHOT of all inputs at submission
-- time. If the applicant later edits their profile, old decisions
-- still show the exact data they were based on.
-- ---------------------------------------------------------------------
CREATE TABLE loan_application (
    application_id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    application_ref         CHAR(36)    NOT NULL DEFAULT (UUID()),
    idempotency_key         VARCHAR(64) NULL,     -- client-generated; blocks double-submit / replay duplicates
    applicant_id            BIGINT UNSIGNED NOT NULL,
    source                  ENUM('LIVE','HISTORICAL_IMPORT','TEST') NOT NULL DEFAULT 'LIVE',
    submitted_at            DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),

    -- demographic snapshot (used for fairness auditing, NOT as model features)
    age_at_application      TINYINT UNSIGNED NULL,
    age_band                VARCHAR(10) NULL,
    gender_snapshot         ENUM('Male','Female','Joint','Not_Disclosed') NOT NULL DEFAULT 'Not_Disclosed',
    dependents_snapshot     TINYINT UNSIGNED NULL,

    -- financial & credit
    income_monthly          DECIMAL(15,2) NULL,
    credit_score            SMALLINT UNSIGNED NULL,
    credit_type             VARCHAR(10) NULL,     -- EXP / EQUI / CRIF / CIB
    co_applicant_credit_type VARCHAR(10) NULL,
    credit_worthiness       ENUM('l1','l2') NULL,
    dtir                    DECIMAL(6,2) NULL,    -- debt-to-income %

    -- loan
    loan_amount             DECIMAL(15,2) NOT NULL,
    term_months             SMALLINT UNSIGNED NOT NULL,
    loan_type               VARCHAR(10) NULL,
    loan_purpose            VARCHAR(10) NULL,

    -- collateral
    property_value          DECIMAL(15,2) NULL,
    ltv                     DECIMAL(8,2) GENERATED ALWAYS AS
                              (IF(property_value > 0, ROUND(loan_amount / property_value * 100, 2), NULL)) STORED,
    occupancy_type          ENUM('pr','sr','ir') NULL,

    -- workflow
    status                  VARCHAR(30) NOT NULL DEFAULT 'RECEIVED',
    soft_referral           BOOLEAN NOT NULL DEFAULT FALSE, -- a SOFT rule failed => must go to human
    current_decision_id     BIGINT UNSIGNED NULL,           -- the one final decision (FK added below)
    row_version             INT UNSIGNED NOT NULL DEFAULT 0, -- optimistic locking
    status_updated_at       DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),

    -- ground truth for historical rows only (see README: VERIFY label meaning!)
    dataset_status          TINYINT NULL,

    CONSTRAINT uq_app_ref        UNIQUE (application_ref),
    CONSTRAINT uq_app_idem       UNIQUE (idempotency_key),
    CONSTRAINT fk_app_applicant  FOREIGN KEY (applicant_id) REFERENCES applicant(applicant_id),
    CONSTRAINT fk_app_status     FOREIGN KEY (status) REFERENCES app_status(status_code),
    CONSTRAINT chk_app_age       CHECK (age_at_application IS NULL OR age_at_application BETWEEN 0 AND 120),
    CONSTRAINT chk_app_deps      CHECK (dependents_snapshot IS NULL OR dependents_snapshot <= 20),
    CONSTRAINT chk_app_income    CHECK (income_monthly IS NULL OR income_monthly >= 0),
    CONSTRAINT chk_app_score     CHECK (credit_score IS NULL OR credit_score BETWEEN 300 AND 900),
    CONSTRAINT chk_app_dtir      CHECK (dtir IS NULL OR dtir BETWEEN 0 AND 999),
    CONSTRAINT chk_app_amount    CHECK (loan_amount > 0 AND loan_amount <= 999999999),
    CONSTRAINT chk_app_term      CHECK (term_months BETWEEN 1 AND 600),
    CONSTRAINT chk_app_property  CHECK (property_value IS NULL OR property_value > 0),
    CONSTRAINT chk_app_label     CHECK (dataset_status IS NULL OR dataset_status IN (0,1)),
    INDEX idx_app_status (status),
    INDEX idx_app_applicant (applicant_id),
    INDEX idx_app_submitted (submitted_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Layer 1 output: EVERY rule evaluated for EVERY application
-- (not just failures — needed for rule-correctness KPI and to list ALL
-- rejection reasons, which an adverse-action notice requires).
-- ---------------------------------------------------------------------
CREATE TABLE rule_evaluation (
    evaluation_id   BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    application_id  BIGINT UNSIGNED NOT NULL,
    rule_id         INT UNSIGNED NOT NULL,
    outcome         ENUM('PASS','FAIL','MISSING_REFER','MISSING_FAIL','SKIPPED') NOT NULL,
    observed_value  VARCHAR(64) NULL,
    threshold_used  DECIMAL(15,4) NOT NULL,     -- copied: rule may be edited later
    evaluated_at    DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    CONSTRAINT uq_eval_once   UNIQUE (application_id, rule_id),
    CONSTRAINT fk_eval_app    FOREIGN KEY (application_id) REFERENCES loan_application(application_id),
    CONSTRAINT fk_eval_rule   FOREIGN KEY (rule_id)        REFERENCES policy_rule(rule_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Layer 2 output: model prediction with explanation
-- ---------------------------------------------------------------------
CREATE TABLE model_prediction (
    prediction_id    BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    application_id   BIGINT UNSIGNED NOT NULL,
    model_id         INT UNSIGNED NOT NULL,
    predicted_label  ENUM('APPROVED','REJECTED') NOT NULL,
    prob_approve     DECIMAL(6,5) NOT NULL,
    confidence       DECIMAL(6,5) NOT NULL,     -- max(p, 1-p)
    decision_path    JSON NULL,                 -- list of tree splits, e.g. ["credit_score<=612.5", ...]
    top_reasons      JSON NULL,
    latency_ms       INT UNSIGNED NULL,
    predicted_at     DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    CONSTRAINT uq_pred_once  UNIQUE (application_id, model_id),
    CONSTRAINT fk_pred_app   FOREIGN KEY (application_id) REFERENCES loan_application(application_id),
    CONSTRAINT fk_pred_model FOREIGN KEY (model_id)       REFERENCES model_version(model_id),
    CONSTRAINT chk_pred_prob CHECK (prob_approve BETWEEN 0 AND 1),
    CONSTRAINT chk_pred_conf CHECK (confidence BETWEEN 0.5 AND 1)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- DECISION LOG — append-only. An officer override does NOT edit the old
-- row; it inserts a new one that points to what it supersedes.
-- ---------------------------------------------------------------------
CREATE TABLE decision (
    decision_id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    application_id          BIGINT UNSIGNED NOT NULL,
    decision_source         ENUM('RULE','MODEL','OFFICER','SYSTEM_FALLBACK') NOT NULL,
    outcome                 ENUM('APPROVED','REJECTED','REFERRED') NOT NULL,
    confidence              DECIMAL(6,5) NULL,
    reason_text             VARCHAR(1000) NOT NULL,
    rule_set_id             INT UNSIGNED NOT NULL,
    model_id                INT UNSIGNED NULL,
    prediction_id           BIGINT UNSIGNED NULL,
    decided_by              INT UNSIGNED NOT NULL,
    supersedes_decision_id  BIGINT UNSIGNED NULL,
    is_override             BOOLEAN NOT NULL DEFAULT FALSE, -- officer went against the model
    decided_at              DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    CONSTRAINT fk_dec_app     FOREIGN KEY (application_id) REFERENCES loan_application(application_id),
    CONSTRAINT fk_dec_ruleset FOREIGN KEY (rule_set_id)    REFERENCES rule_set(rule_set_id),
    CONSTRAINT fk_dec_model   FOREIGN KEY (model_id)       REFERENCES model_version(model_id),
    CONSTRAINT fk_dec_pred    FOREIGN KEY (prediction_id)  REFERENCES model_prediction(prediction_id),
    CONSTRAINT fk_dec_user    FOREIGN KEY (decided_by)     REFERENCES app_user(user_id),
    CONSTRAINT fk_dec_super   FOREIGN KEY (supersedes_decision_id) REFERENCES decision(decision_id),
    CONSTRAINT chk_dec_conf   CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    CONSTRAINT chk_dec_reason CHECK (CHAR_LENGTH(TRIM(reason_text)) >= 5),
    -- a MODEL decision must say which model & prediction
    CONSTRAINT chk_dec_model  CHECK (decision_source <> 'MODEL' OR (model_id IS NOT NULL AND prediction_id IS NOT NULL)),
    INDEX idx_dec_app (application_id),
    INDEX idx_dec_time (decided_at)
) ENGINE=InnoDB;

ALTER TABLE loan_application
    ADD CONSTRAINT fk_app_current_decision
    FOREIGN KEY (current_decision_id) REFERENCES decision(decision_id);

-- ---------------------------------------------------------------------
-- Human-in-the-loop queue. One open item per application; items are
-- escalated when overdue, NEVER silently dropped.
-- ---------------------------------------------------------------------
CREATE TABLE review_queue (
    review_id       BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    application_id  BIGINT UNSIGNED NOT NULL,
    reason          ENUM('LOW_CONFIDENCE','SOFT_RULE','MISSING_DATA','MODEL_FAILURE','FAIRNESS_FLAG') NOT NULL,
    priority        TINYINT UNSIGNED NOT NULL DEFAULT 3,   -- 1 = highest
    status          ENUM('OPEN','IN_PROGRESS','ESCALATED','RESOLVED') NOT NULL DEFAULT 'OPEN',
    assigned_to     INT UNSIGNED NULL,
    created_at      DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    sla_due_at      DATETIME(3) NOT NULL,
    resolved_at     DATETIME(3) NULL,
    resolution_decision_id BIGINT UNSIGNED NULL,
    CONSTRAINT uq_review_app      UNIQUE (application_id),
    CONSTRAINT fk_review_app      FOREIGN KEY (application_id) REFERENCES loan_application(application_id),
    CONSTRAINT fk_review_user     FOREIGN KEY (assigned_to)    REFERENCES app_user(user_id),
    CONSTRAINT fk_review_decision FOREIGN KEY (resolution_decision_id) REFERENCES decision(decision_id),
    CONSTRAINT chk_review_resolved CHECK ((status = 'RESOLVED') = (resolved_at IS NOT NULL)),
    INDEX idx_review_status (status, sla_due_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Tamper-evident audit log (hash chain). Each row's hash covers the
-- previous row's hash, so editing/deleting any old row breaks the chain
-- (verified by v_audit_chain_check).
-- ---------------------------------------------------------------------
CREATE TABLE audit_log (
    audit_id     BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    table_name   VARCHAR(40) NOT NULL,
    record_id    BIGINT UNSIGNED NOT NULL,
    action       ENUM('INSERT','UPDATE','STATUS_CHANGE','BLOCKED') NOT NULL,
    payload      JSON NULL,
    -- the four columns below are always overwritten by trg_audit_hash
    db_user      VARCHAR(100) NOT NULL DEFAULT '',
    created_at   DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    prev_hash    CHAR(64) NOT NULL DEFAULT '',
    row_hash     CHAR(64) NOT NULL DEFAULT '',
    INDEX idx_audit_record (table_name, record_id)
) ENGINE=InnoDB;

-- Chain head: the latest hash, kept in its own single-row table because a
-- MySQL trigger may not read the table it is inserting into.
CREATE TABLE audit_chain_head (
    id         TINYINT PRIMARY KEY,
    last_hash  CHAR(64) NOT NULL,
    CONSTRAINT chk_chain_single_row CHECK (id = 1)
) ENGINE=InnoDB;
INSERT INTO audit_chain_head (id, last_hash) VALUES (1, REPEAT('0', 64));

-- ---------------------------------------------------------------------
-- Layer 4: fairness audit runs and per-group results
-- ---------------------------------------------------------------------
CREATE TABLE fairness_run (
    run_id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    attribute_name   ENUM('gender','age_band','dependents') NOT NULL,
    scope            ENUM('ALL_FINAL','MODEL_ONLY') NOT NULL,
    window_start     DATETIME(3) NOT NULL,
    window_end       DATETIME(3) NOT NULL,
    min_group_size   INT UNSIGNED NOT NULL,
    di_threshold     DECIMAL(4,3) NOT NULL DEFAULT 0.800,
    reference_group  VARCHAR(30) NULL,
    any_flagged      BOOLEAN NOT NULL DEFAULT FALSE,
    run_by           INT UNSIGNED NOT NULL,
    run_at           DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    CONSTRAINT fk_fr_user FOREIGN KEY (run_by) REFERENCES app_user(user_id),
    CONSTRAINT chk_fr_window CHECK (window_end > window_start)
) ENGINE=InnoDB;

CREATE TABLE fairness_result (
    run_id          INT UNSIGNED NOT NULL,
    group_value     VARCHAR(30) NOT NULL,
    n_decided       INT UNSIGNED NOT NULL,
    n_approved      INT UNSIGNED NOT NULL,
    approval_rate   DECIMAL(6,5) NULL,
    di_ratio        DECIMAL(8,5) NULL,
    status          ENUM('OK','FLAGGED','INSUFFICIENT_SAMPLE','REFERENCE','NO_APPROVALS_OVERALL') NOT NULL,
    PRIMARY KEY (run_id, group_value),
    CONSTRAINT fk_fres_run FOREIGN KEY (run_id) REFERENCES fairness_run(run_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Bulk import of the Kaggle Loan_Default.csv (all text; validated later)
-- ---------------------------------------------------------------------
CREATE TABLE import_batch (
    batch_id     INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    file_name    VARCHAR(255) NOT NULL,
    rows_staged  INT UNSIGNED NOT NULL DEFAULT 0,
    rows_loaded  INT UNSIGNED NOT NULL DEFAULT 0,
    rows_rejected INT UNSIGNED NOT NULL DEFAULT 0,
    started_at   DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
    finished_at  DATETIME(3) NULL
) ENGINE=InnoDB;

CREATE TABLE stg_loan_raw (
    ID VARCHAR(20), `year` VARCHAR(10), loan_limit VARCHAR(10), Gender VARCHAR(30),
    approv_in_adv VARCHAR(10), loan_type VARCHAR(10), loan_purpose VARCHAR(10),
    Credit_Worthiness VARCHAR(10), open_credit VARCHAR(10), business_or_commercial VARCHAR(10),
    loan_amount VARCHAR(30), rate_of_interest VARCHAR(30), Interest_rate_spread VARCHAR(30),
    Upfront_charges VARCHAR(30), term VARCHAR(10), Neg_ammortization VARCHAR(10),
    interest_only VARCHAR(10), lump_sum_payment VARCHAR(10), property_value VARCHAR(30),
    construction_type VARCHAR(10), occupancy_type VARCHAR(10), Secured_by VARCHAR(10),
    total_units VARCHAR(10), income VARCHAR(30), credit_type VARCHAR(10), Credit_Score VARCHAR(10),
    co_applicant_credit_type VARCHAR(10), age VARCHAR(10), submission_of_application VARCHAR(20),
    LTV VARCHAR(30), Region VARCHAR(20), Security_Type VARCHAR(20), `Status` VARCHAR(5), dtir1 VARCHAR(20)
) ENGINE=InnoDB;

CREATE TABLE import_error (
    error_id    BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    batch_id    INT UNSIGNED NOT NULL,
    source_id   VARCHAR(20) NULL,
    error_code  VARCHAR(40) NOT NULL,
    detail      VARCHAR(255) NULL,
    CONSTRAINT fk_ierr_batch FOREIGN KEY (batch_id) REFERENCES import_batch(batch_id),
    INDEX idx_ierr_code (error_code)
) ENGINE=InnoDB;
