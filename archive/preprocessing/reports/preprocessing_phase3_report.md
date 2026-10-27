# Preprocessing Phase 3 Report
## Cleaning and Feature Transformation

| | |
|---|---|
| **Project** | CogniLend – Loan Approval Decision-Support System |
| **Phase** | 3 of 4 (Duplicates, data types, missing values, outliers, transforms, encoding, scaling) |
| **Input data** | `data/raw/loan_applications_raw.csv` (10,000 × 17) |
| **Input reports** | Phase 1 (issues P01–P18) and Phase 2 (decisions + new issues P19–P24) |
| **Code** | `phase3/phase3_clean_transform.ipynb` |
| **Main deliverable** | `data/processed/semi_preprocessed_dataset.csv` (9,847 × 26) |
| **Extra outputs** | `data/processed/cleaned_dataset_original_units.csv` (9,847 × 17), `phase3/transform_params.json` |
| **Plots** | `phase3/plots/` (6 images) |
| **Next phase** | Phase 4 – Feature engineering |

---

## 0. Quick summary (read this first)

- **Rows:** 10,000 → **9,847**. We removed 135 duplicate rows and 18 rows without a target. No other row was deleted.
- **Errors fixed:** 991 extra spaces, 3,904 badly spelled labels, 578 text amounts, 1,819 values of "3+", 95 tenures typed in years, 22 sign errors, plus 113 impossible values. The impossible values were set to missing and then filled.
- **Missing values:** 12,724 before filling → **0**.
  - Blanks that really mean "none" became 0 (no co-applicant, unsecured loan).
  - Gender and Marital_Status became "Unknown" (never guessed).
  - Everything else was filled with medians or modes inside sensible groups.
- **Outliers:** **no row deleted**. The 5 money columns were capped at the 1st and 99th percentile, in the model file only.
- **Transforms:** `log1p` on the 6 columns with skewness > 1. Their skewness dropped from 1.3–2.7 to between −0.3 and 0.8.
- **Encoding:** one-hot for Employment_Type, Loan_Type, Gender and Marital_Status (one reference level dropped each); ordinal for Property_Area.
- **Scaling:** `StandardScaler` on 10 numeric columns. Each now has mean 0 and std 1.
- **Three outputs:**
  1. `semi_preprocessed_dataset.csv`: model-ready, the main deliverable.
  2. `cleaned_dataset_original_units.csv`: clean but still in real ₹ and years. Phase 4 needs it to build ratios, and the rule engine and audit log use it too.
  3. `transform_params.json`: every number we used.
- **Issue log:** 20 of the 24 issues are closed. The 4 still open (P18, P21–P24) are for Phase 4, the fairness audit and the rule engine (Section 8).

---

## 1. What we did and what we did not do

| Done in Phase 3 | Not done (Phase 4) |
|---|---|
| Removed duplicates and rows without a target | Building new features (total income, EMI, FOIR, loan-to-income, collateral cover, age at loan end) |
| Fixed data types and labels | Choosing which features go into the model (feature selection) |
| Fixed or removed impossible values | Removing protected or redundant columns from the model inputs |
| Filled every missing value | PCA or other feature extraction |
| Treated outliers, applied the log transform, encoded, scaled | |

We **did** add one 0/1 column, `is_new_to_credit`. It is not a new feature idea; it is the standard way to deal with a special code (CIBIL −1) before scaling. Without it, scaling would treat −1 as a very low score (P12).

### Why there are two cleaned files
Phase 4 must build ratios like FOIR from **real rupee values**. If it used the capped or scaled numbers, the ratios would be wrong. For example, a rich applicant's capped income would make their FOIR look much higher than it really is. So:

| File | Contents | Use it for |
|---|---|---|
| `cleaned_dataset_original_units.csv` | Clean and filled; **real units** and readable labels; CIBIL −1 kept | Building ratios (Phase 4), bank-rule checks (rule engine), audit log |
| `semi_preprocessed_dataset.csv` | Clean, filled, capped, log-transformed, encoded, scaled | Model features (Phase 4 picks from here) |

Both files have the **same 9,847 rows in the same order**, linked by `Loan_ID` / `loan_id`.

### Note on data leakage
All medians, caps and scaler values were calculated on all 9,847 rows, so that the pipeline produces the agreed final dataset. **When the model is trained, these steps must be fitted on the training split only** and then applied unchanged to the test split. Otherwise test information leaks into training.

---

## 2. The steps in order

```
Raw (10,000 × 17)
  │ A1 remove extra spaces          A2 remove duplicates (−135)      A3 remove rows without target (−18)
  │ A4 fix category labels          A5 fix data types                A6 fix / remove impossible values
  ▼
  │ B  fill missing values (structural → 0, protected → "Unknown", others → group median/mode)
  ▼
cleaned_dataset_original_units.csv (9,847 × 17)   ← saved here, real units
  │ C1 CIBIL −1 → flag + median     C2 cap money columns (1st/99th pct)
  │ C3 log1p if skew > 1            C4 encode categories            C5 standard scaling
  ▼
semi_preprocessed_dataset.csv (9,847 × 26)        ← main deliverable
```

The order matters. For example, the ×12 tenure fix must come before the tenure is filled, and Monthly_Income is filled after Property_Area because its group median uses Property_Area.

---

## 3. Part A – Cleaning

### A1. Extra spaces (P03)
Removed leading and trailing spaces from every text column: **991 cells**.

### A2. Duplicates (P01)
Removed **135 exact duplicate rows** (10,000 → 9,865). Phase 2 had confirmed they are complete copies. After this, `Loan_ID` is unique.

### A3. Rows without a target (P02)
Removed **18 rows** (9,865 → 9,847). We never guess the target.

### A4. Category labels (P03)
We used the `plot_map` from Phases 1 and 2, now on the real data. No spelling was left unmapped.

| Column | Raw spellings → clean | Badly spelled cells fixed | Clean labels |
|---|---|---|---|
| Gender | 11 → 3 | 775 | Male, Female, Transgender |
| Marital_Status | 10 → 4 | 776 | Married, Single, Divorced, Widowed |
| Employment_Type | 12 → 3 | 788 | Salaried, SEP, SENP |
| Loan_Type | 16 → 4 | 788 | Home, Vehicle, Personal, Business |
| Property_Area | 10 → 3 | 777 | Urban, Semi-Urban, Rural |
| **Total** | | **3,904** | |

The spelling counts are after A1, which had already removed the extra spaces. **SEP** = Self-Employed Professional; **SENP** = Self-Employed Non-Professional.

### A5. Data types (P04, P05)

| Column | Before | Fix | After |
|---|---|---|---|
| Loan_Amount | text (578 values like `12,20,000` or `Rs. 27,90,000`) | Removed `Rs.` and commas, then converted to a number | float |
| Dependents | text (`3+` in 1,819 rows) | `3+` → 3, then converted to a number | integer |
| Loan_Status | text | Approved = 1, Rejected = 0 | integer |
| Age, Work_Experience, CIBIL_Score, Loan_Tenure | decimals (`40.0`) | Converted to integers after filling (P06) | integer |

### A6. Impossible values
If the correct value is **clear**, we fix it. If not, we set it to missing and fill it in Part B.

| Issue | Rule | Rows | Action |
|---|---|---|---|
| P07 | Age outside 18–75 | 28 | Set to missing |
| P09 | Monthly_Income below 0 | 22 | **Removed the minus sign** (the values look like normal incomes) |
| P10 | Monthly_Income = 0 | 8 | Set to missing |
| P11 | CIBIL outside 300–900, but not −1 | 32 | Set to missing (−1 is a valid code and is kept) |
| P08 + P19 | Work_Experience below 0, above 50, or above (age − 18) | 45 | Set to missing |
| P13 | Home loan with tenure ≤ 30 | 95 | **× 12** (years → months) |

Some counts are slightly lower than in Phase 1 (for example 28 instead of 29) because the duplicates were removed first.

---

## 4. Part B – Missing values

**Before filling: 12,724 missing cells. After filling: 0.**

| Column | Missing | Type | How it was filled | Evidence |
|---|---|---|---|---|
| Coapplicant_Income | 6,685 | Structural | **0** | Phase 2 Q1 (P14) |
| Collateral_Value – Personal/Business | 3,976 | Structural | **0** | Phase 2 Q2 (P15) |
| Collateral_Value – Home/Vehicle | 205 | Really missing | Loan_Amount ÷ median LTV of its type (Home 0.672, Vehicle 0.851), rounded to ₹10,000 | Phase 2 (P20) |
| Gender | 176 | Protected | **"Unknown"** | Never guess a protected attribute |
| Marital_Status | 118 | Protected | **"Unknown"** | Same reason |
| Property_Area | 148 | Random | Mode (Urban) | Phase 2: random |
| Dependents | 236 | Random | Mode inside Marital_Status (Married → 2, others → 0) | Married people have more dependents |
| Age | 28 | Invalid | Median inside Employment_Type | Age differs by job type |
| Monthly_Income | 107 | Random + invalid | Median inside Employment_Type × Property_Area | Income depends on both (Phase 2 C2) |
| Work_Experience | 341 | Random + invalid | Median inside Employment_Type, then limited to [0, age − 18] | Keeps experience possible for the age |
| Existing_EMI | 247 | Random | Median (₹0) | Most applicants have no existing loan |
| CIBIL_Score | 131 | Random + invalid | Median of scored applicants (739) | −1 rows are not used for the median |
| Loan_Amount | 148 | Random | Median inside Loan_Type | Loan sizes differ a lot by type |
| Loan_Tenure | 178 | Random | Mode inside Loan_Type (Home 240, Vehicle 60, Personal 36, Business 36) | Tenure options differ by type |

The Phase 2 count for Home/Vehicle collateral was 209; it is 205 here because the duplicates are gone.

**Did filling change the data?** No.
![Imputation check](plots/p3_imputation_check.png)

The curves before (valid raw values) and after filling lie on top of each other. Medians: Age 37 → 37, Work_Experience 13 → 13, Monthly_Income ₹55,300 → ₹55,100. The only visible change is a small bump at the Work_Experience median, where 341 values (3.5%) were filled.

**At this point the clean, real-unit table was saved as `cleaned_dataset_original_units.csv`.**

---

## 5. Part C – Transformation (model copy only)

### C1. CIBIL −1 = no credit history (P12)
- New 0/1 column `is_new_to_credit`: **598 applicants** have 1.
- Their CIBIL_Score was then set to the median (739), so the score column stays a normal 436–900 scale.
- This keeps the meaning (Phase 2 showed these applicants have their own approval level of 41.7%) without treating −1 as a very low score.

### C2. Outlier treatment (P17)
IQR outliers in the cleaned data:

| Column | IQR outliers | % | Are they real? | Treatment |
|---|---|---|---|---|
| Monthly_Income | 683 | 6.94 | Yes (high earners) | **Cap 1st/99th pct** |
| Coapplicant_Income | 671 | 6.81 | Yes | **Cap 1st/99th pct** |
| Existing_EMI | 1,144 | 11.62 | Yes | **Cap 1st/99th pct** |
| Loan_Amount | 841 | 8.54 | Yes (home loans, Phase 2) | **Cap 1st/99th pct** |
| Collateral_Value | 988 | 10.03 | Yes (property values) | **Cap 1st/99th pct** |
| Age | 62 | 0.63 | Yes (older applicants) | Keep |
| Work_Experience | 61 | 0.62 | Yes | Keep |
| CIBIL_Score | 234 | 2.38 | Yes (weak borrowers) | Keep |
| Loan_Tenure | 558 | 5.67 | Yes (25–30-year home loans) | Keep |
| Dependents | 0 | 0 | – | Keep |

**Capping limits (values outside are set to the limit):**

| Column | Lower limit (1st pct) | Upper limit (99th pct) | Values changed |
|---|---|---|---|
| Monthly_Income | ₹12,700 | ₹3,33,480 | 192 |
| Coapplicant_Income | ₹0 | ₹1,03,800 | 98 |
| Existing_EMI | ₹0 | ₹59,800 | 98 |
| Loan_Amount | ₹60,000 | ₹1,04,79,400 | 164 |
| Collateral_Value | ₹0 | ₹1,69,10,200 | 99 |

![Outlier capping](plots/p3_outlier_capping.png)

- **Why cap and not delete?** Phase 2 showed these are real customers, such as big home loans and high earners. Deleting them would lose real data, while capping just stops a few very large values from dominating.
- **Why are there still dots after capping?** Capping cuts only the extreme 1% at each end. The IQR rule still marks the long right tail; the log transform in C3 fixes the shape.
- **The capping is only in the model file.** The real-unit file keeps the true values, because the rule engine needs them (for example, the ₹15,000 minimum-income check).

### C3. Transform (log1p) (P17)
**Rule:** apply `log1p(x) = log(1 + x)` if skewness (after capping) is **above 1** and the column has no negative values. The `+1` keeps 0 as 0.

| Column | Skew before | log1p? | Skew after |
|---|---|---|---|
| Age | 0.34 | No | 0.34 |
| Dependents | 0.15 | No | 0.15 |
| Work_Experience | 0.47 | No | 0.47 |
| Monthly_Income | 2.20 | **Yes** | 0.25 |
| Coapplicant_Income | 1.89 | **Yes** | 0.78 |
| Existing_EMI | 2.67 | **Yes** | 0.58 |
| CIBIL_Score | −0.45 | No | −0.45 |
| Loan_Amount | 2.47 | **Yes** | 0.09 |
| Loan_Tenure | 1.34 | **Yes** | 0.30 |
| Collateral_Value | 2.52 | **Yes** | −0.32 |

![Skewness](plots/p3_skewness_before_after.png)

Coapplicant_Income and Existing_EMI still have a big group at 0 (no co-applicant / no loan). That is real information.

### C4. Encoding

| Column | Encoding | New columns | Reference (all 0) |
|---|---|---|---|
| Employment_Type | One-hot | `emp_sep`, `emp_senp` | Salaried |
| Loan_Type | One-hot | `loan_type_home`, `loan_type_vehicle`, `loan_type_business` | Personal |
| Gender ⚠ | One-hot | `gender_female`, `gender_transgender`, `gender_unknown` | Male |
| Marital_Status ⚠ | One-hot | `marital_single`, `marital_divorced`, `marital_widowed`, `marital_unknown` | Married |
| Property_Area | Ordinal | `property_area`: Rural 0, Semi-Urban 1, Urban 2 | – |
| Dependents | Already a number (0–3) | `dependents` | – |
| Loan_Status | Already 1/0 | `loan_status` | – |

- One level of each group is dropped and acts as the reference. This avoids the "dummy variable trap" in linear models.
- ⚠ **Gender and Marital_Status are protected attributes.** They are encoded so the dataset is complete for the **fairness audit**, but **Phase 4 must not use them as model inputs** (RBI Fair Practices Code; Phase 2 P22 and P23).

### C5. Scaling
`StandardScaler`, z = (value − mean) ÷ std, on every numeric column with **more than 3 different values**. The 0/1 columns and the 0–2 `property_area` stay as they are.

| Column | log1p first? | Mean used | Std used |
|---|---|---|---|
| age | no | 37.4754 | 8.7061 |
| dependents | no | 1.3545 | 1.0774 |
| work_experience | no | 13.4170 | 8.3242 |
| monthly_income | yes | 10.9517 | 0.6764 |
| coapplicant_income | yes | 3.3633 | 4.9005 |
| existing_emi | yes | 3.4369 | 4.5020 |
| cibil_score | no | 734.8202 | 63.4487 |
| loan_amount | yes | 13.4833 | 1.2160 |
| loan_tenure_months | yes | 4.1689 | 0.8607 |
| collateral_value | yes | 8.4643 | 7.0469 |

Means and stds are on the log1p scale for the log1p columns. The full-precision values are in `transform_params.json`. After scaling, every column has mean 0 and std 1.

![Scaled columns](plots/p3_scaled_columns.png)

**One column through every step (Monthly_Income):**
![Transform example](plots/p3_transform_example_income.png)

It starts very skewed (real ₹), the extremes are cut by capping, log1p gives a bell shape, and scaling centres it at 0. The small bars at both ends are the capped values.

**To turn a scaled value back into real units** (useful for decision-tree explanations):
- with log1p: `real = exp(z × std + mean) − 1`
- without log1p: `real = z × std + mean`

---

## 6. Output files and data dictionary

### 6.1 `data/processed/semi_preprocessed_dataset.csv` (9,847 × 26) – main deliverable

| Column | Type | Meaning |
|---|---|---|
| `loan_id` | text | Application ID (**not** a model input; join key) |
| `age` | scaled | Age (years) |
| `dependents` | scaled | Dependents (0–3) |
| `work_experience` | scaled | Years of work or business |
| `monthly_income` | capped → log1p → scaled | Applicant's monthly income |
| `coapplicant_income` | capped → log1p → scaled | Co-applicant's income (0 = none) |
| `existing_emi` | capped → log1p → scaled | Existing EMIs (applicant + co-applicant) |
| `cibil_score` | scaled | CIBIL score (no-history rows set to 739) |
| `is_new_to_credit` | 0/1 | 1 = no credit history (original CIBIL −1) |
| `loan_amount` | capped → log1p → scaled | Loan amount asked for |
| `loan_tenure_months` | log1p → scaled | Tenure in months |
| `collateral_value` | capped → log1p → scaled | Collateral value (0 = unsecured) |
| `property_area` | 0/1/2 | Rural / Semi-Urban / Urban |
| `emp_sep`, `emp_senp` | 0/1 | Employment type (reference: Salaried) |
| `loan_type_home`, `loan_type_vehicle`, `loan_type_business` | 0/1 | Loan type (reference: Personal) |
| `gender_female`, `gender_transgender`, `gender_unknown` | 0/1 | ⚠ Audit only (reference: Male) |
| `marital_single`, `marital_divorced`, `marital_widowed`, `marital_unknown` | 0/1 | ⚠ Audit only (reference: Married) |
| `loan_status` | 0/1 | **Target**: 1 = Approved (58.46%) |

### 6.2 `data/processed/cleaned_dataset_original_units.csv` (9,847 × 17)
This file has the same 17 columns as the raw file (same names), cleaned and filled, in **real units**:
- Money in ₹, ages and experience in years, tenure in months, CIBIL in points (−1 kept for no history).
- Labels: Employment_Type = Salaried/SEP/SENP; Loan_Type = Home/Vehicle/Personal/Business; Gender and Marital_Status may be "Unknown".
- Loan_Status is 1/0. No missing values.

### 6.3 `phase3/transform_params.json`
This file holds the category map, all imputation values (group medians and modes, median LTV), the CIBIL replacement (739), the capping limits, the list of log1p columns, the scaler mean and std per column, the encodings and the column renames.

---

## 7. Cleaning log (every step, in order)

| # | Issue | Step | Count | Rows after |
|---|---|---|---|---|
| 1 | P03 | Extra spaces removed (cells) | 991 | 10,000 |
| 2 | P01 | Duplicate rows removed | 135 | 9,865 |
| 3 | P02 | Rows without target removed | 18 | 9,847 |
| 4 | P03 | Badly spelled labels fixed | 3,904 | 9,847 |
| 5 | P04 | Loan_Amount text → number | 578 | 9,847 |
| 6 | P05 | Dependents "3+" → 3 | 1,819 | 9,847 |
| 7 | P07 | Impossible Age → missing | 28 | 9,847 |
| 8 | P09 | Negative income → positive | 22 | 9,847 |
| 9 | P10 | Zero income → missing | 8 | 9,847 |
| 10 | P11 | Invalid CIBIL → missing | 32 | 9,847 |
| 11 | P08 + P19 | Invalid Work_Experience → missing | 45 | 9,847 |
| 12 | P13 | Home tenure years → months | 95 | 9,847 |
| 13 | P14 | Coapplicant_Income blank → 0 | 6,685 | 9,847 |
| 14 | P15 | Collateral blank (Personal/Business) → 0 | 3,976 | 9,847 |
| 15–16 | P16 | Gender / Marital_Status → "Unknown" | 176 / 118 | 9,847 |
| 17–24 | P16 | Area, Dependents, Age, Income, Experience, EMI, CIBIL, Amount, Tenure filled | 148 / 236 / 28 / 107 / 341 / 247 / 131 / 148 / 178 | 9,847 |
| 25 | P20 | Collateral (Home/Vehicle) estimated | 205 | 9,847 |
| 26 | P12 | CIBIL −1 → flag + 739 | 598 | 9,847 |
| 27 | P17 | Money columns capped | 192 / 98 / 98 / 164 / 99 | 9,847 |
| 28 | P17 | log1p on 6 columns | – | 9,847 |
| 29 | – | Encoding (4 one-hot + 1 ordinal) | – | 9,847 |
| 30 | – | StandardScaler (10 columns) | – | 9,847 |

![Row flow](plots/p3_row_flow.png)

---

## 8. Issue log – final status after Phase 3

| ID | Issue | Status | How / where |
|---|---|---|---|
| P01 | Duplicate rows | ✅ Closed | 135 removed |
| P02 | Missing target | ✅ Closed | 18 removed |
| P03 | Spelling variants and spaces | ✅ Closed | 991 spaces + 3,904 labels fixed |
| P04 | Loan_Amount as text | ✅ Closed | 578 converted |
| P05 | Dependents "3+" | ✅ Closed | 1,819 → 3 |
| P06 | Whole numbers as decimals | ✅ Closed | Converted to integers |
| P07 | Impossible Age | ✅ Closed | 28 → missing → filled |
| P08 | Invalid Work_Experience | ✅ Closed | Included in the 45 below |
| P09 | Negative income | ✅ Closed | 22 sign errors fixed |
| P10 | Zero income | ✅ Closed | 8 → missing → filled |
| P11 | Invalid CIBIL | ✅ Closed | 32 → missing → filled |
| P12 | CIBIL −1 | ✅ Closed | `is_new_to_credit` flag + 739 |
| P13 | Tenure in years | ✅ Closed | 95 × 12 |
| P14 | Coapplicant blank | ✅ Closed | 6,685 → 0 |
| P15 | Collateral blank | ✅ Closed | 3,976 → 0 (unsecured) |
| P16 | Small random missing values | ✅ Closed | All filled (group median/mode) |
| P17 | Skew and real outliers | ✅ Closed | Capped 1st/99th pct + log1p; no row deleted |
| P18 | Very small groups (Transgender 60, Divorced 95, Widowed 87) | 🔶 Open | **Fairness audit**: report with care |
| P19 | Experience > age − 18 | ✅ Closed | Included in the 45 set to missing |
| P20 | Collateral really missing (Home/Vehicle) | ✅ Closed | 205 estimated from the median LTV |
| P21 | Redundant pairs (Age ↔ Work_Experience 0.94; Loan_Amount ↔ Collateral 0.98) | 🔶 Open | **Phase 4** (feature selection) |
| P22 | Marital_Status and Dependents act as "age in disguise" | 🔶 Open | **Phase 4**: do not use as model inputs |
| P23 | Gender gap remains inside income groups | 🔶 Open | **Fairness audit** on model predictions |
| P24 | Past approvals that break hard rules | 🔶 Open | **Rule engine** must override; Phase 4 should be aware |

---

## 9. Hand-over to Phase 4 (feature engineering)

**Which file to use for what:**

| Task in Phase 4 | Use this |
|---|---|
| Build ratio features (total income, proposed EMI, FOIR, loan-to-income, collateral cover, age at loan end) | `cleaned_dataset_original_units.csv`, which has real values. **Do not** build ratios from the capped or scaled file. |
| Columns that are already model-ready | `semi_preprocessed_dataset.csv`: `work_experience`, `cibil_score`, `is_new_to_credit`, `loan_tenure_months`, `emp_*`, `loan_type_*`, and the others in 6.1 |
| Join the two | Same row order; key `Loan_ID` = `loan_id` |

**Rules to reuse for the new features**, so all model features are treated the same way:
1. **Cap** extreme values. Money-like features: 1st/99th percentile. Ratios: a sensible domain limit, chosen in Phase 4.
2. Apply **log1p** if skewness > 1 and there are no negative values.
3. Apply **StandardScaler** to columns with more than 3 different values. Save the mean and std so values can be turned back into real units.
4. **Do not scale again** the columns that are already scaled.

**Things Phase 4 must decide (open issues):**
- **P22 / P23:** remove `gender_*` and `marital_*` from the model inputs. They stay in the data only for the audit.
- **P21:** Age ↔ Work_Experience (0.94) and Loan_Amount ↔ Collateral_Value (0.98) are redundant. Keep one of each pair, or replace the pair with a ratio.
- Phase 2 evidence for new features:
  - loan size vs income: 81.6% vs 36.7% approval (Phase 2, 6.3)
  - EMI vs income (Phase 2, 6.4)
  - loan vs collateral: 2.8% vs 57.1% (Phase 2, 6.5)
  - age + tenure: 61+ → 24.4%, 360 months → 32.6% (Phase 2, 4.3)
- `loan_id` must be dropped before `fit()`, but kept in the final file for the audit trail.

**For the rule engine team:** run the bank and RBI rules on `cleaned_dataset_original_units.csv`, which has real ₹ values, real ages and CIBIL with −1 kept. Never run them on the scaled file.

---

## 10. Files produced in Phase 3

| File | What it is |
|---|---|
| `phase3/phase3_clean_transform.ipynb` | All Phase 3 code with outputs |
| `phase3/preprocessing_phase3_report.md` | This report |
| `phase3/transform_params.json` | Every value used (medians, caps, scaler, encodings) |
| `phase3/plots/*.png` | 6 plots used in this report |
| `data/processed/semi_preprocessed_dataset.csv` | **Main deliverable** (9,847 × 26) |
| `data/processed/cleaned_dataset_original_units.csv` | Clean data in real units (9,847 × 17) |

**How to run:** open the notebook from inside the `phase3` folder and run all cells. It reads `../data/raw/loan_applications_raw.csv` and writes to `../data/processed/`. Libraries used: pandas, numpy, matplotlib, seaborn, scikit-learn.
