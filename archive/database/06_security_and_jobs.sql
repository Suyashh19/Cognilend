-- =====================================================================
-- CogniLend :: 06_security_and_jobs.sql
-- Least-privilege DB accounts + scheduled maintenance job.
-- CHANGE THE PASSWORDS before running. Never commit real passwords to Git.
-- =====================================================================
USE cognilend;

-- ---------------------------------------------------------------------
-- Roles. Procedures run with the definer's rights (SQL SECURITY DEFINER,
-- the default), so the app accounts only need EXECUTE — they get NO
-- direct INSERT/UPDATE/DELETE on any table. The only way to change data
-- is through the validated procedures.
-- ---------------------------------------------------------------------
CREATE ROLE IF NOT EXISTS cl_pipeline, cl_ml, cl_officer, cl_auditor;

-- Pipeline (Flask/Streamlit backend)
GRANT EXECUTE ON PROCEDURE cognilend.sp_submit_application   TO cl_pipeline;
GRANT EXECUTE ON PROCEDURE cognilend.sp_run_rule_layer       TO cl_pipeline;
GRANT EXECUTE ON PROCEDURE cognilend.sp_record_prediction    TO cl_pipeline;
GRANT EXECUTE ON PROCEDURE cognilend.sp_record_model_failure TO cl_pipeline;
GRANT EXECUTE ON PROCEDURE cognilend.sp_withdraw_application TO cl_pipeline;
GRANT SELECT  ON cognilend.v_decision_explanation            TO cl_pipeline;
GRANT SELECT  ON cognilend.v_model_features                  TO cl_pipeline;
GRANT SELECT  ON cognilend.model_version                     TO cl_pipeline;

-- ML team (G10): read features WITHOUT protected attributes, register models
GRANT SELECT ON cognilend.v_model_features TO cl_ml;
GRANT SELECT, INSERT ON cognilend.model_version TO cl_ml;
GRANT EXECUTE ON PROCEDURE cognilend.sp_activate_model TO cl_ml;

-- Loan officers
GRANT EXECUTE ON PROCEDURE cognilend.sp_claim_review   TO cl_officer;
GRANT EXECUTE ON PROCEDURE cognilend.sp_resolve_review TO cl_officer;
GRANT SELECT  ON cognilend.v_review_backlog            TO cl_officer;
GRANT SELECT  ON cognilend.v_decision_explanation      TO cl_officer;

-- Auditors / fairness team (G15): read everything, change nothing
GRANT SELECT ON cognilend.* TO cl_auditor;
GRANT EXECUTE ON PROCEDURE cognilend.sp_run_fairness TO cl_auditor;
GRANT EXECUTE ON PROCEDURE cognilend.sp_escalate_overdue_reviews TO cl_auditor;

-- ---------------------------------------------------------------------
-- Login accounts (localhost only)
-- ---------------------------------------------------------------------
CREATE USER IF NOT EXISTS 'cl_app'@'localhost'     IDENTIFIED BY 'ChangeMe_App#2026';
CREATE USER IF NOT EXISTS 'cl_ml_user'@'localhost' IDENTIFIED BY 'ChangeMe_ML#2026';
CREATE USER IF NOT EXISTS 'cl_officer'@'localhost' IDENTIFIED BY 'ChangeMe_Off#2026';
CREATE USER IF NOT EXISTS 'cl_audit'@'localhost'   IDENTIFIED BY 'ChangeMe_Aud#2026';

GRANT cl_pipeline TO 'cl_app'@'localhost';
GRANT cl_ml       TO 'cl_ml_user'@'localhost';
GRANT cl_officer  TO 'cl_officer'@'localhost';
GRANT cl_auditor  TO 'cl_audit'@'localhost';

SET DEFAULT ROLE ALL TO 'cl_app'@'localhost', 'cl_ml_user'@'localhost',
                        'cl_officer'@'localhost', 'cl_audit'@'localhost';

-- ---------------------------------------------------------------------
-- Hourly job: escalate overdue human reviews (never drop them)
-- Needs the event scheduler (ON by default in MySQL 8; check with
-- SHOW VARIABLES LIKE 'event_scheduler';)
-- ---------------------------------------------------------------------
DROP EVENT IF EXISTS ev_escalate_reviews;
CREATE EVENT ev_escalate_reviews
    ON SCHEDULE EVERY 1 HOUR
    DO CALL sp_escalate_overdue_reviews(@escalated);
