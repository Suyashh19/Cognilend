-- =====================================================================
-- CogniLend :: 02_seed_reference.sql
-- Reference data: statuses, state machine, users, rule set v1, model stub
-- =====================================================================
USE cognilend;

-- ---------------------------------------------------------------------
-- Application lifecycle (state machine)
--
--   RECEIVED ──hard rule fail──► RULE_REJECTED            (terminal)
--      │
--      └─rules pass / soft fail─► PENDING_MODEL
--                                   ├─ high confidence ─► AUTO_APPROVED / AUTO_REJECTED (terminal)
--                                   └─ low conf / soft ─► PENDING_REVIEW
--                                                          └─► OFFICER_APPROVED / OFFICER_REJECTED (terminal)
--   any non-terminal ──► WITHDRAWN (terminal)
--
-- There is deliberately NO edge out of RULE_REJECTED: neither the model
-- nor an officer can overturn a hard policy rule.
-- ---------------------------------------------------------------------
INSERT INTO app_status (status_code, is_terminal, description) VALUES
 ('RECEIVED',         FALSE, 'Submitted, validated, awaiting rule layer'),
 ('RULE_REJECTED',    TRUE,  'Failed at least one HARD policy rule'),
 ('PENDING_MODEL',    FALSE, 'Passed hard rules, awaiting ML prediction'),
 ('PENDING_REVIEW',   FALSE, 'Routed to a human loan officer'),
 ('AUTO_APPROVED',    TRUE,  'Approved by model with high confidence'),
 ('AUTO_REJECTED',    TRUE,  'Rejected by model with high confidence'),
 ('OFFICER_APPROVED', TRUE,  'Approved by loan officer after review'),
 ('OFFICER_REJECTED', TRUE,  'Rejected by loan officer after review'),
 ('WITHDRAWN',        TRUE,  'Withdrawn by applicant before a final decision');

INSERT INTO status_transition (from_status, to_status) VALUES
 ('RECEIVED','RULE_REJECTED'), ('RECEIVED','PENDING_MODEL'), ('RECEIVED','WITHDRAWN'),
 ('PENDING_MODEL','AUTO_APPROVED'), ('PENDING_MODEL','AUTO_REJECTED'),
 ('PENDING_MODEL','PENDING_REVIEW'), ('PENDING_MODEL','WITHDRAWN'),
 ('PENDING_REVIEW','OFFICER_APPROVED'), ('PENDING_REVIEW','OFFICER_REJECTED'),
 ('PENDING_REVIEW','WITHDRAWN');

-- ---------------------------------------------------------------------
-- Users (user_id 1 MUST be the pipeline/system user)
-- ---------------------------------------------------------------------
INSERT INTO app_user (user_id, username, full_name, role) VALUES
 (1, 'pipeline',  'CogniLend Pipeline',  'SYSTEM'),
 (2, 'admin',     'System Administrator','ADMIN'),
 (3, 'officer_a', 'Loan Officer A',      'OFFICER'),
 (4, 'officer_b', 'Loan Officer B',      'OFFICER'),
 (5, 'auditor',   'Compliance Auditor',  'AUDITOR');

-- ---------------------------------------------------------------------
-- Rule set v1
-- Facts available (built in sp_run_rule_layer):
--   age, age_at_maturity, income_monthly, credit_score, dtir, ltv,
--   loan_to_annual_income, is_blacklisted, open_applications,
--   rejections_last_30d, loan_amount, term_months
-- A rule PASSES when  <fact> <operator> <threshold>  is TRUE.
-- Thresholds are starting points — tune them on the training data so the
-- rule layer does not reject a huge share of genuinely good applicants
-- (see v_rule_trigger_stats).
-- ---------------------------------------------------------------------
INSERT INTO rule_set (rule_set_id, version_label, description, is_active, created_by)
VALUES (1, 'v1.0', 'Initial policy: RBI-style eligibility + internal risk appetite', TRUE, 2);

INSERT INTO policy_rule
 (rule_set_id, rule_code, fact_key, operator, threshold, severity, on_missing, priority, reason_text) VALUES
 (1,'R01_BLACKLIST',     'is_blacklisted',        '=',  0,     'HARD','FAIL',  10, 'Applicant is listed in the fraud / blacklist registry'),
 (1,'R02_MIN_AGE',       'age',                   '>=', 21,    'HARD','REFER', 20, 'Applicant is younger than the minimum age of 21'),
 (1,'R03_MAX_AGE_MATUR', 'age_at_maturity',       '<=', 65,    'HARD','SKIP',  30, 'Applicant would be older than 65 at loan maturity'),
 (1,'R04_INCOME',        'income_monthly',        '>',  0,     'HARD','REFER', 40, 'No verifiable income declared'),
 (1,'R05_MIN_SCORE',     'credit_score',          '>=', 550,   'HARD','REFER', 50, 'Credit score below the minimum of 550'),
 (1,'R06_MAX_DTI',       'dtir',                  '<=', 50,    'HARD','REFER', 60, 'Debt-to-income ratio exceeds 50%'),
 (1,'R07_MAX_LTV',       'ltv',                   '<=', 90,    'HARD','SKIP',  70, 'Loan-to-value ratio exceeds 90% of property value'),
 (1,'R08_LOAN_TO_INCOME','loan_to_annual_income', '<=', 5,     'SOFT','SKIP',  80, 'Loan amount is more than 5x annual income'),
 (1,'R09_PARALLEL_APPS', 'open_applications',     '=',  0,     'SOFT','SKIP',  90, 'Applicant has another application in progress (possible loan stacking)'),
 (1,'R10_REAPPLY_ABUSE', 'rejections_last_30d',   '<',  3,     'SOFT','SKIP', 100, 'Three or more rejections in the last 30 days (possible model probing)');

-- ---------------------------------------------------------------------
-- Placeholder model so the pipeline can be tested before G10 delivers.
-- G10 registers the real one via sp_register_model (see 03).
-- ---------------------------------------------------------------------
INSERT INTO model_version
 (model_id, model_name, algorithm, version_label, artifact_sha256, random_seed,
  max_depth, node_count, confidence_threshold, feature_list, is_active, trained_at)
VALUES
 (1, 'cognilend_dt', 'DecisionTree', 'v0-placeholder', REPEAT('0',64), 42,
  4, 15, 0.7000,
  JSON_ARRAY('income_monthly','credit_score','credit_type','co_applicant_credit_type',
             'credit_worthiness','dtir','loan_amount','term_months','loan_type',
             'loan_purpose','property_value','ltv','occupancy_type'),
  TRUE, UTC_TIMESTAMP(3));

-- Sample blacklisted identity (hash of the string 'FRAUDPAN0001')
INSERT INTO fraud_registry (id_hash, reason, source)
VALUES (SHA2('FRAUDPAN0001', 256), 'Confirmed identity fraud (sample entry)', 'INTERNAL');
