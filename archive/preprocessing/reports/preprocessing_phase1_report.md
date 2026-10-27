# Preprocessing Phase 1 Report
## Domain Knowledge, Basic EDA and Univariate Analysis

| | |
|---|---|
| **Project** | CogniLend – Loan Approval Decision-Support System |
| **Phase** | 1 of 4 (Domain knowledge + Basic EDA + Univariate analysis) |
| **Input data** | `data/raw/loan_applications_raw.csv` (10,000 rows × 17 columns) |
| **Code** | `phase1/phase1_domain_eda_univariate.ipynb` |
| **Plots** | `phase1/plots/` (19 images) |
| **Next phase** | Phase 2 – Bivariate and multivariate analysis |

---

## 0. Quick summary (read this first)

- The raw data has **10,000 loan applications** and **17 columns**: Loan_ID, 15 input columns and the target Loan_Status.
- Target: **58.5% Approved, 41.5% Rejected**, with **18 rows missing the target**. The imbalance is mild.
- The data is **messy on purpose, like a real bank export**:
  - 135 duplicate rows
  - 4,861 badly spelled category values (for example `HL`, `Housing Loan` and `home loan` are the same thing)
  - 584 loan amounts stored as text (`"Rs. 27,90,000"`)
  - impossible values (age 999, CIBIL 9999, negative income)
  - 95 tenures that look like years instead of months
- **Two columns are mostly blank:** Coapplicant_Income (67.9%) and Collateral_Value (42.5%). The blanks probably mean "no co-applicant" and "no collateral". **Phase 2 must confirm this.**
- **CIBIL = −1 (602 rows) is not an error.** It means "no credit history".
- All money columns are **strongly right-skewed** (skewness about 3 to 3.7). Most of their outliers are **real rich customers or big loans**, not mistakes.
- **We did not change the data.** Section 5 lists every problem with an ID (P01–P18) so later phases can refer to it.

---

## 1. What we did and what we did not do

| Done in Phase 1 | Not done in Phase 1 (left for later) |
|---|---|
| Studied the loan domain and Indian bank norms | Comparing two or more columns (Phase 2) |
| Answered the 7 basic EDA questions | Removing duplicates, fixing types, filling missing values (Phase 3) |
| Studied each column on its own (univariate) | Treating outliers, scaling, encoding (Phase 3) |
| Counted every problem and wrote it down | Making new features or selecting features (Phase 4) |

**Rule we followed:** the real data frame (`df`) was **never changed**. The last cell of the notebook reloads the CSV and confirms `df` is still the same as the raw file. For a few plots we made **temporary copies** with small fixes, for example joining `M` and `Male`, or removing commas from Loan_Amount. These copies were used only for drawing and then thrown away.

---

## 2. Domain knowledge

### 2.1 The problem in simple words
A bank gets many loan applications. A loan officer must decide **approve or reject**. Our system must:
1. **Predict** approve or reject correctly, and also work on new data.
2. **Explain** the decision with a clear path, like a decision tree.
3. **Check hard bank and RBI rules separately** from the model, so a rule is never broken even if the model says "approve".
4. **Save** every decision with a full record (audit trail).
5. **Check fairness**, meaning that groups such as men and women are treated fairly.

This is a **binary classification** problem. The target is **Loan_Status** (Approved / Rejected).

### 2.2 How an Indian bank checks a loan (the 5 Cs of credit)

| C | Question the bank asks | Columns in our data |
|---|---|---|
| **Character** | Does this person repay loans on time? | CIBIL_Score |
| **Capacity** | Can this person pay one more EMI every month? | Monthly_Income, Coapplicant_Income, Existing_EMI |
| **Capital / stability** | Is the job or business stable? | Employment_Type, Work_Experience, Age |
| **Collateral** | What can the bank sell if the loan is not repaid? | Collateral_Value, Loan_Type |
| **Conditions** | What exactly is being asked for? | Loan_Type, Loan_Amount, Loan_Tenure |

### 2.3 Important terms

| Term | Simple meaning |
|---|---|
| **EMI** | Equated Monthly Instalment: the fixed amount paid every month to repay a loan. |
| **FOIR** | Fixed Obligation to Income Ratio = (all EMIs, including the new loan's EMI) ÷ monthly income. It shows how much of the salary goes to EMIs. Lower is safer. |
| **CIBIL score** | Credit score from **300 to 900** given by the credit bureau. Higher is better. **−1 means no credit history** (new to credit, NTC). |
| **NTC** | New to credit: a person who never took a loan or credit card before. |
| **LTV** | Loan-to-Value = loan amount ÷ value of the property. RBI limits this for home loans. |
| **Collateral** | Property or vehicle given as security. A loan with collateral is **secured**; one without (like a personal loan) is **unsecured**. |
| **Co-applicant** | A second person (often spouse or parent) whose income is added to the applicant's income. |
| **Tenure** | Time to repay the loan, in **months**. |
| **Age at maturity** | Age of the applicant when the last EMI is paid = age + tenure in years. |
| **Salaried / SEP / SENP** | Job holder / Self-Employed Professional (doctor, CA, architect) / Self-Employed Non-Professional (shop or business owner). Banks treat these groups differently. |

### 2.4 Common norms used by Indian banks
We collected these from bank and RBI documents. **Only the LTV cap is an RBI rule**; the others are common **bank policy** limits. In our project these norms become the **hard policy rules** of the rule engine.

| Norm | Usual value | Type |
|---|---|---|
| Minimum age | 21 years | Bank policy |
| Age at loan end (maturity) | ≤ 60 (salaried), ≤ 65 (self-employed) | Bank policy |
| CIBIL score | 750+ preferred; many banks reject below about 650 | Bank policy |
| FOIR limit | Up to 50–65% of income, depending on income level | Bank policy |
| **Home-loan LTV cap** | **≤ 90% for loans up to ₹30 lakh, ≤ 80% for ₹30–75 lakh, ≤ 75% above ₹75 lakh** | **RBI rule** |
| Minimum income | About ₹15,000 per month | Bank policy |
| Minimum experience | 1 year (salaried), 3 years of business (self-employed) | Bank policy |
| No discrimination | Lenders must not discriminate on grounds of **sex, caste or religion** | **RBI Fair Practices Code** |

### 2.5 Column dictionary (meaning and valid values)
These valid values are also written in the notebook as `valid_range` and `valid_categories` so that the **next phases can reuse them**.

| # | Column | Meaning | Valid values (domain) | Raw type |
|---|---|---|---|---|
| – | Loan_ID | Application number (for audit; not a model input) | Unique text like `LN2025102971` | text |
| 1 | Age | Applicant age | 18–75 years | number |
| 2 | Gender | Applicant gender (**protected**) | Male / Female / Transgender | text |
| 3 | Marital_Status | Marital status (**protected**) | Married / Single / Divorced / Widowed | text |
| 4 | Dependents | People who depend on the applicant | 0, 1, 2, 3+ | text |
| 5 | Employment_Type | Job type | Salaried / Self-Employed Professional / Self-Employed Non-Professional | text |
| 6 | Work_Experience | Years of job or business | 0–50 years | number |
| 7 | Monthly_Income | Applicant's monthly income (₹) | More than 0 | number |
| 8 | Coapplicant_Income | Co-applicant's monthly income (₹) | More than 0; blank = no co-applicant (to be confirmed) | number |
| 9 | Existing_EMI | EMIs already being paid (₹/month) | 0 or more (0 = no existing loan) | number |
| 10 | CIBIL_Score | Credit score | 300–900, or −1 = no credit history | number |
| 11 | Loan_Type | Type of loan asked for | Home / Vehicle / Personal / Business Loan | text |
| 12 | Loan_Amount | Amount asked for (₹) | More than 0 | **text (should be number)** |
| 13 | Loan_Tenure | Repayment time | Months, usually a multiple of 12, up to 360 | number |
| 14 | Collateral_Value | Value of property or vehicle given as security (₹) | More than 0; blank = unsecured (to be confirmed) | number |
| 15 | Property_Area | Area of the applicant or property | Urban / Semi-Urban / Rural | text |
| – | **Loan_Status** | **Target**: past decision | Approved / Rejected | text |

### 2.6 Fairness note
**Gender** and **Marital_Status** are protected attributes. Following the RBI Fair Practices Code, they **should not be used to decide** a loan. We keep them in the data only so the **fairness audit** can check approval rates for each group. One small group to watch: **Transgender applicants are only 60 rows (0.6%)**, which is too few for strong conclusions.

The dataset is **synthetic** (computer-made). It was designed to look like Indian bank data, including real-world mistakes.

---

## 3. Basic EDA – the 7 questions

### Q1. How big is the data?
**10,000 rows × 17 columns**, about 6 MB in memory. This is small enough to work on easily.

### Q2. How does the data look?
Each row is one application. Even the first few rows show problems: `salaried` in small letters, `M` instead of `Male`, `Personal` instead of `Personal Loan`, and `Rural ` with an extra space. Coapplicant_Income and Collateral_Value are often blank.

### Q3. What are the data types?
- **8 number columns** (`float64`) and **9 text columns**.
- **Loan_Amount is text** but should be a number. 584 values are written in Indian comma style, like `12,20,000`, and 94 of these also start with `Rs.`.
- **Dependents is text** because of the value `3+` (1,840 rows).
- Age, Work_Experience, CIBIL_Score and Loan_Tenure are whole numbers stored as decimals (`40.0`).

### Q4. Are there missing values?
13 of the 17 columns have missing values, **12,825 missing cells in total**.

| Column | Missing | % |
|---|---|---|
| Coapplicant_Income | 6,787 | **67.87** |
| Collateral_Value | 4,250 | **42.50** |
| Work_Experience | 301 | 3.01 |
| Existing_EMI | 252 | 2.52 |
| Dependents | 240 | 2.40 |
| Loan_Tenure | 181 | 1.81 |
| Gender | 179 | 1.79 |
| Loan_Amount | 152 | 1.52 |
| Property_Area | 149 | 1.49 |
| Marital_Status | 118 | 1.18 |
| Monthly_Income | 99 | 0.99 |
| CIBIL_Score | 99 | 0.99 |
| Loan_Status (target) | 18 | 0.18 |

![Missing values](plots/q4_missing_values.png)

**Two kinds of missing values:**
- **Very high (68% and 42.5%).** These are too large to be random typing errors. They are probably "not applicable": no co-applicant, or no collateral.
- **Small (1–3%).** These look random.

### Q5. How does the data look mathematically?
`describe()` shows impossible values straight away:

| Column | Problem seen in `describe()` |
|---|---|
| Age | min **−30**, max **999** |
| Monthly_Income | min **−2,12,100** (negative income) |
| CIBIL_Score | max **9999** (valid range is 300–900); min **−1** (no credit history) |
| Work_Experience | min **−3**, max **71** years |
| Existing_EMI | median **0**, so more than half of applicants have no existing loan |
| Loan_Tenure | min **10** months (unusual) |
| Loan_ID | **9,865 unique** in 10,000 rows, so some IDs repeat |

### Q6. Are there duplicates?
- **135 fully duplicate rows.** The same 135 Loan_IDs repeat, and **every repeated ID is an exact copy**: no ID has two different versions of the data.
- These are the same application entered twice and can be safely removed in Phase 3.

### Q7. How are the columns correlated? (first look only)
![Correlation heatmap](plots/q7_correlation_heatmap.png)

- The strongest links are **Monthly_Income ↔ Collateral_Value (0.46)**, **Loan_Tenure ↔ Collateral_Value (0.43)** and **Monthly_Income ↔ Existing_EMI (0.33)**.
- **Age ↔ Work_Experience is only 0.28.** We expected this to be high, so the impossible ages (like 999) are probably spoiling the number. **Phase 2 should re-check it without the bad values.**
- CIBIL_Score is almost unrelated to the other columns.
- Loan_Amount is not in this table because it is stored as text.

---

## 4. Univariate analysis

### 4.1 Target – Loan_Status
![Target](plots/uni_target_loan_status.png)

| Class | Count | % of filled rows |
|---|---|---|
| Approved | 5,838 | 58.49 |
| Rejected | 4,144 | 41.51 |
| Missing | 18 | – |

- The imbalance is **mild**: about 1.4 approved for every 1 rejected.
- A model that always says "Approved" would already get about **58.5% accuracy**, so later phases must also report **precision, recall, F1 and ROC-AUC**.
- The 18 rows without a target cannot be used for training.

### 4.2 Categorical columns

**Spelling problems.** Five text columns have many spellings for the same category:

| Column | Raw spellings | Real categories | Rows with extra space | Rows not in correct spelling |
|---|---|---|---|---|
| Gender | 25 | 3 | 195 | 960 |
| Marital_Status | 25 | 4 | 195 | 969 |
| Dependents | 4 | 4 | 0 | 0 |
| Employment_Type | 27 | 3 | 198 | 983 |
| Loan_Type | 36 | 4 | 202 | 983 |
| Property_Area | 24 | 3 | 201 | 966 |
| Loan_Status | 2 | 2 | 0 | 0 |

![Spellings](plots/uni_cat_spellings_summary.png)

About **10% of the rows** in each messy column are badly spelled, and about **2%** have extra spaces. Some spellings need domain knowledge to understand: `Service` = Salaried, `Unmarried` = Single, `MSME Loan` = Business Loan, `Auto Loan` / `Car Loan` = Vehicle Loan, `HL` / `PL` / `BL`. Appendix A lists every spelling.

**Category counts.** These counts use the temporary joined spellings; the real data was not changed.

| Column | Counts | What it tells us |
|---|---|---|
| Gender | Male 6,981 (69.8%), Female 2,780 (27.8%), Transgender 60 (0.6%), missing 179 (1.8%) | Mostly male applicants. The Transgender group is very small. |
| Marital_Status | Married 7,411 (74.1%), Single 2,289 (22.9%), Divorced 95 (1.0%), Widowed 87 (0.9%), missing 118 (1.2%) | Divorced and Widowed are rare groups. |
| Dependents | 0: 2,737 (27.4%), 1: 2,686 (26.9%), 2: 2,497 (25.0%), 3+: 1,840 (18.4%), missing 240 (2.4%) | Fairly even spread. |
| Employment_Type | Salaried 6,048 (60.5%), Self-Employed Non-Professional 2,450 (24.5%), Self-Employed Professional 1,502 (15.0%) | No missing values. Salaried is the largest group. |
| Loan_Type | Personal 3,215 (32.2%), Home 2,800 (28.0%), Vehicle 2,343 (23.4%), Business 1,642 (16.4%) | No missing values. Every loan type has enough rows. |
| Property_Area | Urban 4,905 (49.0%), Semi-Urban 2,947 (29.5%), Rural 1,999 (20.0%), missing 149 (1.5%) | Half of the applicants are urban. |

| | |
|---|---|
| ![Gender](plots/uni_cat_gender.png) | ![Marital status](plots/uni_cat_marital_status.png) |
| ![Dependents](plots/uni_cat_dependents.png) | ![Employment type](plots/uni_cat_employment_type.png) |
| ![Loan type](plots/uni_cat_loan_type.png) | ![Property area](plots/uni_cat_property_area.png) |

### 4.3 Numerical columns

**How we checked each column:**
1. Count the missing values.
2. Count the **invalid** values, using the valid ranges from Section 2.5.
3. Hide the invalid values **only in the plot**.
4. Find the **skewness** and the **IQR outliers** (values below Q1 − 1.5×IQR or above Q3 + 1.5×IQR).

For money columns the histogram uses a **log x-axis**, so the shape is visible. The boxplot stays on the normal scale, so its dots match the outlier count.

**Summary table.** Statistics are calculated without the invalid values. For Loan_Tenure, "invalid" means "not a multiple of 12".

| Column | Missing | Invalid | Min | Median | Mean | Max | Skewness | IQR outliers |
|---|---|---|---|---|---|---|---|---|
| Age | 0 | 29 | 20 | 37 | 37.47 | 70 | 0.35 | 63 |
| Work_Experience | 301 | 25 | 0 | 13 | 13.53 | 50 | 0.50 | 74 |
| Monthly_Income | 99 | 30 | 8,000 | 55,300 | 73,721.64 | 10,72,200 | 3.72 | 689 |
| Coapplicant_Income | 6,787 | 0 | 4,600 | 35,400 | 42,255.28 | 5,50,900 | 3.73 | 136 |
| Existing_EMI (non-zero only) | 252 | 0 | 100 | 10,900 | 16,032.72 | 2,12,900 | 2.91 | 223 |
| CIBIL_Score (without −1) | 99 | 33 | 436 | 739 | 734.41 | 900 | −0.42 | 131 |
| Loan_Amount | 152 | 0 | 50,000 | 6,80,000 | 14,94,442.53 | 3,00,00,000 | 3.73 | 857 |
| Loan_Tenure | 181 | 95 | 12 | 60 | 92.32 | 360 | 1.38 | 550 |
| Collateral_Value | 4,250 | 0 | 50,000 | 17,20,000 | 32,07,523.48 | 6,08,50,000 | 3.53 | 390 |

**Age**
![Age](plots/uni_num_age.png)
- **29 impossible ages:** −30, 0, 1, 5, 150, 200 and 999. These are typing errors.
- Valid ages are 20–70, median 37, and the shape is almost symmetric (skewness 0.35).
- The 63 outliers (above 61 years) are **real older applicants**, not errors.
- **153 applicants are 20 years old**, which is below the usual bank minimum of 21.

**Work_Experience**
![Work experience](plots/uni_num_work_experience.png)
- 301 missing values.
- **25 invalid values:** 15 negative (−3 to −1) and 10 above 50 years (up to 71).
- Valid values: median 13 years, with a slight right skew.
- **677 applicants have 0 years** of experience (the tall first bar). This matters because banks usually want at least 1 year of experience (salaried) or 3 years in business (self-employed).
- Experience should never be more than (age − 18). This needs two columns, so **Phase 2 will check it**.

**Monthly_Income**
![Monthly income](plots/uni_num_monthly_income.png)
- 99 missing values.
- **22 negative** incomes. Their size (₹8,000 to ₹2,12,100, median ₹69,550) looks like normal incomes, so this is most likely a **wrong minus sign**.
- **8 incomes are zero.**
- Median ₹55,300 and mean ₹73,722: the mean is much bigger than the median, so the column is **strongly right-skewed** (3.72).
- **689 outliers** (above about ₹1,66,500 per month). These are **real high earners**, not errors.
- On the log axis the histogram looks like a bell, which suggests a **log transform could help in Phase 3**.
- 193 applicants earn less than ₹15,000.

**Coapplicant_Income**
![Co-applicant income](plots/uni_num_coapplicant_income.png)
- **67.9% missing.**
- Every value that is present is above 0 (minimum ₹4,600), and there is **no row with 0**. This strongly suggests that a **blank means "no earning co-applicant"** rather than "unknown".
- Present values: median ₹35,400, right-skewed (3.73).

**Existing_EMI**
![Existing EMI](plots/uni_num_existing_emi.png)
- 252 missing values. No negative values.
- **6,022 applicants (61.8%) have an EMI of 0**, meaning no existing loan. This is a valid value, so these rows are not plotted.
- Applicants who do have an EMI: median ₹10,900, right-skewed (2.91).

**CIBIL_Score**
![CIBIL score](plots/uni_num_cibil_score.png)
- 99 missing values.
- **602 rows have −1** (no credit history). This is a **special code, not a very low score**, and must not be treated as a number.
- **33 invalid scores:** 0, 100, 999, 1000 and 9999.
- Valid scores run from 436 to 900, with median 739. The tail is on the left (skewness −0.42): some applicants have weak scores.
- **955 applicants score below 650** and **3,999 score 750 or more**.
- The 131 outliers are low scores (below about 567). They are real weak borrowers, not errors.

**Loan_Amount** (text converted only for the plot)
![Loan amount](plots/uni_num_loan_amount.png)
- After the temporary conversion, **no value was lost**, so Phase 3 can convert all 584 text values safely.
- Range ₹50,000 to ₹3 crore; median ₹6.8 lakh; mean ₹14.9 lakh. Strongly right-skewed (3.73).
- **857 outliers** (above about ₹40.6 lakh). These are probably home loans, which are naturally large. **Phase 2 should check amounts by Loan_Type.**
- 1,214 loans are ₹1.5 lakh or less, and 112 loans are ₹1 crore or more.

**Loan_Tenure**
![Loan tenure](plots/uni_num_loan_tenure.png)
- Only 16 different values. The most common are 36 and 60 months (1,831 each).
- Every value is a multiple of 12 **except 10, 15, 20, 25 and 30 (95 rows, orange bars)**. These look like **years typed instead of months**; for example, 20 years = 240 months. **Phase 2 should check the loan type of these rows.**
- The 550 outliers are 300- and 360-month tenures. These are normal for home loans, so they are real values.

**Collateral_Value**
![Collateral value](plots/uni_num_collateral_value.png)
- **42.5% missing.** All values that are present are above 0, so a blank probably means **no collateral (unsecured loan)**.
- Range ₹50,000 to ₹6.09 crore; median ₹17.2 lakh. Right-skewed (3.53), with 390 outliers.
- The histogram has **two humps**, one around ₹1–2 lakh and one around ₹20–50 lakh. These are probably **vehicles and property**; Phase 2 can confirm this with Loan_Type.

**Shape summary**
- **Almost symmetric:** Age, Work_Experience, CIBIL_Score.
- **Strongly right-skewed:** all five money columns (skewness about 3 to 3.7).
- **Most outliers in the money columns are real large values.** Deleting them would delete real customers. The true errors are the **invalid values**.

---

## 5. Problems found (issue log)

Nothing below has been fixed. The IDs (P01, P02, …) are for later reports to refer to.

| ID | Column | Problem | Count | Suggested next step |
|---|---|---|---|---|
| P01 | All columns | Exact duplicate rows | 135 | Phase 3: remove |
| P02 | Loan_Status | Target missing | 18 | Phase 3: drop these rows (never guess the target) |
| P03 | Gender, Marital_Status, Employment_Type, Loan_Type, Property_Area | Spelling variants and extra spaces | 4,861 cells (960 / 969 / 983 / 983 / 966) | Phase 3: strip spaces and map to real categories (Appendix A) |
| P04 | Loan_Amount | Number stored as text (`12,50,000`, `Rs. …`) | 584 (94 with `Rs.`) | Phase 3: remove `Rs.` and commas, convert to number |
| P05 | Dependents | Text value `3+` | 1,840 | Phase 3: convert to the number 3 |
| P06 | Age, Work_Experience, CIBIL_Score, Loan_Tenure | Whole numbers stored as decimals | – | Phase 3: convert to integer after filling missing values |
| P07 | Age | Impossible age (outside 18–75) | 29 | Phase 3: treat as missing |
| P08 | Work_Experience | Negative or above 50 years | 25 (15 + 10) | Phase 2: compare with Age. Phase 3: treat as missing |
| P09 | Monthly_Income | Negative income (looks like a sign error) | 22 | Phase 3: remove the minus sign |
| P10 | Monthly_Income | Zero income | 8 | Phase 3: treat as missing |
| P11 | CIBIL_Score | Outside 300–900 (not −1) | 33 | Phase 3: treat as missing |
| P12 | CIBIL_Score | −1 = no credit history (**valid**) | 602 | Phase 3/4: keep the meaning, for example with a separate flag |
| P13 | Loan_Tenure | Not a multiple of 12 (10, 15, 20, 25, 30) | 95 | Phase 2: check the loan type. If these are years, ×12 in Phase 3 |
| P14 | Coapplicant_Income | 67.9% blank; no zeros at all | 6,787 | Phase 2: confirm blank = no co-applicant, then fill with 0 in Phase 3 |
| P15 | Collateral_Value | 42.5% blank | 4,250 | Phase 2: check blanks by Loan_Type (unsecured or truly missing) |
| P16 | 10 columns | Small random missing values (1–3%) | 1,770 cells | Phase 3: fill (impute) |
| P17 | 5 money columns | Strong right skew; many real outliers | – | Phase 3: do not delete real values; consider log transform and capping |
| P18 | Gender, Marital_Status | Very small groups (Transgender 60, Divorced 95, Widowed 87) | – | Fairness audit: report with care (small samples) |

Detail for **P16**: Gender 179, Marital_Status 118, Dependents 240, Work_Experience 301, Monthly_Income 99, Existing_EMI 252, CIBIL_Score 99, Loan_Amount 152, Loan_Tenure 181, Property_Area 149.

---

## 6. Questions for Phase 2 (they need two or more columns)

1. **Coapplicant_Income blanks (P14).** Are blanks more common for Personal loans and Single applicants? That would support "no co-applicant".
2. **Collateral_Value blanks (P15).** What % is blank for each Loan_Type? We expect Personal loans to be almost all blank and Home and Vehicle loans to be almost never blank.
3. **Odd tenures (P13).** Which loan type do the 95 rows with tenure 10–30 belong to? If they are home loans, these are years.
4. **Work_Experience vs Age (P08).** How many rows have experience greater than (age − 18)?
5. **Age ↔ Work_Experience correlation.** Does it become strong once the invalid values are removed?
6. **Loan_Amount and Collateral by Loan_Type.** Are the big outliers home loans? Are the two humps in collateral vehicles and property?
7. **Each column vs Loan_Status.** How do CIBIL, income, EMI, loan type, employment type, tenure and area relate to approval?
8. **First fairness look.** What are the approval rates by Gender and Marital_Status? (Only to describe them; these columns must not be model inputs.)
9. **Multivariate.** Do income, EMI and loan amount together explain approval better than any one of them alone? This is a hint for Phase 4 ratio features such as FOIR.

---

## 7. Suggestions for Phase 3 (not done in this phase)

- Recommended order: remove duplicates → drop rows with no target → strip spaces and map spellings → fix types → turn invalid values into missing → fill missing values → treat outliers → transform → encode → scale.
- **Reuse from the notebook:** `valid_range` and `valid_categories` (Part A) and `plot_map` (Part C2).
- **Do not delete outliers in the money columns.** They are real customers. Capping or a log transform is safer.
- **Do not treat CIBIL −1 as a score.** Keep its meaning, for example with an "is new to credit" flag.
- **Gender and Marital_Status:** if they are missing, mark them as "Unknown". Never guess a protected attribute.

---

## 8. Files produced in Phase 1

| File | What it is |
|---|---|
| `phase1/phase1_domain_eda_univariate.ipynb` | All Phase 1 code with outputs |
| `phase1/preprocessing_phase1_report.md` | This report |
| `phase1/plots/*.png` | 19 plots used in this report |

**How to run:** open the notebook from inside the `phase1` folder and run all cells. It reads `../data/raw/loan_applications_raw.csv` and saves the plots to `plots/`. Libraries used: pandas, numpy, matplotlib, seaborn.

---

## Appendix A – Every spelling found (after removing extra spaces)

| Column | Spellings found → real category |
|---|---|
| Gender | `Male`, `male`, `MALE`, `M` → **Male**; `Female`, `female`, `FEMALE`, `F` → **Female**; `Transgender`, `transgender`, `TG` → **Transgender** |
| Marital_Status | `Married`, `married`, `MARRIED` → **Married**; `Single`, `single`, `Unmarried` → **Single**; `Divorced`, `divorced` → **Divorced**; `Widowed`, `widowed` → **Widowed** |
| Employment_Type | `Salaried`, `salaried`, `SALARIED`, `Service` → **Salaried**; `Self-Employed Professional`, `self-employed professional`, `Self Employed Professional`, `SEP` → **Self-Employed Professional**; `Self-Employed Non-Professional`, `Self Employed Business`, `Business Owner`, `SENP` → **Self-Employed Non-Professional** |
| Loan_Type | `Home Loan`, `home loan`, `Housing Loan`, `HL` → **Home Loan**; `Vehicle Loan`, `vehicle loan`, `Auto Loan`, `Car Loan` → **Vehicle Loan**; `Personal Loan`, `personal loan`, `Personal`, `PL` → **Personal Loan**; `Business Loan`, `business loan`, `MSME Loan`, `BL` → **Business Loan** |
| Property_Area | `Urban`, `urban`, `URBAN` → **Urban**; `Semi-Urban`, `semi-urban`, `Semi Urban`, `Semiurban` → **Semi-Urban**; `Rural`, `rural`, `RURAL` → **Rural** |

## Sources
- RBI – Guidelines on Fair Practices Code for Lenders: https://www.rbi.org.in/commonman/Upload/English/Notification/PDFs/36102.pdf
- RBI home-loan LTV limits (90% / 80% / 75%) and the CIBIL 750+ guideline: https://www.bajajfinserv.in/insights/rbi-guidelines-for-home-loan
- The other limits (minimum age, age at maturity, FOIR, minimum income, minimum experience, CIBIL cut-off of 650) are common bank-policy values used in this project, not RBI rules.
