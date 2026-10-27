# Loan Approval Dataset — Raw to Final Preprocessing Report

**Project:** Hybrid (rule + ML) loan-approval decision-support system
**Scope of this report:** what is in the raw dataset, what is wrong with it on purpose, and every step that turned it into the model-ready dataset. EDA (Phases 1–2) is left for you to do; this report covers the Phase 3 and Phase 4 operations whose output you'll reproduce with your pipeline.

---

## 0. Deliverables

| File | Shape | What it is |
|---|---|---|
| `loan_applications_raw.csv` | **10,000 × 17** | `Loan_ID` + **15 features** + `Loan_Status`. A loan origination system (LOS) style export with realistic data-quality problems. It is the input to your pipeline. |
| `loan_applications_final.csv` | **9,847 × 16** | `loan_id` + **14 model features** + `loan_status`. Cleaned, imputed, engineered, encoded, transformed and scaled. It is the expected output of your pipeline. |
| `report.md` | — | This document. |

`loan_id` in the final file is an identifier and **must be dropped before `fit()`**. It's kept so that every prediction can be joined back to the raw record for the audit trail (requirement d) and to the protected attributes for the fairness audit (requirement e).

---

## 1. Raw dataset: the 15 features

The features follow what an Indian retail bank's credit appraisal actually checks: KYC and demographics, income and obligations (FOIR), bureau score (CIBIL), the loan asked for, and security (LTV).

| # | Column | Type | Unit / values | Why an Indian bank checks it |
|---|---|---|---|---|
| — | `Loan_ID` | ID | `LN2025xxxxxx` | Application reference number (audit trail key) |
| 1 | `Age` | numeric | years | Minimum entry age (21) and **age at loan maturity** (60 salaried / 65 self-employed) |
| 2 | `Gender` | categorical | Male / Female / Transgender | Collected on KYC forms (the third-gender option is mandated). **Protected**: used only for the fairness audit |
| 3 | `Marital_Status` | categorical | Married / Single / Divorced / Widowed | Collected on application; spouse is often a co-applicant. **Protected**, for the audit only |
| 4 | `Dependents` | categorical-ordinal | 0, 1, 2, `3+` | Household burden and net disposable income |
| 5 | `Employment_Type` | categorical | Salaried / Self-Employed Professional (SEP) / Self-Employed Non-Professional (SENP) | The standard Indian bank segmentation. Each segment gets different income documents (salary slips vs ITR) and different age limits |
| 6 | `Work_Experience` | numeric | years | Salaried: total experience (minimum 1 yr). SEP/SENP: business vintage (minimum 3 yrs of ITR) |
| 7 | `Monthly_Income` | numeric | ₹ net per month | Repayment capacity |
| 8 | `Coapplicant_Income` | numeric | ₹ net per month | Income clubbing (spouse or parent), common for home loans |
| 9 | `Existing_EMI` | numeric | ₹ per month | Existing obligations from the bureau report, the numerator of FOIR |
| 10 | `CIBIL_Score` | numeric | 300–900; **−1 = no credit history (NTC)** | Bureau score. −1 is the real bureau convention for new-to-credit applicants |
| 11 | `Loan_Type` | categorical | Home / Vehicle / Personal / Business Loan | Product. Decides whether the loan is secured and which LTV rule applies |
| 12 | `Loan_Amount` | numeric | ₹ | Amount requested |
| 13 | `Loan_Tenure` | numeric | months | Drives the EMI and age at maturity |
| 14 | `Collateral_Value` | numeric | ₹ (blank = unsecured) | Property or vehicle value. Needed for **LTV** (RBI caps for housing loans) |
| 15 | `Property_Area` | categorical | Urban / Semi-Urban / Rural | Location of the applicant or property |
| — | `Loan_Status` | target | Approved / Rejected | Historical credit decision |

### 1.1 How the raw data was generated (so you know the ground truth)

1. **Applicants were simulated** with realistic dependencies. Income is log-normal and depends on segment (SEP > SENP > Salaried), location (Urban > Semi-Urban > Rural), and experience. It also carries a ~15% gender income gap. The NTC rate is higher for applicants under 25 and in rural areas. Loan size is a multiple of income per product. Home-loan LTV follows a Beta distribution, and some applications exceed the RBI caps.
2. **The historical decision was generated in two stages**, the same way your system will work:
   - **Hard policy rules** (Section 7). Any violation meant the application was rejected, except for about 3% "legacy deviations" that were approved anyway.
   - **A soft credit score** (logistic in CIBIL, FOIR, income, collateral coverage, experience, segment, product, area, NTC and dependents). The label was then **sampled** from that probability, so the labels carry realistic noise, as underwriter judgement does.
3. **A small historical gender bias was injected on purpose.** Its size is −0.35 logit for Female and −0.50 for Transgender in the soft-score stage. It gives your fairness audit (requirement e) a known signal to detect. See Section 8.
4. **The data was then corrupted** (Section 2).

Class balance after cleaning: **58.5% Approved / 41.5% Rejected**. That is mild imbalance.

---

## 2. Data-quality issues in the raw file

Counts are measured on the raw file (10,000 rows).

| # | Issue | Column(s) | Count | How you will see it in EDA |
|---|---|---|---|---|
| 1 | Exact duplicate rows (double-submitted applications) | all | **135** | `df.duplicated().sum()`, duplicated `Loan_ID` |
| 2 | Missing target (decision not recorded) | `Loan_Status` | **18** | `isna()` on the target |
| 3 | Leading or trailing whitespace | the 5 text categoricals | ~195–202 per column | `'Male '` ≠ `'Male'` in `value_counts()` |
| 4 | Inconsistent category labels | Gender (25 raw spellings → 3), Marital (25 → 4), Employment (27 → 3), Loan_Type (36 → 4), Area (24 → 3) | ~8% of cells | e.g. `M`, `male`, `MALE`; `HL`, `Housing Loan`; `Service` = Salaried; `SENP`, `Business Owner`; `Semiurban` |
| 5 | Numbers stored as text in Indian digit grouping | `Loan_Amount` | **584** (94 with a `Rs.` prefix) | dtype `object`; values like `"12,50,000"`, `"Rs. 27,90,000"` |
| 6 | Mixed-type category | `Dependents` | 1,840 × `"3+"` | dtype `object` |
| 7 | Impossible ages | `Age` | **29** | values −30, 0, 1, 5, 150, 200, 999 |
| 8 | Sign error | `Monthly_Income` | **22** negative | `min() < 0` |
| 9 | Zero income | `Monthly_Income` | **8** | `== 0` |
| 10 | Out-of-range bureau score | `CIBIL_Score` | **33** | 0, 100, 999, 1000, 9999 (valid range is 300–900, plus −1) |
| 11 | Sentinel value, **not an error** | `CIBIL_Score` | **602** × `−1` | spike at −1 on the histogram |
| 12 | Experience impossible for age | `Work_Experience` | **45** (after bad ages are nulled) | negative values, or `Work_Experience > Age − 18` |
| 13 | **Unit error**: home-loan tenure keyed in *years* | `Loan_Tenure` | **95** | Home loans with tenure 10/15/20/25/30 "months" |
| 14 | Random missing values (MCAR/MAR) | Gender 1.8%, Marital 1.2%, Dependents 2.4%, Work_Experience 3.0%, Monthly_Income 1.0%, Existing_EMI 2.5%, CIBIL 1.0%, Loan_Amount 1.5%, Loan_Tenure 1.8%, Property_Area 1.5% | ~1,770 cells | `isna().mean()` |
| 15 | **Structural** missing values (blank means "none") | `Coapplicant_Income` **67.9%**, `Collateral_Value` **42.5%** | — | Missingness depends on the loan type or on having a co-applicant. **Don't drop these columns.** |
| 16 | Legitimate extreme values (high-net-worth applicants, ₹3 Cr home loans) | incomes, EMI, loan amount, collateral | see §3.8 | long right tails, skew > 1 |

---

## 3. Phase 3: Clean and transform

Step counts below are measured at the moment each step ran, so they're after duplicate removal.

### 3.1 Whitespace
Stripped leading and trailing spaces from every text column; empty strings became `NaN`.

### 3.2 Duplicates
Removed **135** exact duplicate rows. Afterwards `Loan_ID` is unique (0 duplicated IDs).

### 3.3 Target
Dropped **18** rows with no recorded decision. The label is never imputed. Encoded `Approved → 1`, `Rejected → 0`.

### 3.4 Category standardisation
Each column is lower-cased and then mapped through an explicit dictionary to canonical labels. The code asserts that no value is left unmapped. For example:
- Gender: `m, male, MALE → Male`; `f, female → Female`; `tg, transgender → Transgender`
- Employment: `salaried, service → Salaried`; `sep, self employed professional → SEP`; `senp, self employed business, business owner → SENP`
- Loan type: `hl, housing loan, home loan → Home`; `auto loan, car loan → Vehicle`; `pl, personal → Personal`; `bl, msme loan → Business`
- Area: `semiurban, semi urban → Semi-Urban`

### 3.5 Dtype fixes
- `Loan_Amount`: removed `Rs.`, commas and spaces, then converted to numeric (578 text cells after deduplication)
- `Dependents`: `"3+" → 3`, then converted to integer (a count, since "3 or more" is capped at 3)
- All numeric columns went through `pd.to_numeric`. After imputation, `Age`, `Dependents`, `Work_Experience`, `CIBIL_Score` and `Loan_Tenure` were cast to `int`.

### 3.6 Domain validity rules
An invalid value is recovered when the error is unambiguous; otherwise it is set to `NaN` and imputed.

| Rule | Count | Action |
|---|---|---|
| Age outside 18–75 | 28 | → NaN |
| Monthly_Income < 0 (sign error) | 22 | **recovered with `abs()`** |
| Monthly_Income = 0 | 8 | → NaN |
| CIBIL outside 300–900, excluding −1 | 32 | → NaN (−1 is kept, see §4.1) |
| Work_Experience < 0, > 50, or > Age − 18 | 45 | → NaN |
| Home loan with tenure ≤ 30 (keyed in years) | 95 | **recovered with × 12** |

### 3.7 Missing-value imputation
Groups are built from columns that have no missing values of their own.

| Column | Missing (incl. nulled invalids) | Type | Strategy |
|---|---|---|---|
| `Coapplicant_Income` | 6,685 (67.9%) | structural | **0**: no earning co-applicant |
| `Collateral_Value` | 4,181 | mostly structural | Personal and Business loans: **0** (unsecured; 3,976 rows). Collateral that isn't on record is treated as no collateral, which is the conservative credit choice. Home and Vehicle loans (205 rows, which are always secured): `Loan_Amount / median LTV of that loan type` (Home 0.672, Vehicle 0.851) |
| `Gender` | 176 | MCAR | **"Unknown"**. A protected attribute is never guessed |
| `Marital_Status` | 118 | MCAR | **"Unknown"** (same reason) |
| `Property_Area` | 148 | MCAR | mode (Urban) |
| `Dependents` | 236 | MAR | mode within Marital_Status (Married → 2, others → 0) |
| `Age` | 28 | invalid → NaN | median within Employment_Type |
| `Monthly_Income` | 107 | MCAR + invalid | median within Employment_Type × Property_Area |
| `Work_Experience` | 341 | MCAR + invalid | median within Employment_Type, then clipped to [0, Age − 18] |
| `Existing_EMI` | 247 | MCAR | median (₹0, since 62% of applicants have no existing loan) |
| `CIBIL_Score` | 131 | MCAR + invalid | median of *scored* applicants (739). NTC rows (−1) are not missing and are not touched here |
| `Loan_Amount` | 148 | MCAR | median within Loan_Type |
| `Loan_Tenure` | 178 | MCAR | mode within Loan_Type (Home 240, Vehicle 60, Personal 36, Business 36) |

After this step the table has **0 missing values**.

**The cleaned, imputed table in original units is the Phase 3 `semi_preprocessed_dataset`.** The rule engine and the audit log must read this version, not the scaled one (see §6).

### 3.8 Outlier treatment
Outliers were handled in two ways, depending on whether they are errors or real values.

- **Errors** (impossible values) were already handled by the validity rules in §3.6.
- **Legitimate extremes are flagged, not removed.** The IQR rule flags Monthly_Income 683, Loan_Amount (within type) 648, Collateral_Value 360, Existing_EMI (non-zero) 220 and Coapplicant_Income (earning) 134. These are real high-income applicants and large home loans, so they are kept in the raw columns.
- **Capping is applied to the model features only, after the ratios are built:**

| Feature | Treatment | Values capped |
|---|---|---|
| `total_income` | winsorised at the 1st/99th percentile (₹14,000 – ₹3,59,258) | 197 |
| `foir` | capped at 1.50 | 29 |
| `collateral_coverage` | capped at 5.0 | 5 |
| `loan_to_income` | capped at the 99th percentile (5.62 years of income) | 99 |

> **Ordering pitfall:** build ratios from the *real* values before winsorising their components. Suppose an applicant earns ₹10 L/month and pays ₹5 L of EMI, so FOIR is 50%. If income is winsorised to ₹3.6 L first, FOIR becomes 139% and the applicant is wrongly made to look over-leveraged.

---

## 4. Phase 4: Feature engineering

### 4.1 Feature construction
All features were built from the cleaned values in original units.

| New feature | Formula | Banking meaning |
|---|---|---|
| `total_income` | Monthly_Income + Coapplicant_Income | Eligibility income (clubbed) |
| `proposed_emi` | `P·r·(1+r)^n / ((1+r)^n − 1)`, r = indicative annual rate / 12 (Home 8.5%, Vehicle 9.5%, Personal 11.5%, Business 13%) | EMI of the loan being applied for |
| **`foir`** | (Existing_EMI + proposed_emi) / total_income | **Fixed Obligation to Income Ratio**, the main affordability metric in Indian underwriting |
| **`collateral_coverage`** | Collateral_Value / Loan_Amount (0 = unsecured) | Inverse of LTV. It is defined for unsecured loans too, whereas LTV would divide by zero |
| `loan_to_income` | Loan_Amount / (12 × total_income) | Loan size in years of income, independent of loan size |
| **`age_at_maturity`** | Age + Loan_Tenure / 12 | The age variable banks actually set policy on |
| `is_new_to_credit` | CIBIL_Score == −1 | NTC flag. The −1 is then replaced by the median score (739), so the numeric scale stays continuous and the flag carries the information |
| `has_coapplicant`, `is_secured` | > 0 indicators | Candidate flags |

Together with the cleaned columns and one-hot dummies, this gave **27 candidate features**.

### 4.2 Feature selection (27 → 14)
The selection was a four-step funnel. Mutual information (MI) and Random-Forest permutation importance (PI, on a 25% hold-out) were computed for all 27 candidates.

| Step | Rule | Dropped |
|---|---|---|
| **0. Fairness** | Protected attributes are never model inputs (RBI Fair Practices Code: lenders must not discriminate on grounds of sex, caste or religion) | `Gender`, `Marital_Status` (kept in raw for the audit) |
| **A. Ratio supersedes its components** | Underwriting decides on ratios, not on the raw amounts | `monthly_income`, `coapplicant_income` (→ total_income); `existing_emi`, `proposed_emi` (→ foir); `collateral_value` (→ coverage); `loan_amount` (→ loan_to_income; MI 0.030 vs 0.006) |
| **B. Redundancy** (\|Spearman ρ\| > 0.80, drop the member with lower MI) | | `age` (ρ = 0.94 with work_experience; MI 0.039 vs 0.068; the age information stays in `age_at_maturity`), `is_secured` (ρ = 0.88 with collateral_coverage) |
| **C. Relevance** (MI < 0.005 **and** PI < 0.001) | Both measures negligible | `dependents` (MI 0.0025), `property_area` (MI 0.0029), `has_coapplicant` (MI 0.0009) |
| **D. One-hot groups** | Keep a group if its joint PI ≥ 0.001; drop one reference level | Employment kept (group PI 0.0081), reference = Salaried. Loan type kept (group PI 0.0027), reference = Personal |

**Result:** the highest pairwise |ρ| among the 14 final features is 0.78. Selection costs no accuracy: a Random Forest with 5-fold CV scores **0.881 on all 27 candidates vs 0.879 on the selected 14**.

Top features by MI: `foir` 0.118, `cibil_score` 0.107, `work_experience` 0.068, `age_at_maturity` 0.038, `loan_to_income` 0.030. This matches how Indian underwriting ranks affordability and bureau history.

Dropping `property_area` has a side benefit: it removes a possible geographic proxy for protected groups.

### 4.3 Feature extraction (evaluated, not applied)
PCA on the 8 continuous final features needs **5 of 8 components for 90% of the variance** (cumulative: 0.36, 0.56, 0.70, 0.83, 0.91, …). That is a weak reduction. Principal components are also linear blends such as "0.4·foir − 0.3·cibil + …", which would break requirement (b), a traceable decision path. PCA was therefore rejected. Record this reasoning in your Phase 4 report.

### 4.4 Encoding

| Column | Encoding | Output |
|---|---|---|
| `Employment_Type` (nominal, 3 levels) | one-hot, reference = Salaried | `emp_sep`, `emp_senp` |
| `Loan_Type` (nominal, 4 levels) | one-hot, reference = Personal | `loan_type_home`, `loan_type_vehicle`, `loan_type_business` |
| `CIBIL_Score == −1` | binary flag | `is_new_to_credit` |
| `Loan_Status` | binary | `loan_status` (1 = Approved) |

### 4.5 Transform and scaling
- **log1p** was applied to the continuous features with skew > 1: `total_income` (skew 1.86 → 0.04), `loan_tenure_months` (1.34 → 0.30), `foir` (1.50 → 0.88), `loan_to_income` (1.42 → 0.74).
- **StandardScaler** (z-score) was applied to all 8 continuous features. Binary and one-hot columns stay 0/1.

**Scaler parameters.** Use these to convert a decision-tree threshold back to rupees or scores for explanations (requirement b):

| Feature | log1p? | mean | std | Back to original units |
|---|---|---|---|---|
| `work_experience` | no | 13.4170 | 8.3242 | `x = z·8.3242 + 13.4170` (years) |
| `total_income` | yes | 11.1275 | 0.6872 | `x = exp(z·0.6872 + 11.1275) − 1` (₹/month) |
| `cibil_score` | no | 734.8202 | 63.4487 | `x = z·63.4487 + 734.8202` |
| `loan_tenure_months` | yes | 4.1689 | 0.8607 | `x = exp(z·0.8607 + 4.1689) − 1` (months) |
| `foir` | yes | 0.2920 | 0.1510 | `x = exp(z·0.1510 + 0.2920) − 1` (ratio) |
| `collateral_coverage` | no | 0.8773 | 0.7942 | `x = z·0.7942 + 0.8773` (× loan) |
| `loan_to_income` | yes | 0.7391 | 0.4640 | `x = exp(z·0.4640 + 0.7391) − 1` (years of income) |
| `age_at_maturity` | no | 45.2643 | 10.8499 | `x = z·10.8499 + 45.2643` (years) |

*Example:* a tree split `foir <= 0.5` means **FOIR ≤ 44.4%**, and `cibil_score <= -0.5` means **CIBIL ≤ 703**. Tree-based models don't need scaling at all. It is applied here so that the same file also works for Logistic Regression, SVM and KNN benchmarking.

---

## 5. Final dataset: `loan_applications_final.csv` (9,847 × 16)

| # | Column | Type | Content |
|---|---|---|---|
| — | `loan_id` | str | Identifier. **Drop before training** |
| 1 | `work_experience` | float (z) | Years of experience or business vintage |
| 2 | `total_income` | float (z, log) | Clubbed net monthly income |
| 3 | `cibil_score` | float (z) | Bureau score (NTC set to the median) |
| 4 | `is_new_to_credit` | int 0/1 | 6.1% of applicants |
| 5 | `loan_tenure_months` | float (z, log) | Tenure |
| 6 | `foir` | float (z, log) | Fixed Obligation to Income Ratio |
| 7 | `collateral_coverage` | float (z) | Collateral ÷ loan (0 = unsecured) |
| 8 | `loan_to_income` | float (z, log) | Loan ÷ annual income |
| 9 | `age_at_maturity` | float (z) | Age at the last EMI |
| 10 | `emp_senp` | int 0/1 | Self-employed non-professional |
| 11 | `emp_sep` | int 0/1 | Self-employed professional |
| 12 | `loan_type_business` | int 0/1 | Business loan |
| 13 | `loan_type_home` | int 0/1 | Home loan |
| 14 | `loan_type_vehicle` | int 0/1 | Vehicle loan |
| — | `loan_status` | int 0/1 | **Target**, 1 = Approved (58.5%) |

**Raw vs final at a glance:** 10,000 → 9,847 rows; 15 raw features → 14 model features. Only 3 of the final features are cleaned raw columns (`work_experience`, `cibil_score`, tenure); the rest are constructed, encoded or flags. There are no text values, no missing values, and every continuous column has mean 0 and std 1.

### 5.1 Sanity check
Five-fold stratified CV on the final file:

| Model | Accuracy | ROC-AUC | F1 |
|---|---|---|---|
| Logistic Regression | 0.787 | 0.855 | 0.824 |
| Decision Tree (depth 6, min leaf 20) | 0.849 | 0.897 | 0.880 |
| Random Forest | 0.879 | 0.938 | 0.900 |
| Hist Gradient Boosting | 0.888 | 0.942 | 0.907 |

The dataset is learnable but not trivial. The label noise is deliberate, so expect about 85–89% accuracy, not 99%. The gap between Logistic Regression and the trees comes from the threshold-type policy rules, which trees capture naturally.

---

## 6. Notes for building the pipeline

1. **Fit on the training split only.** In this reference run, the imputation medians and modes, winsorising bounds, scaler and MI-based selection were computed on all 9,847 rows for convenience. In your pipeline, `fit` them on the training fold and only `transform` the test fold, otherwise test information leaks into training.
2. **Phase order.** Your plan lists scaling and encoding in Phase 3 and feature construction in Phase 4. Build FOIR, coverage, loan-to-income and age-at-maturity from the **unscaled** columns: either keep an unscaled copy, or move scaling to the end of Phase 4 as done here.
3. **SMOTE**, if used, must be applied **inside the training folds only**, never to this CSV before splitting. At 58.5/41.5, `class_weight='balanced'` may be enough.
4. **Rule engine input.** The policy engine (requirement c) must evaluate rules on the semi-preprocessed table in original units (₹, years, CIBIL points), independent of the model. It should also route three kinds of record to manual review instead of silently trusting the imputed value:
   - NTC applicants
   - records whose CIBIL or Existing_EMI was imputed
   - collateral that was back-filled from the median LTV
5. **Audit trail.** Persist `loan_id`, the raw inputs, the semi-preprocessed values, the model probability, the rules fired, the final decision and a timestamp. `loan_id` is the join key across all of these.

---

## 7. Policy rules used when the history was generated (for the rule engine)

These are the hard constraints behind the labels, checked here against the cleaned data. They are realistic Indian-bank norms. Only R5 is an RBI regulatory cap; the others are typical bank credit-policy thresholds.

| Rule | Constraint | Violations | Historically approved anyway |
|---|---|---|---|
| R1 | Age ≥ 21 at application | 151 (1.5%) | 3.3% |
| R2 | Age at maturity ≤ 60 (Salaried) / ≤ 65 (SEP, SENP) | 204 (2.1%) | 6.9% |
| R3 | CIBIL ≥ 650 when scored (NTC is allowed through to scoring) | 940 (9.5%) | 2.8% |
| R4 | FOIR ≤ 50% (income < ₹50k) / 55% (₹50k–1L) / 65% (> ₹1L) | 1,488 (15.1%) | 5.4% |
| R5 | **RBI LTV cap for housing loans:** ≤ 90% up to ₹30 L, ≤ 80% for ₹30–75 L, ≤ 75% above ₹75 L | 258 (2.6%) | 5.4% |
| R6 | Total monthly income ≥ ₹15,000 | 133 (1.4%) | 3.8% |
| R7 | Experience ≥ 1 yr (Salaried) / ≥ 3 yrs (SEP, SENP) | 808 (8.2%) | 2.5% |
| — | **Any rule violated** | **3,243 (32.9%)** | **4.1% (133 approvals)** |

Those **133 historical approvals that break policy** matter. The model will partly learn them as legacy deviations, plus a little noise from imputed values. They are the concrete reason requirement (c) says rules must be enforced independently of the model: the rule layer overrides any model approval that violates R1–R7. Among applications that pass every rule, the historical approval rate is 85.2%.

---

## 8. Fairness hooks (requirement e)

`Gender` and `Marital_Status` are **not** in the final features. `Age` left through redundancy, but age bands can be rebuilt from raw. Join on `loan_id` to audit any subgroup. Historical approval rates in the cleaned data:

| Group | n | Approval rate |
|---|---|---|
| Male | 6,880 | 59.5% |
| Female | 2,733 | 55.7% |
| Transgender | 58 | 55.2% (sample too small for reliable estimates; report with confidence intervals) |
| Unknown gender | 176 | 62.5% |
| Urban / Semi-Urban / Rural | 4,980 / 2,900 / 1,967 | 61.7% / 57.3% / 52.0% |
| Age ≤ 25 / 26–35 / 36–45 / 46–55 / > 55 | 800 / 3,446 / 3,869 / 1,453 / 279 | 17.8% / 58.6% / 65.1% / 65.5% / 44.4% |

- The historical **disparate-impact ratio for Female vs Male is 0.936** (above the 0.8 "four-fifths" threshold, but a gap of 3.8 percentage points). Part of it is explained by income (a legitimate factor) and part is the injected direct bias.
- A gender-blind model trained on the final file should narrow the direct part of the gap but not the income-driven part. Checking this is exactly what your audit should do, using demographic parity, equal opportunity (TPR gap) and the DIR, per period.
- The low approval rates for the youngest and oldest groups mostly come from rules R1, R2 and R7, which are legitimate age-linked policy. The audit should separate these policy effects from model effects.

---

## Sources
- RBI housing-loan LTV caps (90% / 80% / 75% by loan slab): [Bajaj Finserv — RBI Guidelines for Home Loans 2026](https://www.bajajfinserv.in/insights/rbi-guidelines-for-home-loan)
- RBI Fair Practices Code for Lenders (non-discrimination on sex, caste and religion; written reasons for rejection): [RBI — Guidelines on Fair Practices Code for Lenders](https://www.rbi.org.in/commonman/Upload/English/Notification/PDFs/36102.pdf)
- FOIR slabs, CIBIL cut-off, age-at-maturity limits and minimum income/experience are typical Indian bank credit-policy values chosen for this synthetic dataset. They are not regulatory mandates.
