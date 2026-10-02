# Preprocessing Phase 4 Report
## Feature Engineering (Construction, Selection, Extraction)

| | |
|---|---|
| **Project** | CogniLend – Loan Approval Decision-Support System |
| **Phase** | 4 of 4 (Feature construction, feature selection, feature extraction) |
| **Inputs** | `data/processed/cleaned_dataset_original_units.csv` (real units), `data/processed/semi_preprocessed_dataset.csv`, `phase3/transform_params.json` |
| **Code** | `phase4/phase4_feature_engineering.ipynb` |
| **Final deliverable** | `data/final/final_preprocessed_dataset.csv` (9,847 × 16) |
| **Extra output** | `phase4/feature_params.json` (formulas, caps, scaler values, selection reasons) |
| **Plots** | `phase4/plots/` (6 images) |
| **Next step** | Model training (Decision Tree), rule engine, fairness audit |

---

## 0. Quick summary (read this first)

- **Built 8 new features** from real values: total income, proposed EMI, **FOIR**, **collateral coverage**, **loan-to-income**, **age at maturity**, has-co-applicant and is-secured.
- **The new features show the bank "walls" clearly:**

| Group | Approval |
|---|---|
| FOIR 65–80% | 3.8% |
| Total income below ₹15,000 | 3.7% |
| Age at maturity 65+ | 6.5% |
| FOIR below 30% | 73.9% |

- **Selected 14 of 25 candidates** with a simple four-step funnel:
  - A: a ratio replaces its parts
  - B: redundancy
  - C: relevance
  - D: one-hot groups

  Accuracy hardly changed: **88.01% → 87.94%** with 5-fold random forest.
- **Protected attributes** (gender, marital status) were **never candidates**. They stay only for the fairness audit.
- **PCA was tested and not used.** It needs 5 of 8 components for 90% of the variance, and it would destroy the explainable decision path.
- **Final dataset:** 9,847 rows × 16 columns (`loan_id` + 14 features + `loan_status`). There are no missing values, and it is **byte-for-byte identical** to the dataset agreed at the start of the project.
- **The full pipeline (Phase 1 → 4) now turns the raw CSV into the final CSV**, with every step written down.

---

## 1. What we did and what we did not do

| Done in Phase 4 | Already done earlier (not repeated) |
|---|---|
| Built new features from real-unit values | Cleaning, filling and encoding (Phase 3) |
| Capped and transformed the **new** features with the Phase 3 rules | Transforming the original columns (Phase 3; taken as they are) |
| Selected features with written reasons | EDA and relationship study (Phases 1–2; used as evidence) |
| Tested PCA (feature extraction) | |
| Saved the final dataset and all parameters | |

**Why we built from the real-unit file:** the Phase 3 hand-over warned that ratios must use real ₹ values. For example, if income were capped first, a rich applicant's FOIR would look far too high. So we built every ratio from `cleaned_dataset_original_units.csv` and **only then** capped and scaled it.

---

## 2. Feature construction

| New feature | Formula | Bank meaning | Phase 2 evidence |
|---|---|---|---|
| `total_income` | Monthly_Income + Coapplicant_Income | Eligibility income | Co-applicant income raises approval |
| `proposed_emi` | P·r·(1+r)^n / ((1+r)^n − 1) | EMI of the new loan | 12-month tenures (big EMI) get only 38% |
| `foir` | (Existing_EMI + proposed_emi) / total_income | Fixed Obligation to Income Ratio | EMI only matters compared with income |
| `collateral_coverage` | Collateral_Value / Loan_Amount (0 = unsecured) | Inverse of LTV | Above the RBI LTV limit: 2.8% vs 57.1% |
| `loan_to_income` | Loan_Amount / (12 × total_income) | Loan in years of income | Small loan + high income 81.6% vs big loan + low income 36.7% |
| `age_at_maturity` | Age + Loan_Tenure / 12 | Age at the last EMI | Age 61+ 24.4%; 360 months 32.6% |
| `has_coapplicant` | Coapplicant_Income > 0 | Has an earning co-applicant | Candidate flag |
| `is_secured` | Collateral_Value > 0 | Loan has collateral | Candidate flag |

**EMI details:** P = loan amount, n = tenure in months, r = yearly rate ÷ 12. We used one typical rate per loan type: **Home 8.5%, Vehicle 9.5%, Personal 11.5%, Business 13%**. The real rate is only fixed **after** approval, so using it would leak information from after the decision.

**Hand check (first applicant):**

| Item | Value |
|---|---|
| Loan | ₹14.4 lakh home loan over 240 months |
| Proposed EMI | ₹12,497 |
| Existing EMI | ₹1,900 |
| Total income | ₹45,800 |
| FOIR | (1,900 + 12,497) ÷ 45,800 = **31.4%** |
| Collateral coverage | 1.44× |
| Age at maturity | 60 years |

All of these values look realistic.

### 2.1 Treating extreme values of the new features
We reused the Phase 3 rule after building the ratios:

| Feature | Cap | Values changed | Reason |
|---|---|---|---|
| `total_income` | 1st/99th percentile: ₹14,000 – ₹3,59,258 | 197 | Same rule as the Phase 3 money columns |
| `foir` | 0 – 1.5 | 29 | Above 150% of income the EMI is clearly unpayable |
| `collateral_coverage` | 0 – 5.0 | 5 | More than 5× the loan is "very safe"; a bigger number adds nothing |
| `loan_to_income` | 0 – 5.62 (99th percentile) | 99 | No clear bank limit, so the data's 99th percentile is used |
| `age_at_maturity` | none | 0 | Already in a normal range |

### 2.2 Do the new features work?
![New features vs target](plots/p4_new_features_vs_target.png)

| Feature | Approval pattern | Matching bank rule |
|---|---|---|
| **FOIR** | <30% → **73.9%**, 40–50% → 56.9%, 55–65% → 22.4%, 65–80% → **3.8%** | R4 (FOIR limit 50–65%) |
| **Total income** | <₹15k → **3.7%**, then 43.0% rising to 70.6% (₹2 L+) | R6 (minimum income on **total** income) |
| **Age at maturity** | 60–65 → 59.8%, **65+ → 6.5%** | R2 (age at loan end ≤ 60/65) |
| **Loan-to-income** | <3 months → 76.9%, 3+ years → 40.4% | Loan size compared with income |
| **Collateral coverage** | Almost flat when used alone (57.5–62.1%) | R5 applies **only to home loans**, with a limit that depends on loan size. So coverage works together with loan type |

**Total income gives a much sharper wall than applicant income alone.** In Phase 2, applicant income below ₹15k still got 17.9%; here total income below ₹15k gets 3.7%. So the bank rule really looks at combined income.

---

## 3. Feature selection

### 3.1 The candidates (25)
- **Never candidates:** the 7 protected columns (`gender_*`, `marital_*`, kept for the audit only, following the RBI Fair Practices Code and issues P22/P23) and `loan_id`.
- **Candidates (25):** 12 Phase 3 columns + 5 one-hot columns + 8 new features.
  - Scored in **real units**: mutual information and random forests don't need scaling.
  - CIBIL uses the Phase 3 rule (−1 → 739), together with `is_new_to_credit`.

### 3.2 Scores
**Mutual information (MI)** measures how much a feature says about approval. **Permutation importance (PI)** is the accuracy drop when the feature is shuffled; it comes from a random forest with 300 trees on a 25% test part (test accuracy 0.874).

![Feature scores](plots/p4_feature_scores.png)

| Feature | MI | PI | Feature | MI | PI |
|---|---|---|---|---|---|
| **foir** | **0.1178** | **0.1376** | collateral_coverage | 0.0071 | **0.0251** |
| **cibil_score** | **0.1068** | **0.1231** | loan_amount | 0.0059 | 0.0068 |
| **work_experience** | **0.0677** | **0.0615** | loan_type_vehicle | 0.0052 | −0.0009 |
| age | 0.0387 | 0.0049 | is_new_to_credit | 0.0036 | 0.0013 |
| age_at_maturity | 0.0378 | 0.0156 | loan_type_home | 0.0032 | 0.0002 |
| loan_to_income | 0.0302 | 0.0054 | property_area | 0.0029 | 0.0002 |
| proposed_emi | 0.0238 | 0.0021 | dependents | 0.0025 | 0.0002 |
| total_income | 0.0189 | 0.0121 | collateral_value | 0.0014 | 0.0043 |
| monthly_income | 0.0169 | 0.0030 | has_coapplicant | 0.0009 | −0.0006 |
| loan_tenure_months | 0.0138 | 0.0013 | emp_senp | 0.0002 | 0.0013 |
| existing_emi | 0.0087 | 0.0006 | loan_type_business | 0.0001 | 0.0000 |
| | | | is_secured | 0.0001 | 0.0011 |
| | | | coapplicant_income | 0.0000 | 0.0012 |
| | | | emp_sep | 0.0000 | 0.0022 |

**Group importance:** we shuffled each whole one-hot group together. Employment type scored **0.0040** and loan type **0.0011**. One-hot columns look weak one by one, but they matter as a group.

**Redundant pairs (|Spearman| > 0.80):**

| Pair | Spearman |
|---|---|
| coapplicant_income ↔ has_coapplicant | 0.976 |
| age ↔ work_experience | 0.937 |
| collateral_value ↔ collateral_coverage | 0.886 |
| collateral_value ↔ is_secured | 0.879 |
| collateral_coverage ↔ is_secured | 0.879 |
| monthly_income ↔ total_income | 0.874 |
| loan_amount ↔ proposed_emi | 0.850 |
| loan_amount ↔ loan_to_income | 0.814 |

### 3.3 The selection funnel

| Step | Rule | Dropped | Left |
|---|---|---|---|
| Start | 25 candidates | – | 25 |
| **A. Ratio replaces its parts** | Banks decide on ratios | monthly_income, coapplicant_income (→ total_income); existing_emi, proposed_emi (→ foir); collateral_value (→ collateral_coverage); loan_amount (→ loan_to_income) | 19 |
| **B. Redundancy** | Drop the lower-MI member of each pair with \|ρ\| > 0.80 | **age** (0.937 with work_experience; MI 0.039 vs 0.068), **is_secured** (0.879 with collateral_coverage) | 17 |
| **C. Relevance** | Drop if MI < 0.005 **and** PI < 0.001 | **dependents** (0.0025 / 0.0002), **property_area** (0.0029 / 0.0002), **has_coapplicant** (0.0009 / −0.0006) | 14 |
| **D. One-hot groups** | Keep a group if group PI ≥ 0.001 | none (0.0040 and 0.0011) | **14** |

![Selection funnel](plots/p4_selection_funnel.png)

**Must-keep safety rule.** Steps C and D never drop a feature that a **bank rule (R1–R7)** needs:

| Bank rule | Must-keep feature(s) |
|---|---|
| R3 (CIBIL ≥ 650) | cibil_score, is_new_to_credit |
| R4 (FOIR limit) | foir |
| R5 (RBI LTV cap) | collateral_coverage, loan-type group |
| R2 (age at loan end) | age_at_maturity |
| R6 (minimum income) | total_income |
| R7 (minimum experience) | work_experience, employment group |

The rule **changed nothing here**, but two features were close to the cut-off: `is_new_to_credit` (PI 0.0013) and the loan-type group (0.0011). With the rule in place, a tiny score difference on another computer or library version cannot remove them.

**Why each dropped feature is fine to lose:**
- **age:** its information lives on in `age_at_maturity` (age + tenure). This closes **P21**.
- **dependents and property_area:** Phase 2 showed dependents is mostly "age in disguise" (**P22**), and property area mostly follows income, which is now in `total_income`.
- **The parts of the ratios:** each ratio carries their information in a size-free way. Collateral_value ↔ loan_amount (0.98, **P21**) is solved by `collateral_coverage`.

### 3.4 Did selection cost accuracy?

| Feature set | 5-fold accuracy (random forest) |
|---|---|
| All 25 candidates | **88.01%** |
| 14 selected | **87.94%** |
| Difference | −0.07 points |

**We almost lose nothing**, and the model is smaller and easier to explain.

![Selected correlation](plots/p4_selected_correlation.png)

The highest correlation left between two selected features is **0.78** (loan_tenure ↔ loan_type_home, because home loans have long tenures). That is acceptable.

---

## 4. Feature extraction (PCA) – tested, not used

![PCA](plots/p4_pca_variance.png)

| Components | 1 | 2 | 3 | 4 | **5** | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Cumulative variance | 35.8% | 56.1% | 70.2% | 82.6% | **91.3%** | 98.2% | 99.3% | 100% |

- PCA needs **5 of the 8** continuous features' worth of components to keep 90% of the variance, so the reduction is small.
- Each component is a **mix of every feature**. A tree rule like "PC1 ≤ 0.3" means nothing to a loan officer, which breaks the project goal of a **traceable decision path**.
- **Decision: PCA is not used.** The 14 named features are kept.

---

## 5. Transforming the selected features

- **Already transformed in Phase 3**, so taken from `semi_preprocessed_dataset.csv` and not scaled again: work_experience, cibil_score, is_new_to_credit, loan_tenure_months, emp_*, loan_type_*.
- **New features** get the Phase 3 rules: cap (Section 2.1) → `log1p` if skew > 1 → `StandardScaler`.

| Feature | Source | log1p? | Skew before → after | Mean | Std |
|---|---|---|---|---|---|
| work_experience | Phase 3 | no | 0.47 | 13.4170 | 8.3242 |
| cibil_score | Phase 3 | no | −0.45 | 734.8202 | 63.4487 |
| loan_tenure_months | Phase 3 | yes | 1.34 → 0.30 | 4.1689 | 0.8607 |
| total_income | Phase 4 | yes | 1.86 → 0.04 | 11.1275 | 0.6872 |
| foir | Phase 4 | yes | 1.50 → 0.88 | 0.2920 | 0.1510 |
| collateral_coverage | Phase 4 | no | 0.29 | 0.8773 | 0.7942 |
| loan_to_income | Phase 4 | yes | 1.42 → 0.74 | 0.7391 | 0.4640 |
| age_at_maturity | Phase 4 | no | 0.31 | 45.2643 | 10.8499 |

For log1p features the mean and std are on the log1p scale. Full precision is in `phase3/transform_params.json` and `phase4/feature_params.json`.

![Final features](plots/p4_final_features.png)

### 5.1 Reading a decision-tree split in real units
A tree trained on this file will produce splits such as `foir <= 0.5`. To explain them to a loan officer:

| Feature | Back to real units | Example: z = 0.5 means |
|---|---|---|
| foir | exp(z × 0.1510 + 0.2920) − 1 | **FOIR ≈ 44.4%** |
| total_income | exp(z × 0.6872 + 11.1275) − 1 | about ₹96,000 per month |
| loan_to_income | exp(z × 0.4640 + 0.7391) − 1 | about 1.6 years of income |
| cibil_score | z × 63.4487 + 734.8202 | CIBIL ≈ 767 |
| work_experience | z × 8.3242 + 13.4170 | about 17.6 years |
| collateral_coverage | z × 0.7942 + 0.8773 | about 1.27× the loan |
| age_at_maturity | z × 10.8499 + 45.2643 | about 50.7 years |
| loan_tenure_months | exp(z × 0.8607 + 4.1689) − 1 | about 98 months |

---

## 6. The final dataset: `data/final/final_preprocessed_dataset.csv`

**9,847 rows × 16 columns, no missing values.**

| # | Column | Type | Meaning |
|---|---|---|---|
| – | `loan_id` | text | **Drop before `fit()`.** Join key for the audit log and the fairness audit |
| 1 | `work_experience` | scaled | Years of work or business |
| 2 | `total_income` | capped → log1p → scaled | Applicant + co-applicant income |
| 3 | `cibil_score` | scaled | CIBIL score (no-history rows set to 739) |
| 4 | `is_new_to_credit` | 0/1 | 1 = no credit history (6.1%) |
| 5 | `loan_tenure_months` | log1p → scaled | Tenure |
| 6 | `foir` | capped → log1p → scaled | EMI-to-income ratio |
| 7 | `collateral_coverage` | capped → scaled | Collateral ÷ loan (0 = unsecured) |
| 8 | `loan_to_income` | capped → log1p → scaled | Loan in years of income |
| 9 | `age_at_maturity` | scaled | Age at the last EMI |
| 10 | `emp_senp` | 0/1 | Self-employed non-professional (reference: Salaried) |
| 11 | `emp_sep` | 0/1 | Self-employed professional |
| 12 | `loan_type_business` | 0/1 | Business loan (reference: Personal) |
| 13 | `loan_type_home` | 0/1 | Home loan |
| 14 | `loan_type_vehicle` | 0/1 | Vehicle loan |
| – | `loan_status` | 0/1 | **Target**: 1 = Approved (58.46%; 5,757 approved / 4,090 rejected) |

**Check against the agreed dataset:** the notebook compares this file with `data/reference/loan_applications_final.csv`. **Columns, shape and every value are the same**, and the two files are byte-for-byte identical.

---

## 7. Issue log – final status

| ID | Issue | Final status | Where it was handled |
|---|---|---|---|
| P01–P17 | Duplicates, labels, types, invalid values, missing values, skew | ✅ Closed | Phase 3 |
| P19, P20 | Experience > age − 18; collateral really missing | ✅ Closed | Phase 3 |
| **P21** | Redundant pairs (age ↔ experience 0.94; amount ↔ collateral 0.98) | ✅ **Closed** | Phase 4: age dropped (lives on in age_at_maturity); amount and collateral replaced by ratios |
| **P22** | Marital_Status and Dependents act as "age in disguise" | ✅ **Closed** | Phase 4: marital never a candidate; dependents dropped (step C) |
| P18 | Very small groups (Transgender 60, Divorced 95, Widowed 87) | 🔶 Open → **fairness audit** | Report results with care |
| P23 | Gender gap remains inside income groups | 🔶 Open → **fairness audit** | Check the model's predictions per group |
| P24 | Some past approvals break hard rules | 🔶 Open → **rule engine** | The rule engine must override the model |

---

## 8. Hand-over to the next teams

### 8.1 Model training (Decision Tree, benchmarking)
- Use `data/final/final_preprocessed_dataset.csv`. **X = the 14 feature columns**, **y = `loan_status`**, and drop `loan_id`.
- The classes are mildly imbalanced (58.5 / 41.5). Report precision, recall, F1 and ROC-AUC, not only accuracy. If you use SMOTE, apply it **only to the training part**, never to the test part.
- **Data leakage note:** all medians, caps and scaler values in Phases 3–4 were calculated on all 9,847 rows, so the agreed file could be reproduced. For the final model evaluation, the same steps should be **fitted on the training split only** and applied to the test split (Phase 3 Section 1 and Phase 4 code show every step).
- Use Section 5.1 to turn tree thresholds back into ₹, %, years and CIBIL points for explanations.

### 8.2 Rule engine and audit log (DBMS)
- Check the bank and RBI rules (R1–R7) on **`data/processed/cleaned_dataset_original_units.csv`**, which has real units and CIBIL −1 kept. **Never** use the scaled file for rules.
- The formulas for FOIR, LTV (= 1 ÷ collateral_coverage), age at maturity and total income are in Section 2 and in `feature_params.json`. The rule engine should recompute them in real units.
- `loan_id` links raw data, cleaned data, final features, predictions and rule results for the **audit trail**.
- Phase 2 found past approvals that break hard rules (P24). The rule engine must **override** the model in these cases.

### 8.3 Fairness audit
- The model never sees gender or marital status.
- Join them back by `loan_id`, either from `cleaned_dataset_original_units.csv` (readable labels) or from the `gender_*` / `marital_*` columns in `semi_preprocessed_dataset.csv`.
- Check approval rates, true-positive rates and the Female/Male ratio of the **model's predictions**. In the raw data that ratio is 0.936 (Phase 2).
- Report the Transgender, Divorced and Widowed groups with care, because they are very small (P18).

---

## 9. The whole pipeline in one table

| Phase | Input | What happened | Output |
|---|---|---|---|
| 1 | Raw CSV (10,000 × 17) | Domain knowledge, 7 EDA questions, univariate analysis; found issues P01–P18 | `phase1/preprocessing_phase1_report.md` |
| 2 | Raw CSV + Phase 1 report | Bivariate and multivariate analysis; answered Phase 1 questions; issues P19–P24; feature ideas | `phase2/preprocessing_phase2_report.md` |
| 3 | Raw CSV + Phase 1/2 decisions | Duplicates, types, invalid values, imputation, outliers, log1p, encoding, scaling | `data/processed/semi_preprocessed_dataset.csv` (9,847 × 26) + real-unit file + `transform_params.json` |
| 4 | Phase 3 outputs | Built 8 features, selected 14 of 25, tested PCA, transformed new features | **`data/final/final_preprocessed_dataset.csv` (9,847 × 16)** + `feature_params.json` |

---

## 10. Files produced in Phase 4

| File | What it is |
|---|---|
| `phase4/phase4_feature_engineering.ipynb` | All Phase 4 code with outputs |
| `phase4/preprocessing_phase4_report.md` | This report |
| `phase4/feature_params.json` | Rates, caps, must-keep list, dropped features with reasons, selected features, scaler values, PCA result |
| `phase4/plots/*.png` | 6 plots used in this report |
| `data/final/final_preprocessed_dataset.csv` | **Final deliverable** (9,847 × 16) |

**How to run the whole pipeline:** run the four notebooks in order (`phase1` → `phase2` → `phase3` → `phase4`), each from inside its own folder. Phases 1 and 2 only read data; Phase 3 writes `data/processed/`; Phase 4 writes `data/final/`.

**Library versions used:** Python 3, pandas 3.0.2, numpy 2.4.4, scikit-learn 1.8.0, matplotlib 3.10.9, seaborn 0.13.2, scipy 1.17.1. With other scikit-learn versions the MI and PI numbers can move a little. The must-keep rule protects the features that were close to the cut-off, so the final feature list should stay the same. The last cell of the Phase 4 notebook compares the result with the agreed file, so any change is seen at once.
