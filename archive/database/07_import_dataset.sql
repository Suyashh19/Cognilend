-- =====================================================================
-- CogniLend :: 07_import_dataset.sql
-- Load Kaggle "Loan_Default.csv" (148,670 rows, 34 columns) into the
-- schema: raw text -> staging -> validated -> typed tables.
-- Bad rows are NEVER silently dropped: each lands in import_error with a code.
--
-- STEP A (one-time) — allow LOCAL INFILE
--   1. Run as root:   SET GLOBAL local_infile = 1;
--   2. Workbench: Database > Manage Connections > your connection >
--      Advanced tab > "Others" box, add the line:   OPT_LOCAL_INFILE=1
--      then reconnect.
--   (Fallback if that fails: right-click table stg_loan_raw >
--    "Table Data Import Wizard" — works, but is slow for 148k rows.)
-- =====================================================================
USE cognilend;

DROP PROCEDURE IF EXISTS sp_import_staging;
DELIMITER $$
CREATE PROCEDURE sp_import_staging(IN p_batch_id INT UNSIGNED)
BEGIN
    DECLARE v_loaded, v_rejected INT DEFAULT 0;
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;

    DROP TEMPORARY TABLE IF EXISTS tmp_imp;
    CREATE TEMPORARY TABLE tmp_imp AS
    SELECT s.*,
           CASE
             WHEN src_id IS NULL                                            THEN 'MISSING_ID'
             WHEN rn > 1                                                    THEN 'DUPLICATE_ID'
             WHEN amt IS NULL OR amt <= 0 OR amt > 999999999                THEN 'BAD_LOAN_AMOUNT'
             WHEN term_m IS NULL OR term_m < 1 OR term_m > 600              THEN 'BAD_TERM'
             WHEN label_raw IS NULL OR label_raw NOT IN ('0','1')           THEN 'BAD_LABEL'
             WHEN score_raw IS NOT NULL AND (score IS NULL OR score NOT BETWEEN 300 AND 900) THEN 'BAD_SCORE'
             WHEN income_raw IS NOT NULL AND (income IS NULL OR income < 0) THEN 'BAD_INCOME'
             WHEN prop_raw IS NOT NULL AND (prop IS NULL OR prop <= 0)      THEN 'BAD_PROPERTY'
             WHEN dtir_raw IS NOT NULL AND (dtir IS NULL OR dtir NOT BETWEEN 0 AND 999) THEN 'BAD_DTIR'
             WHEN occ IS NOT NULL AND occ NOT IN ('pr','sr','ir')           THEN 'BAD_CATEGORY'
             WHEN worth IS NOT NULL AND worth NOT IN ('l1','l2')            THEN 'BAD_CATEGORY'
             ELSE NULL END AS err_code
      FROM (
        SELECT r.*,
               ROW_NUMBER() OVER (PARTITION BY r.src_id ORDER BY r.src_id) AS rn,
               IF(amt_raw    REGEXP '^[0-9]+(\\.[0-9]+)?$' AND CHAR_LENGTH(amt_raw)    <= 15, CAST(amt_raw    AS DECIMAL(15,2)), NULL) AS amt,
               IF(term_raw   REGEXP '^[0-9]+(\\.0+)?$'     AND CHAR_LENGTH(term_raw)   <= 6,  CAST(term_raw   AS DECIMAL(10,0)), NULL) AS term_m,
               IF(score_raw  REGEXP '^[0-9]+$'             AND CHAR_LENGTH(score_raw)  <= 4,  CAST(score_raw  AS UNSIGNED),      NULL) AS score,
               IF(income_raw REGEXP '^[0-9]+(\\.[0-9]+)?$' AND CHAR_LENGTH(income_raw) <= 15, CAST(income_raw AS DECIMAL(15,2)), NULL) AS income,
               IF(prop_raw   REGEXP '^[0-9]+(\\.[0-9]+)?$' AND CHAR_LENGTH(prop_raw)   <= 15, CAST(prop_raw   AS DECIMAL(15,2)), NULL) AS prop,
               IF(dtir_raw   REGEXP '^[0-9]+(\\.[0-9]+)?$' AND CHAR_LENGTH(dtir_raw)   <= 8,  CAST(dtir_raw   AS DECIMAL(6,2)),  NULL) AS dtir,
               SHA2(CONCAT('HIST-', r.src_id), 256) AS id_hash
          FROM (
            SELECT NULLIF(TRIM(ID), '')                          AS src_id,
                   NULLIF(TRIM(loan_amount), '')                 AS amt_raw,
                   NULLIF(TRIM(term), '')                        AS term_raw,
                   NULLIF(TRIM(Credit_Score), '')                AS score_raw,
                   NULLIF(TRIM(income), '')                      AS income_raw,
                   NULLIF(TRIM(property_value), '')              AS prop_raw,
                   NULLIF(TRIM(REPLACE(dtir1, '\r', '')), '')    AS dtir_raw,   -- last column: strip Windows CR
                   NULLIF(TRIM(`Status`), '')                    AS label_raw,
                   CASE TRIM(Gender) WHEN 'Male' THEN 'Male' WHEN 'Female' THEN 'Female'
                                     WHEN 'Joint' THEN 'Joint' ELSE 'Not_Disclosed' END AS gender,
                   IF(TRIM(age) IN ('<25','25-34','35-44','45-54','55-64','65-74','>74'), TRIM(age), NULL) AS age_band,
                   NULLIF(UPPER(TRIM(credit_type)), '')          AS credit_type,
                   NULLIF(UPPER(TRIM(co_applicant_credit_type)), '') AS coapp_type,
                   NULLIF(LOWER(TRIM(Credit_Worthiness)), '')    AS worth,
                   NULLIF(LOWER(TRIM(loan_type)), '')            AS loan_type,
                   NULLIF(LOWER(TRIM(loan_purpose)), '')         AS purpose,
                   NULLIF(LOWER(TRIM(occupancy_type)), '')       AS occ
              FROM stg_loan_raw
          ) r
      ) s;
    ALTER TABLE tmp_imp ADD INDEX (id_hash);

    START TRANSACTION;

    INSERT INTO import_error (batch_id, source_id, error_code, detail)
    SELECT p_batch_id, src_id, err_code,
           LEFT(CONCAT_WS(' ', 'amount=', amt_raw, 'term=', term_raw, 'score=', score_raw,
                          'status=', label_raw), 255)
      FROM tmp_imp WHERE err_code IS NOT NULL;
    SET v_rejected = ROW_COUNT();

    -- one synthetic applicant per historical row (dataset has no person ID)
    INSERT INTO applicant (id_hash, full_name, gender)
    SELECT t.id_hash, CONCAT('Historical #', t.src_id), t.gender
      FROM tmp_imp t
     WHERE t.err_code IS NULL
       AND NOT EXISTS (SELECT 1 FROM applicant a WHERE a.id_hash = t.id_hash);

    -- idempotency_key 'HIST-<ID>' makes re-running the import safe
    INSERT INTO loan_application
        (idempotency_key, applicant_id, source, submitted_at, age_band, gender_snapshot,
         income_monthly, credit_score, credit_type, co_applicant_credit_type, credit_worthiness,
         dtir, loan_amount, term_months, loan_type, loan_purpose, property_value, occupancy_type,
         dataset_status)
    SELECT CONCAT('HIST-', t.src_id), a.applicant_id, 'HISTORICAL_IMPORT', UTC_TIMESTAMP(3),
           t.age_band, t.gender, t.income, t.score, t.credit_type, t.coapp_type, t.worth,
           t.dtir, t.amt, t.term_m, t.loan_type, t.purpose, t.prop, t.occ,
           CAST(t.label_raw AS UNSIGNED)
      FROM tmp_imp t
      JOIN applicant a ON a.id_hash = t.id_hash
     WHERE t.err_code IS NULL
       AND NOT EXISTS (SELECT 1 FROM loan_application la WHERE la.idempotency_key = CONCAT('HIST-', t.src_id));
    SET v_loaded = ROW_COUNT();

    UPDATE import_batch
       SET rows_staged = (SELECT COUNT(*) FROM stg_loan_raw),
           rows_loaded = v_loaded, rows_rejected = v_rejected, finished_at = UTC_TIMESTAMP(3)
     WHERE batch_id = p_batch_id;
    COMMIT;

    DROP TEMPORARY TABLE tmp_imp;
    SELECT * FROM import_batch WHERE batch_id = p_batch_id;
END$$
DELIMITER ;

-- =====================================================================
-- STEP B — load the CSV (edit the path!)
-- =====================================================================
TRUNCATE TABLE stg_loan_raw;
INSERT INTO import_batch (file_name) VALUES ('Loan_Default.csv');
SET @batch = LAST_INSERT_ID();

LOAD DATA LOCAL INFILE '/home/tanuja/Desktop/CogniLend/data/Loan_Default.csv'
INTO TABLE stg_loan_raw
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\n'
IGNORE 1 LINES;

-- =====================================================================
-- STEP C — validate and move into the real tables
-- =====================================================================
CALL sp_import_staging(@batch);

-- =====================================================================
-- STEP D — sanity checks (run and READ these before training anything)
-- =====================================================================
-- 1. What went wrong, by error code
SELECT * FROM v_import_quality WHERE batch_id = @batch;

-- 2. Label distribution. In the Kaggle Loan_Default dataset, Status = 1
--    means the loan DEFAULTED (~25 %), NOT "approved". Confirm with your
--    source and fix the synopsis mapping if so.
SELECT dataset_status, COUNT(*) AS n, ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
  FROM loan_application WHERE source = 'HISTORICAL_IMPORT' GROUP BY dataset_status;

-- 3. Target-leakage check: if a column is missing almost only for one
--    class, the model will "cheat" using missingness. Drop such columns.
SELECT `Status`,
       ROUND(100 * AVG(NULLIF(TRIM(rate_of_interest), '')     IS NULL), 2) AS pct_missing_rate,
       ROUND(100 * AVG(NULLIF(TRIM(Interest_rate_spread), '') IS NULL), 2) AS pct_missing_spread,
       ROUND(100 * AVG(NULLIF(TRIM(Upfront_charges), '')      IS NULL), 2) AS pct_missing_upfront,
       ROUND(100 * AVG(NULLIF(TRIM(property_value), '')       IS NULL), 2) AS pct_missing_property,
       ROUND(100 * AVG(NULLIF(TRIM(REPLACE(dtir1,'\r','')),'') IS NULL), 2) AS pct_missing_dtir
  FROM stg_loan_raw GROUP BY `Status`;

-- 4. Dataset LTV vs recomputed LTV (should match; large gaps = data error)
SELECT COUNT(*) AS rows_with_ltv_gap_over_1pct
  FROM stg_loan_raw s
  JOIN loan_application a ON a.idempotency_key = CONCAT('HIST-', TRIM(s.ID))
 WHERE NULLIF(TRIM(s.LTV), '') IS NOT NULL
   AND ABS(CAST(s.LTV AS DECIMAL(20,6)) - a.ltv) > 1;

-- 5. How much would the v1 rule set reject? (run the rule layer on a sample)
--    See README section "Tuning rules on historical data".
