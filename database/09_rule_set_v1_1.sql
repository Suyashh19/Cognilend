-- =====================================================================
-- CogniLend :: 09_rule_set_v1_1.sql
-- Policy change: R03 (age at loan maturity) limit 65 -> 70.
-- Run after 01-06 (and after 08 if you ran the tests). Safe to re-run.
--
-- Why 70: most home loans run 20-30 years. With a limit of 65, anyone
-- over ~40 asking for a 25-year loan was hard-rejected. 70 is common for
-- Indian home loans and still keeps the rule meaningful.
--
-- This is done the "proper" way: v1.0 is NOT edited (it has already made
-- decisions and is frozen by trg_rule_bu). We clone it into v1.1, change
-- the one rule there, and activate v1.1. Old decisions keep pointing to
-- v1.0, so they stay reproducible.
-- =====================================================================
USE cognilend;

DROP PROCEDURE IF EXISTS sp_install_rule_set_v1_1;
DELIMITER $$
CREATE PROCEDURE sp_install_rule_set_v1_1()
BEGIN
    DECLARE v_base, v_new INT UNSIGNED;

    -- clone from v1.0 by NAME: 08_edge_case_tests.sql leaves its own
    -- temporary clone in the table, so "the active one" is not reliable
    SET v_base = (SELECT rule_set_id FROM rule_set WHERE version_label = 'v1.0');
    SET v_new  = (SELECT rule_set_id FROM rule_set WHERE version_label = 'v1.1');

    IF v_base IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Rule set v1.0 not found: run 01-06 first';
    END IF;

    IF v_new IS NULL THEN
        CALL sp_clone_rule_set(v_base, 'v1.1', 2, v_new);
        UPDATE rule_set
           SET description = 'v1.0 + R03 age-at-maturity limit raised from 65 to 70'
         WHERE rule_set_id = v_new;
        UPDATE policy_rule
           SET threshold   = 70,
               reason_text = 'Applicant would be older than 70 at loan maturity'
         WHERE rule_set_id = v_new AND rule_code = 'R03_MAX_AGE_MATUR';
    END IF;

    CALL sp_activate_rule_set(v_new);
END$$
DELIMITER ;

CALL sp_install_rule_set_v1_1();
DROP PROCEDURE sp_install_rule_set_v1_1;

-- check: v1.1 active, R03 = 70
SELECT rs.version_label, rs.is_active, pr.rule_code, pr.threshold, pr.severity
  FROM rule_set rs JOIN policy_rule pr ON pr.rule_set_id = rs.rule_set_id
 WHERE rs.version_label IN ('v1.0', 'v1.1') AND pr.rule_code = 'R03_MAX_AGE_MATUR'
 ORDER BY rs.rule_set_id;
