"""
Generate a synthetic RAW loan-application dataset modelled on Indian retail-bank
underwriting (CIBIL, FOIR, RBI LTV caps, age-at-maturity, SEP/SENP taxonomy).

Step 1: simulate clean "true" applicant data.
Step 2: generate the historical decision (hard policy rules + soft credit score).
Step 3: corrupt the data the way a real LOS / branch export is corrupted
        (missing values, label variants, wrong dtypes, invalid entries,
        unit errors, duplicates, missing target).
"""
import numpy as np
import pandas as pd

SEED = 42
rng = np.random.default_rng(SEED)
N = 9_865          # unique applications
N_DUP = 135        # exact duplicate rows  -> raw total = 10,000
N_NO_TARGET = 18   # applications with no recorded decision

RATE = {"Home": 0.085, "Vehicle": 0.095, "Personal": 0.115, "Business": 0.130}


def emi(p, annual_rate, n):
    r = annual_rate / 12
    return p * r * (1 + r) ** n / ((1 + r) ** n - 1)


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


# ------------------------------------------------------------------ 1. true data
emp = rng.choice(["SAL", "SEP", "SENP"], N, p=[0.60, 0.15, 0.25])
gender = rng.choice(["Male", "Female", "Transgender"], N, p=[0.715, 0.280, 0.005])
area = rng.choice(["Urban", "Semi-Urban", "Rural"], N, p=[0.50, 0.30, 0.20])

age = np.where(emp == "SAL", rng.normal(35, 7.5, N),
      np.where(emp == "SEP", rng.normal(40, 9, N), rng.normal(42, 10, N)))
lo = np.where(emp == "SAL", 20, np.where(emp == "SEP", 24, 21))
hi = np.where(emp == "SAL", 62, 70)
age = np.clip(np.round(age), lo, hi).astype(int)

start_age = np.where(emp == "SAL", rng.integers(21, 26, N),
            np.where(emp == "SEP", rng.integers(26, 31, N), rng.integers(20, 30, N)))
exp_yrs = np.clip(age - start_age + rng.integers(-1, 2, N), 0, None).astype(int)

p_married = 0.92 * sigmoid((age - 28) / 2.5)
u = rng.random(N)
marital = np.where(u < p_married, "Married", "Single").astype(object)
dw = (age > 40) & (rng.random(N) < 0.05)
marital[dw] = rng.choice(["Divorced", "Widowed"], dw.sum())

dependents = np.where(marital == "Married",
                      rng.choice([0, 1, 2, 3, 4, 5], N, p=[.15, .30, .32, .15, .05, .03]),
                      rng.choice([0, 1, 2, 3], N, p=[.70, .18, .08, .04]))

base = np.select([emp == "SAL", emp == "SEP"], [42_000, 85_000], 55_000)
area_m = np.select([area == "Urban", area == "Semi-Urban"], [1.20, 0.95], 0.72)
gen_m = np.select([gender == "Female", gender == "Transgender"], [0.85, 0.80], 1.0)
sigma = np.select([emp == "SAL", emp == "SEP"], [0.45, 0.60], 0.70)
exp_m = 1.035 ** (np.minimum(exp_yrs, 25) - 8)
income = base * area_m * gen_m * exp_m * np.exp(rng.normal(0, sigma, N))
income = np.clip(np.round(income, -2), 8_000, None)

loan_type = np.empty(N, dtype=object)
for e, p in {"SAL": [.30, .25, .43, .02], "SEP": [.30, .20, .20, .30],
             "SENP": [.20, .20, .15, .45]}.items():
    m = emp == e
    loan_type[m] = rng.choice(["Home", "Vehicle", "Personal", "Business"], m.sum(), p=p)

p_co = pd.Series(loan_type).map({"Home": .65, "Vehicle": .25, "Personal": .10, "Business": .35}).values
p_co = np.clip(p_co + np.where(marital == "Married", 0.10, -0.15), 0.02, 0.95)
has_co = rng.random(N) < p_co
earning_co = has_co & (rng.random(N) > 0.15)          # 15% of co-applicants are non-earning
co_income = np.where(earning_co, 35_000 * area_m * np.exp(rng.normal(0, 0.55, N)), 0)
co_income = np.round(co_income, -2)
total_income = income + co_income

has_loans = rng.random(N) < np.clip(0.30 + 0.006 * (age - 25), 0.2, 0.6)
existing_emi = np.where(has_loans, total_income * rng.beta(2, 9, N), 0)
existing_emi = np.round(existing_emi, -2)

p_ntc = 0.03 + 0.12 * (age < 25) + 0.04 * (area == "Rural") + 0.03 * (~has_loans)
ntc = rng.random(N) < p_ntc
q = rng.normal(0, 1, N) + 0.25 * np.log(total_income / 50_000) - 0.8 * (existing_emi / total_income)
cibil = 745 + 55 * q
tail = rng.random(N) < 0.10
cibil[tail] = rng.normal(625, 55, tail.sum())
cibil = np.clip(np.round(cibil), 300, 900)
cibil = np.where(ntc, -1, cibil).astype(int)

mult = np.select(
    [loan_type == "Home", loan_type == "Vehicle", loan_type == "Personal"],
    [np.exp(rng.normal(np.log(35), 0.35, N)), np.exp(rng.normal(np.log(10), 0.45, N)),
     np.exp(rng.normal(np.log(7), 0.50, N))],
    np.exp(rng.normal(np.log(8), 0.55, N)))
loan_amt = mult * np.where(loan_type == "Home", total_income, income + 0.5 * co_income)
two_wheeler = (loan_type == "Vehicle") & (rng.random(N) < 0.25)
loan_amt[two_wheeler] = rng.uniform(50_000, 150_000, two_wheeler.sum())
lims = {"Home": (5e5, 3e7), "Vehicle": (5e4, 4e6), "Personal": (5e4, 4e6), "Business": (1e5, 2e7)}
for t, (a, b) in lims.items():
    m = loan_type == t
    loan_amt[m] = np.clip(loan_amt[m], a, b)
loan_amt = np.round(loan_amt, -4)
loan_amt[two_wheeler] = np.round(loan_amt[two_wheeler], -3)

TENURES = {"Home": ([120, 180, 240, 300, 360], [.10, .20, .35, .20, .15]),
           "Vehicle": ([36, 48, 60, 84], [.15, .25, .45, .15]),
           "Personal": ([12, 24, 36, 48, 60], [.08, .20, .30, .20, .22]),
           "Business": ([12, 24, 36, 48, 60, 84, 120], [.10, .15, .25, .15, .20, .10, .05])}
max_age = np.where(emp == "SAL", 60, 65)
tenure = np.zeros(N, dtype=int)
for i in range(N):
    opts, p = TENURES[loan_type[i]]
    t = rng.choice(opts, p=p)
    if rng.random() < 0.92:                         # most applicants pick a tenure that fits the age rule
        allowed = [o for o in opts if age[i] + o / 12 <= max_age[i]]
        if allowed and t not in allowed:
            t = max(allowed)
    tenure[i] = t
two = two_wheeler
tenure[two] = rng.choice([12, 24, 36], two.sum())

collateral = np.full(N, np.nan)
m = loan_type == "Home"
collateral[m] = loan_amt[m] / rng.beta(8, 4, m.sum()).clip(0.35, 0.98)
m = loan_type == "Vehicle"
collateral[m] = loan_amt[m] / rng.uniform(0.70, 1.00, m.sum())
m = (loan_type == "Business") & (rng.random(N) < 0.5)
collateral[m] = loan_amt[m] / rng.uniform(0.35, 0.75, m.sum())
collateral = np.round(collateral, -4)

# ------------------------------------------------------------------ 2. decision
rate = pd.Series(loan_type).map(RATE).values
new_emi = emi(loan_amt, rate, tenure)
foir = (existing_emi + new_emi) / total_income
foir_cap = np.select([total_income < 50_000, total_income < 100_000], [0.50, 0.55], 0.65)
ltv = loan_amt / collateral
ltv_cap = np.select([loan_amt <= 3e6, loan_amt <= 7.5e6], [0.90, 0.80], 0.75)
age_mat = age + tenure / 12

hard = (
    (age < 21)
    | (age_mat > max_age)
    | ((cibil != -1) & (cibil < 650))
    | (foir > foir_cap)
    | ((loan_type == "Home") & (ltv > ltv_cap))
    | (total_income < 15_000)
    | ((emp == "SAL") & (exp_yrs < 1))
    | ((emp != "SAL") & (exp_yrs < 3))
)

cib_eff = np.where(cibil == -1, 700, cibil)
coverage = np.nan_to_num(collateral / loan_amt, nan=0.0)
z = (
    0.70
    + 0.028 * (cib_eff - 720)
    - 7.0 * (foir - 0.35)
    + 0.6 * np.log(total_income / 50_000)
    + 0.9 * np.minimum(np.clip(coverage - 1, 0, None), 1.5)
    + 0.06 * np.minimum(exp_yrs, 15)
    + np.select([emp == "SEP", emp == "SENP"], [0.3, -0.35], 0)
    + pd.Series(loan_type).map({"Home": .5, "Vehicle": .3, "Personal": -.1, "Business": -.5}).values
    + np.select([area == "Urban", area == "Rural"], [0.15, -0.20], 0)
    - 0.9 * (cibil == -1) * np.isin(loan_type, ["Personal", "Business"])
    - 0.4 * (cibil == -1)
    - 0.12 * dependents
    # deliberately injected historical bias (documented) so the fairness audit has a signal to find
    + np.select([gender == "Female", gender == "Transgender"], [-0.35, -0.50], 0)
)
p_approve = np.where(hard, 0.03, sigmoid(z))
approved = rng.random(N) < p_approve

df = pd.DataFrame({
    "Loan_ID": [f"LN{2025000000 + i:010d}"[:12] for i in rng.permutation(np.arange(100001, 100001 + N))],
    "Age": age.astype(float),
    "Gender": gender.astype(object),
    "Marital_Status": marital,
    "Dependents": np.where(dependents >= 3, "3+", dependents.astype(str)).astype(object),
    "Employment_Type": pd.Series(emp).map({"SAL": "Salaried", "SEP": "Self-Employed Professional",
                                           "SENP": "Self-Employed Non-Professional"}).values.astype(object),
    "Work_Experience": exp_yrs.astype(float),
    "Monthly_Income": income,
    "Coapplicant_Income": np.where(co_income > 0, co_income, np.nan),   # LOS leaves blank when none
    "Existing_EMI": existing_emi,
    "CIBIL_Score": cibil.astype(float),
    "Loan_Type": pd.Series(loan_type).map({"Home": "Home Loan", "Vehicle": "Vehicle Loan",
                                           "Personal": "Personal Loan", "Business": "Business Loan"}).values.astype(object),
    "Loan_Amount": loan_amt.astype(object),
    "Loan_Tenure": tenure.astype(float),
    "Collateral_Value": collateral,
    "Property_Area": area.astype(object),
    "Loan_Status": np.where(approved, "Approved", "Rejected").astype(object),
})
truth = df.copy()   # clean version kept only for internal validation (not delivered)
truth["_hard_violation"] = hard

# ------------------------------------------------------------------ 3. corruption
def pick(frac=None, n=None, mask=None):
    idx = np.arange(N) if mask is None else np.flatnonzero(mask)
    k = n if n is not None else int(round(frac * len(idx)))
    return rng.choice(idx, k, replace=False)

# 3a. missing values (MCAR / MAR)
for col, frac in {"Gender": .018, "Marital_Status": .012, "Dependents": .024,
                  "Work_Experience": .030, "Existing_EMI": .025, "CIBIL_Score": .010,
                  "Loan_Amount": .015, "Loan_Tenure": .018, "Property_Area": .015,
                  "Monthly_Income": .010}.items():
    df.loc[pick(frac), col] = np.nan
sec = df["Collateral_Value"].notna().values
df.loc[pick(0.04, mask=sec), "Collateral_Value"] = np.nan

# 3b. invalid / impossible entries
df.loc[pick(n=28), "Age"] = rng.choice([0, 1, 5, 150, 200, 999, -30], 28)
df.loc[pick(n=22, mask=df["Monthly_Income"].notna().values), "Monthly_Income"] *= -1
df.loc[pick(n=8, mask=df["Monthly_Income"].notna().values), "Monthly_Income"] = 0
okc = df["CIBIL_Score"].notna().values & (df["CIBIL_Score"].values != -1)
df.loc[pick(n=32, mask=okc), "CIBIL_Score"] = rng.choice([0, 100, 999, 1000, 9999], 32)
oke = df["Work_Experience"].notna().values
bad_exp = pick(n=45, mask=oke)
df.loc[bad_exp[:30], "Work_Experience"] = df.loc[bad_exp[:30], "Age"].abs() + rng.integers(2, 15, 30)
df.loc[bad_exp[30:], "Work_Experience"] = -rng.integers(1, 4, 15)

# 3c. unit error: some home-loan tenures keyed in YEARS instead of months
okt = (truth["Loan_Type"].values == "Home Loan") & df["Loan_Tenure"].notna().values
yrs_idx = pick(0.035, mask=okt)
df.loc[yrs_idx, "Loan_Tenure"] = df.loc[yrs_idx, "Loan_Tenure"] / 12

# 3d. dtype pollution: Indian digit-grouped strings in Loan_Amount (e.g. "12,50,000")
def inr(x):
    s = str(int(x))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:]); head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail
okl = df["Loan_Amount"].notna().values
for i in pick(0.05, mask=okl):
    df.at[i, "Loan_Amount"] = inr(df.at[i, "Loan_Amount"])
for i in pick(0.01, mask=okl):
    if not isinstance(df.at[i, "Loan_Amount"], str):
        df.at[i, "Loan_Amount"] = "Rs. " + inr(df.at[i, "Loan_Amount"])

# 3e. inconsistent category labels + stray whitespace
VARIANTS = {
    "Gender": {"Male": ["M", "male", "MALE"], "Female": ["F", "female", "FEMALE"],
               "Transgender": ["TG", "transgender"]},
    "Marital_Status": {"Married": ["married", "MARRIED"], "Single": ["Unmarried", "single"],
                       "Divorced": ["divorced"], "Widowed": ["widowed"]},
    "Employment_Type": {"Salaried": ["salaried", "SALARIED", "Service"],
                        "Self-Employed Professional": ["SEP", "Self Employed Professional", "self-employed professional"],
                        "Self-Employed Non-Professional": ["SENP", "Self Employed Business", "Business Owner"]},
    "Loan_Type": {"Home Loan": ["Housing Loan", "home loan", "HL"], "Vehicle Loan": ["Auto Loan", "Car Loan", "vehicle loan"],
                  "Personal Loan": ["PL", "personal loan", "Personal"], "Business Loan": ["MSME Loan", "business loan", "BL"]},
    "Property_Area": {"Urban": ["urban", "URBAN"], "Semi-Urban": ["Semiurban", "Semi Urban", "semi-urban"],
                      "Rural": ["rural", "RURAL"]},
}
for col, vmap in VARIANTS.items():
    for i in pick(0.08, mask=df[col].notna().values):
        v = df.at[i, col]
        df.at[i, col] = rng.choice(vmap[v])
    for i in pick(0.02, mask=df[col].notna().values):
        df.at[i, col] = df.at[i, col] + rng.choice([" ", "  "])

# 3f. missing target (decision not recorded)
df.loc[pick(n=N_NO_TARGET), "Loan_Status"] = np.nan

# 3g. exact duplicates (double-submitted applications), then shuffle
dups = df.iloc[rng.choice(N, N_DUP, replace=False)]
raw = pd.concat([df, dups]).sample(frac=1, random_state=SEED).reset_index(drop=True)

raw.to_csv("loan_applications_raw.csv", index=False)
truth.to_pickle("_truth.pkl")
print(raw.shape)
print(raw["Loan_Status"].value_counts(dropna=False, normalize=True).round(3))
print("hard-rule violators:", hard.mean().round(3), " approval among non-violators:", approved[~hard].mean().round(3))
