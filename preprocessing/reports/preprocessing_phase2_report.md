# Preprocessing Phase 2 Report
## Exploring Relationships Between Variables (Bivariate and Multivariate Analysis)

| | |
|---|---|
| **Project** | CogniLend – Loan Approval Decision-Support System |
| **Phase** | 2 of 4 (Bivariate + Multivariate analysis) |
| **Input data** | `data/raw/loan_applications_raw.csv` (10,000 rows × 17 columns, unchanged) |
| **Input report** | `phase1/preprocessing_phase1_report.md` (issue IDs P01–P18 and 9 questions for Phase 2) |
| **Code** | `phase2/phase2_bivariate_multivariate.ipynb` |
| **Plots** | `phase2/plots/` (30 images) |
| **Next phase** | Phase 3 – Cleaning and feature transformation |

---

## 0. Quick summary (read this first)

**All 9 questions from Phase 1 are answered** (Section 3):
- **Coapplicant_Income blank = no co-applicant**, so it should become 0.
- **Collateral_Value blank:**
  - Personal and Business loans → unsecured (0).
  - Home and Vehicle loans (209 rows) → really missing.
- **All 95 odd tenures are home loans typed in years** (×12).
- **21 more invalid experience values** (experience greater than age − 18).
- **Age and Work_Experience are almost the same information** (correlation 0.94).

**The data has hard "walls".** In these groups almost nobody is approved, which matches the bank and RBI rules from Phase 1:

| Group | Approval |
|---|---|
| CIBIL below 650 | 2–3% |
| Age 20 | 3.3% |
| 0 years experience | 2.4% |
| Self-employed with under 3 years | 1.5–3.9% |
| Home loan above the RBI LTV limit | 2.8% |

**CIBIL is the strongest single column** (Spearman 0.37 with approval). Every other column is weak on its own.

**Columns matter in combination.** Approval depends on the loan **compared with** income, the EMI **compared with** income, the loan **compared with** collateral, and age **plus** tenure. This is strong evidence for ratio features in Phase 4.

**Marital_Status and Dependents look like "age in disguise".** Inside the same age group their effect mostly disappears.

**Fairness first look:**
- The Female/Male approval ratio is **0.936**.
- Part of the gap comes from the income gap, but **women are approved a little less in every income group**.
- The fairness audit must keep checking this.

**The real data was not changed.** Six new issues are added: **P19–P24** (Section 8).

---

## 1. What we did and what we did not do

| Done in Phase 2 | Not done (left for later phases) |
|---|---|
| Answered the 9 questions left by Phase 1 | Removing duplicates, fixing types, filling missing values (Phase 3) |
| Compared every column with Loan_Status (bivariate) | Fixing the tenure units or bad values in the real data (Phase 3) |
| Compared columns with each other (bivariate) | Outlier treatment, scaling, encoding (Phase 3) |
| Studied three or more columns together (multivariate) | Creating new features such as FOIR, or selecting features (Phase 4) |
| First fairness look (gender inside income groups) | Training any model |

**How we kept to the phase rule:** all plots use a **temporary copy** called `plot_df`, which is never saved. The last cell reloads the CSV and confirms the real `df` is unchanged.

---

## 2. The temporary plotting copy

These are the same basic fixes Phase 1 used for plotting, applied once to `plot_df`.

| Basic fix (plotting only) | Rows affected | Why |
|---|---|---|
| Joined spellings with `plot_map` (copied from Phase 1) | ~4,861 cells | So `HL` and `Home Loan` count as one group |
| Loan_Amount text → number | 584 cells | So it can be plotted (no value is lost) |
| Impossible values hidden: Age (29), Work_Experience (25), Monthly_Income ≤ 0 (30), CIBIL outside 300–900 (33) | 117 cells | So they don't spoil the plots |
| Odd tenures hidden, only from Part B3 onward (after A3 had studied them) | 95 cells | They are years, not months |
| `approved` = 1/0 from Loan_Status | – | To calculate the approval rate (%) |

- 9,982 rows have a target. The **overall approval rate is 58.49%**, shown as the dashed line in the approval-rate plots.
- The 135 duplicate rows are still inside. They are only 1.35% of the data, so they do not change any conclusion.
- Short names used in plots: **SEP** = Self-Employed Professional, **SENP** = Self-Employed Non-Professional.

---

## 3. Answers to the questions from Phase 1

### Q1. Does a blank Coapplicant_Income mean "no co-applicant"? (P14) → **Yes**
![Co-applicant blanks](plots/a1_coapplicant_blank_by_group.png)
- Blanks are **lowest for Home loans (40.8%)** and **highest for Personal loans (87.2%)**. Married applicants have fewer blanks (62.9%) than Single (83.0%) or Divorced (85.3%) applicants.
- This matches real life: home loans and married couples usually have a co-applicant.
- No row in the data has 0 in this column, and the smallest value present is ₹4,600.
- **Decision for Phase 3: fill the blanks with 0, not with the median.**

### Q2. Does a blank Collateral_Value mean "unsecured"? (P15) → **Depends on the loan type**
![Collateral blanks](plots/a2_collateral_blank_by_loan_type.png)

| Loan type | Blank rows | Meaning | Suggested Phase 3 action |
|---|---|---|---|
| Personal | 3,215 (**100%**) | Always unsecured | Fill with 0 |
| Business | 826 (**50.3%**) | About half are secured | Fill with 0 (unsecured, the cautious choice) |
| Home | 121 (**4.3%**) | A home loan always has a property | **Really missing → estimate** |
| Vehicle | 88 (**3.8%**) | A vehicle loan always has the vehicle | **Really missing → estimate** |

### Q3. Which loan type has the odd tenures 10, 15, 20, 25, 30? (P13) → **All 95 are Home loans**
![Tenure by loan type](plots/a3_tenure_by_loan_type.png)

Home loans otherwise only use 120, 180, 240, 300 and 360 months, and 10/15/20/25/30 × 12 gives exactly those values. **These are years typed instead of months. Phase 3 should multiply them by 12.**

### Q4. Is experience ever more than (age − 18)? (P08) → **Yes, 21 more rows**
![Age vs experience](plots/a4_age_vs_experience.png)

For example, one applicant is 32 years old with 37 years of experience. Each value looks fine alone, so Phase 1 could not catch these. All other points sit under the line. **Phase 3: treat these 21 values as invalid, together with the 25 found in Phase 1.** (New issue **P19**.)

### Q5. Is Age ↔ Work_Experience strong once the bad values are removed? → **Yes, 0.937**
The correlation was 0.279 on raw data and becomes **0.937** with the bad values hidden. The low raw value was caused only by the impossible ages. **The two columns carry almost the same information.** (New issue **P21**, for Phase 4.)

### Q6. Where do the big loan amounts and the two collateral humps come from? → **Home loans and vehicles**
![Amount and collateral by type](plots/a6_amount_collateral_by_loan_type.png)
- **822 of the 857 Loan_Amount outliers are Home loans** (the other 35 are Business loans). Median loan amount: Home ₹28 L, Business ₹6.3 L, Vehicle ₹4.2 L, Personal ₹3.7 L.
- Median collateral: Home ₹42.6 L, Business ₹12.2 L, Vehicle ₹4.9 L. The two humps in Phase 1 are **vehicles (small) and property (big)**.
- **These are real values. Do not delete them in Phase 3.**

### Extra check for Phase 3: are the small missing values random?

| Column | Missing | Approval when missing | Approval when present | p-value |
|---|---|---|---|---|
| Gender | 179 | 62.7% | 58.4% | 0.283 |
| Marital_Status | 118 | 62.7% | 58.4% | 0.399 |
| Dependents | 240 | 58.2% | 58.5% | 0.970 |
| Work_Experience | 301 | 55.8% | 58.6% | 0.370 |
| Monthly_Income | 99 | 63.6% | 58.4% | 0.346 |
| Existing_EMI | 252 | 56.0% | 58.6% | 0.446 |
| CIBIL_Score | 99 | 51.5% | 58.6% | 0.190 |
| Loan_Amount | 152 | 55.9% | 58.5% | 0.573 |
| Loan_Tenure | 181 | 67.4% | 58.3% | **0.017** |
| Property_Area | 149 | 59.1% | 58.5% | 0.952 |

- **9 of the 10 columns show no real difference** (p > 0.05). Only Loan_Tenure shows one, and only for 181 rows. With 10 tests, one small p-value can easily appear by chance.
- **Conclusion: the small missing values look random.** Simple filling (median or mode, possibly inside groups) is fine for Phase 3.

Questions 7–9 are answered in Sections 4–6.

---

## 4. Each column vs the target (Loan_Status)

### 4.1 Categorical columns
![Categorical vs target](plots/b1_categorical_vs_target.png)

| Column | Lowest → highest approval | Gap (points) | Chi-square p | Note |
|---|---|---|---|---|
| Marital_Status | Single **43.6%** → Divorced 64.2% (Married 62.9%) | 20.6 | < 0.001 | Mostly an **age** effect (see 6.6) |
| Loan_Type | Home **52.3%** → Vehicle **67.5%** | 15.2 | < 0.001 | Home loans are the hardest to get |
| Property_Area | Rural **52.1%** → Urban **61.7%** | 9.7 | < 0.001 | Rural applicants earn less |
| Dependents | 0 → **53.4%** … 3+ → 61.8% | 8.4 | < 0.001 | Looks strange; it is also **age** (see 6.6) |
| Gender | Transgender 55.0%, Female 55.7% → Male **59.5%** | 4.5 | 0.002 | See the fairness look in 6.7 |
| Employment_Type | SENP 56.7% → Salaried 59.5% | 2.8 | 0.036 | Weak on its own |

### 4.2 CIBIL_Score – the strongest column
![CIBIL vs target](plots/b2_cibil_vs_target.png)

| CIBIL band | Rows | Approval |
|---|---|---|
| No history (−1) | 602 | 41.7% |
| 300–599 | 292 | **1.7%** |
| 600–649 | 660 | **3.3%** |
| 650–699 | 1,556 | 49.9% |
| 700–749 | 2,750 | 63.7% |
| 750–799 | 2,594 | 72.2% |
| 800–900 | 1,396 | 77.9% |

- **There is a wall at 650**, matching the bank rule "CIBIL ≥ 650". Above it, approval rises smoothly.
- **No history (−1)** gets 41.7%. These applicants are not treated like bad scorers, so **−1 must stay a separate group** (P12) and must not be treated as a very low number.
- Median scored CIBIL: Approved **755**, Rejected **707**.

### 4.3 Numerical columns
Each plot shows the boxplot (Approved vs Rejected) on the left and the approval rate per value group on the right.

**Age**
![Age vs target](plots/b3_age_vs_target.png)
- Age **18–20 gets only 3.3%** approval, a wall at the minimum age of 21.
- Approval peaks around 66% for ages 36–50, then **drops: 56–60 → 52.9%, 61+ → 24.4%**. These older applicants probably fail the **age-at-loan-end** rule, which needs age **and** tenure together.

**Work_Experience**
![Experience vs target](plots/b3_experience_vs_target.png)
- **0 years: 2.4% approval** (676 rows).
- Split by job type (approval %):

| Experience | Salaried | SEP | SENP |
|---|---|---|---|
| 0 years | 2.7 | 1.3 | 2.6 |
| 1–2 years | **62.4** | **3.9** | **1.5** |
| 3–5 years | 60.6 | 65.8 | 57.7 |
| 6+ years | 64.3 | 67.8 | 61.7 |

- This matches the rule "**1 year for salaried, 3 years for self-employed**". **Work_Experience must be read together with Employment_Type.**

**Monthly_Income**
![Income vs target](plots/b3_income_vs_target.png)
- Applicants **below ₹15,000 get 17.9% approval**. Above that, approval rises smoothly from 46.0% to 71.7% (₹2 L+).
- This wall is softer than the others, probably because the rule uses **total** income. A co-applicant can lift a low earner above ₹15,000.
- Median income: Approved ₹60,600, Rejected ₹48,600.

**Coapplicant_Income**
![Co-applicant vs target](plots/b3_coapplicant_vs_target.png)
- Blank (no co-applicant): 57.1%. Higher co-applicant income means higher approval: 55.6% (below ₹20k) up to **66.6% (₹50k+)**. The co-applicant's income **helps**.

**Existing_EMI**
![EMI vs target](plots/b3_emi_vs_target.png)
- **No existing loan: 64.4%.** Any existing EMI: about 47–53%. Above ₹5,000 the rate is flat, so the EMI size **alone** is not enough. It must be **compared with income** (see 6.4).

**Loan_Amount**
![Amount vs target](plots/b3_amount_vs_target.png)
- Flat (59–62%) up to ₹25 L, then lower: ₹50 L–1 Cr → 44.4%, ₹1 Cr+ → 42.0%.
- Weak alone, because a big loan is fine for a high earner (see 6.3).

**Loan_Tenure** (odd values hidden)
![Tenure vs target](plots/b3_tenure_vs_target.png)
- **12 months: 38.0%.** A short tenure gives a big EMI, which can fail affordability.
- **360 months: 32.6%.** A 30-year loan often ends after age 60/65.
- 84 months is the highest at 72.0%.
- Tenure is useless alone (Spearman 0.017) but matters **with amount and with age**.

**Collateral_Value**
![Collateral vs target](plots/b3_collateral_vs_target.png)
- Bigger collateral → **lower** approval (65.6% below ₹5 L, 50.7% at ₹60 L+). This is because big collateral means big **home loans**. Collateral alone is misleading; it must be **compared with the loan** (see 6.5).

### 4.4 Which numeric column is most linked to approval?
![Spearman with target](plots/b4_spearman_with_target.png)

| Column | Spearman with approval |
|---|---|
| CIBIL_Score | **+0.366** |
| Work_Experience | +0.165 |
| Age | +0.159 |
| Monthly_Income | +0.156 |
| Coapplicant_Income | +0.078 |
| Loan_Tenure | +0.017 |
| Loan_Amount | −0.064 |
| Collateral_Value | −0.116 |
| Existing_EMI | −0.153 |

**Only CIBIL is strong alone.** The others are weak alone, but Section 6 shows that many of them matter in combination.

---

## 5. Columns vs each other

### 5.1 Correlation between numeric columns
![Feature correlation](plots/c1_feature_correlation.png)

| Pair | Spearman | Meaning |
|---|---|---|
| Loan_Amount ↔ Collateral_Value | **0.98** | For secured loans, collateral is almost the loan amount divided by the LTV |
| Age ↔ Work_Experience | **0.94** | Almost the same information |
| Loan_Tenure ↔ Collateral_Value | 0.69 | Long tenures belong to big home loans |
| Loan_Amount ↔ Loan_Tenure | 0.61 | Same reason |
| Monthly_Income ↔ Loan_Amount | 0.47 | Richer people borrow more |
| Monthly_Income ↔ Age | 0.45 | Older people earn more |

**CIBIL_Score is almost unrelated to every other column**, so it brings unique information.

### 5.2 Income by group
![Income by groups](plots/c2_income_by_groups.png)
- **Employment:** SEP ₹91,650 > SENP ₹69,900 > Salaried ₹46,700 (medians).
- **Area:** Urban ₹65,400 > Semi-Urban ₹51,600 > Rural ₹39,100. This partly explains the lower rural approval.
- **Gender:** Male ₹58,100, Transgender ₹52,200, Female ₹48,500. This **income gap** partly explains the gender approval gap.

### 5.3 Employment type vs loan type
![Employment vs loan type](plots/c3_employment_vs_loan_type.png)
- Salaried applicants mostly take Personal loans (42.6%) and almost never Business loans (1.6%).
- SENP applicants mostly take Business loans (45.2%).
- The two columns are linked, so their effects mix together (see 6.8).

### 5.4 Age by marital status and dependents
![Age by marital and dependents](plots/c4_age_by_marital_dependents.png)
- **Single applicants are much younger** (median 28) than Married applicants (39) and Divorced or Widowed applicants (45).
- Applicants with 0 dependents are younger (33) than those with 3+ (39).

---

## 6. Multivariate analysis

### 6.1 Pair plot (1,500 random rows)
![Pair plot](plots/d1_pairplot.png)

CIBIL separates the classes best (below about 650 almost every point is orange). The rows with 0 years of experience form an orange line. No single plot separates the classes fully.

### 6.2 CIBIL × income
![CIBIL x income](plots/d2_cibil_income_heatmap.png)
- **Below 650, approval is 2–4% in every income quartile.** Even the richest applicants are rejected, so this is a **hard rule**.
- From 650 upward, **both** score and income raise approval: from 39.1% (650–699, lowest income) to 82.7% (800+, highest income).

### 6.3 Income × loan size (answer to Phase 1 question 9)
![Income vs amount by type](plots/d3_income_vs_amount_by_type.png)
![Amount x income](plots/d3_amount_income_heatmap.png)

Loan size is measured inside each loan type, because a "big" personal loan is not the same as a "big" home loan.

| | Low income | Middle income | High income |
|---|---|---|---|
| Small loan | 51.6% | 69.1% | **81.6%** |
| Medium loan | 46.4% | 61.5% | 74.5% |
| Big loan | **36.7%** | 46.8% | 61.5% |

**For the same income, a bigger loan lowers approval. For the same loan, a higher income raises it.** What matters is the **loan compared with the income**. This is direct evidence for ratio features in Phase 4.

### 6.4 Existing EMI × income
![EMI vs income](plots/d4_emi_vs_income.png)

For the same income, a higher existing EMI is more often rejected, and rejected points crowd near the "EMI = 50% of income" line. **The EMI compared with income is what counts**; this is the idea behind FOIR.

### 6.5 Home loans: loan amount vs property value (RBI LTV rule)
![Home LTV](plots/d5_home_ltv_scatter.png)
- **248 home loans** ask for more than the RBI limit: 90% of the property value up to ₹30 L, 80% for ₹30–75 L, 75% above ₹75 L.
- **Approval above the limit is 2.8%**; within the limit it is 57.1%. **This is a hard wall that matches the RBI rule.**
- The few approvals above the limit look like **past exceptions**, which the rule engine must block. (New issue **P24**.)

### 6.6 Marital status and dependents inside age groups (confounding)
![Marital x age](plots/d6_marital_age_heatmap.png)
![Dependents x age](plots/d6_dependents_age_heatmap.png)
- Inside the same age group, Married and Single applicants are close: 65.3% vs 64.9% at ages 36–45. At 46–55, Single is even higher (68.9% vs 65.5%).
- The big overall gap comes from **719 of the 806 applicants aged 18–25 being Single**, and young applicants fail the age and experience rules.
- Dependents show **no clear pattern** inside an age group.
- **Conclusion: Marital_Status and Dependents mostly carry age information** (confounding). A gap of about 10 points remains at ages 26–35. (New issue **P22**.)

### 6.7 Fairness first look: gender inside income quartiles
![Gender x income](plots/d7_gender_income_approval.png)

| Income quartile | Male | Female | Gap (points) |
|---|---|---|---|
| Q1 (lowest) | 49.2% | 44.7% | 4.5 |
| Q2 | 57.4% | 55.9% | 1.5 |
| Q3 | 62.5% | 61.8% | 0.7 |
| Q4 (highest) | 67.0% | 66.2% | 0.8 |
| **Overall** | **59.5%** | **55.7%** | **3.8** |

- The **Female/Male approval ratio is 0.936**. This is above the common "80% rule" threshold of 0.8, but it is still a gap.
- Women earn less (5.2), which explains **part** of the gap. **Inside every income quartile women are still approved a little less**, so income does not explain all of it. (New issue **P23**.)
- Transgender applicants are only **59 rows** with a target (11–18 per quartile). Their rates jump around and **cannot be trusted** for conclusions (P18).
- We only describe this here. Gender must **not** be a model input.

### 6.8 Employment type × loan type
![Employment x loan type](plots/d8_employment_loan_heatmap.png)
**Home loans have the lowest approval for every employment group** (47.0–54.1%) and **Vehicle loans the highest** (66.8–67.8%). Loan type matters more than employment type.

---

## 7. Hard-rule "walls" found in the data

These match the bank and RBI norms listed in the Phase 1 report (Section 2.4). They are useful for the **rule engine** team as well as for Phase 4.

| Wall | Approval inside the wall | Approval outside | Matching norm |
|---|---|---|---|
| CIBIL 300–649 | 1.7–3.3% | 49.9–77.9% | CIBIL ≥ 650 (bank policy) |
| Age 18–20 | 3.3% | 21.4–66.1% | Minimum age 21 (bank policy) |
| Work_Experience = 0 | 2.4% | 39.8–65.9% | Minimum experience (bank policy) |
| Self-employed with 1–2 years | 1.5–3.9% | Salaried 1–2 years: 62.4% | 3 years of business for SEP/SENP (bank policy) |
| Home loan above the RBI LTV limit | 2.8% | 57.1% | **RBI LTV cap (regulation)** |
| Monthly_Income below ₹15,000 | 17.9% (softer) | 46.0–71.7% | Minimum income ₹15,000 (on total income) |
| Age 61+ / tenure 360 months | 24.4% / 32.6% | – | Age at loan end ≤ 60/65 (needs age + tenure) |

---

## 8. Updated issue log

### 8.1 Status of the Phase 1 issues

| ID | Issue (from Phase 1) | Status after Phase 2 | Action for the next phase |
|---|---|---|---|
| P01 | 135 duplicate rows | Unchanged; too few to change any conclusion | Phase 3: remove |
| P02 | 18 rows with no target | Unchanged | Phase 3: drop |
| P03 | Spelling variants (4,861 cells) | `plot_map` joins **every** spelling correctly | Phase 3: reuse `plot_map` |
| P04 | Loan_Amount stored as text (584) | Conversion loses no value | Phase 3: remove `Rs.` and commas, convert |
| P05 | Dependents `3+` | Unchanged | Phase 3: convert to 3 |
| P06 | Whole numbers stored as decimals | Unchanged | Phase 3: convert to integer |
| P07 | Impossible Age (29) | Unchanged | Phase 3: treat as missing |
| P08 | Invalid Work_Experience (25) | **Updated: 21 more found (P19)** | Phase 3: treat all 46 as missing |
| P09 | Negative income (22) | Unchanged | Phase 3: remove the minus sign |
| P10 | Zero income (8) | Unchanged | Phase 3: treat as missing |
| P11 | CIBIL outside 300–900 (33) | Unchanged | Phase 3: treat as missing |
| P12 | CIBIL −1 (602) | **Confirmed as its own group** (41.7% approval) | Phase 3/4: keep the meaning with a flag |
| P13 | Odd tenures (95) | **Confirmed: all home loans, years** | Phase 3: × 12 |
| P14 | Coapplicant_Income blank (6,787) | **Confirmed: no co-applicant** | Phase 3: fill with 0 |
| P15 | Collateral_Value blank (4,250) | **Split:** Personal/Business = unsecured; Home/Vehicle 209 rows = really missing (P20) | Phase 3: 0 for unsecured, estimate for Home/Vehicle |
| P16 | Small random missing values | **Confirmed random** (9 of 10 columns p > 0.05) | Phase 3: median/mode filling is fine |
| P17 | Skewed money columns with outliers | **Explained:** outliers are big home loans and rich applicants | Phase 3: keep them; consider a log transform or capping |
| P18 | Very small groups | Confirmed (Transgender n = 59 with a target) | Fairness audit: report with care |

### 8.2 New issues found in Phase 2

| ID | Column(s) | Issue | Count / evidence | Suggested next step |
|---|---|---|---|---|
| **P19** | Work_Experience, Age | Experience greater than (age − 18) | 21 rows | Phase 3: treat as missing (with P08) |
| **P20** | Collateral_Value | Really missing on loans that always have collateral | Home 121, Vehicle 88 | Phase 3: estimate from Loan_Amount and the usual loan-to-value of that loan type |
| **P21** | Age ↔ Work_Experience; Loan_Amount ↔ Collateral_Value | Very strong correlation (redundant) | 0.94 and 0.98 | Phase 4: keep one, or use a ratio |
| **P22** | Marital_Status, Dependents | Effect on approval is mostly **age** (confounding) | Gap disappears inside age groups | Phase 4: not useful as model inputs (Marital_Status is also protected) |
| **P23** | Gender | Gap remains inside every income quartile | F/M ratio 0.936 | Fairness audit: check model predictions per group |
| **P24** | All rule columns | A few past approvals break hard rules (for example 2.8% above the LTV limit) | See Section 7 | Rule engine must override; Phase 4: keep in mind when training |

---

## 9. Hand-over to Phase 3 (cleaning and transformation)

| Column | What Phase 2 found | Suggested Phase 3 action |
|---|---|---|
| Coapplicant_Income | Blank = no co-applicant | Fill with **0** |
| Collateral_Value | Personal/Business blank = unsecured; Home/Vehicle blank = missing | 0 for Personal/Business; **estimate** for 209 Home/Vehicle rows |
| Loan_Tenure | 95 home-loan values are years | **× 12** |
| Work_Experience | 25 + 21 invalid | Treat as missing, then fill (for example, median per employment type) |
| Small missing values | Random | Median/mode filling, possibly inside groups (employment type, area, loan type) |
| Money columns | Outliers are real | **Do not delete.** Consider a log transform and/or capping |
| CIBIL −1 | Its own group | Keep its meaning (flag), then give it a neutral score |
| Gender, Marital_Status | Protected | If missing, mark as "Unknown"; never guess |

## 10. Hand-over to Phase 4 (feature engineering)

| Feature idea | Evidence from Phase 2 |
|---|---|
| **Total income** = applicant + co-applicant | Co-applicant income raises approval (55.6% → 66.6%) |
| **EMI-to-income ratio (FOIR)**, including the new loan's EMI | EMI matters only compared with income (6.4); 12-month tenures (big EMI) get 38% |
| **Loan-to-income ratio** | Small loan + high income 81.6% vs big loan + low income 36.7% (6.3) |
| **Collateral ÷ loan** (inverse of LTV) | Above the LTV limit: 2.8% vs 57.1% (6.5); also removes the 0.98 redundancy |
| **Age at loan end** = age + tenure | Age 61+ 24.4%, tenure 360 months 32.6% (4.3) |
| **New-to-credit flag** (CIBIL −1) | Its own approval level, 41.7% (4.2) |
| **Experience read with employment type** | The 1-year vs 3-year rule (4.3) |
| **Redundancy** | Age ↔ Work_Experience 0.94: keep one or use age at loan end |
| **Do not use** Gender or Marital_Status | Protected attributes; Marital_Status and Dependents are mostly age (P22) |

---

## 11. Files produced in Phase 2

| File | What it is |
|---|---|
| `phase2/phase2_bivariate_multivariate.ipynb` | All Phase 2 code with outputs |
| `phase2/preprocessing_phase2_report.md` | This report |
| `phase2/plots/*.png` | 30 plots used in this report |

**How to run:** open the notebook from inside the `phase2` folder and run all cells. It reads `../data/raw/loan_applications_raw.csv`. Libraries used: pandas, numpy, matplotlib, seaborn, scipy.
