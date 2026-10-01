"""
Cognilend hybrid loan-approval engine.

    raw application
      -> clean()               stateless: whitespace, spellings, dtypes, domain-validity fixes (+ data-quality flags)
      -> Imputer               fitted on training data only (+ imputation flags)
      -> build_features()      stateless: FOIR, LTV, coverage, age at maturity, policy headroom, rule flags
      -> evaluate_rules()      hard policy R1-R7 (independent of the model)
      -> model                 gradient boosting probability of approval
      -> decide()              APPROVE / REJECT / MANUAL_REVIEW with written reasons

Every threshold used by the policy lives in POLICY so it can be audited and changed in one place.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

# --------------------------------------------------------------------------------------
# Policy and reference constants
# --------------------------------------------------------------------------------------
POLICY = {
    'min_age': 21,                                            # R1
    'max_maturity_age': {'Salaried': 60, 'SEP': 65, 'SENP': 65},   # R2
    'min_cibil': 650,                                         # R3 (NTC = -1 passes to scoring)
    'foir_slabs': [(50_000, 0.50), (100_000, 0.55), (np.inf, 0.65)],  # R4: income < 50k / <= 1L / above
    'ltv_slabs': [(3_000_000, 0.90), (7_500_000, 0.80), (np.inf, 0.75)],  # R5: RBI housing-loan caps
    'min_total_income': 15_000,                               # R6
    'min_experience': {'Salaried': 1, 'SEP': 3, 'SENP': 3},   # R7
}
INDICATIVE_RATES = {'Home': 0.085, 'Vehicle': 0.095, 'Personal': 0.115, 'Business': 0.13}
SECURED_TYPES = ('Home', 'Vehicle')

RULE_TEXT = {
    'R1': 'Applicant is younger than the minimum age of {min_age}',
    'R2': 'Age at loan maturity ({age_at_maturity:.1f}) exceeds the limit of {max_maturity_age} for {Employment_Type}',
    'R3': 'CIBIL score {CIBIL_Score:.0f} is below the minimum of {min_cibil}',
    'R4': 'FOIR {foir:.0%} exceeds the limit of {foir_limit:.0%} for this income level',
    'R5': 'Loan-to-value {ltv:.0%} exceeds the RBI housing-loan cap of {ltv_cap:.0%}',
    'R6': 'Total monthly income Rs {total_income:,.0f} is below the minimum of Rs {min_total_income:,}',
    'R7': 'Work experience / business vintage of {Work_Experience:.0f} yrs is below the minimum of {min_experience} for {Employment_Type}',
}
RULES = list(RULE_TEXT)

CATEGORY_MAPS = {
    'Gender': {'m': 'Male', 'male': 'Male', 'f': 'Female', 'female': 'Female',
               'tg': 'Transgender', 'transgender': 'Transgender'},
    'Marital_Status': {'married': 'Married', 'single': 'Single', 'unmarried': 'Single',
                       'divorced': 'Divorced', 'widowed': 'Widowed'},
    'Employment_Type': {'salaried': 'Salaried', 'service': 'Salaried',
                        'sep': 'SEP', 'self employed professional': 'SEP',
                        'self-employed professional': 'SEP',
                        'senp': 'SENP', 'self-employed non-professional': 'SENP',
                        'self employed business': 'SENP', 'business owner': 'SENP'},
    'Loan_Type': {'hl': 'Home', 'home loan': 'Home', 'housing loan': 'Home', 'home': 'Home',
                  'auto loan': 'Vehicle', 'car loan': 'Vehicle', 'vehicle loan': 'Vehicle', 'vehicle': 'Vehicle',
                  'pl': 'Personal', 'personal': 'Personal', 'personal loan': 'Personal',
                  'bl': 'Business', 'business loan': 'Business', 'msme loan': 'Business', 'business': 'Business'},
    'Property_Area': {'urban': 'Urban', 'semiurban': 'Semi-Urban', 'semi urban': 'Semi-Urban',
                      'semi-urban': 'Semi-Urban', 'rural': 'Rural'},
    'Loan_Status': {'approved': 'Approved', 'rejected': 'Rejected'},
}
# Canonical labels map to themselves too, so already-clean input passes through
for _m in CATEGORY_MAPS.values():
    _m.update({v.lower(): v for v in list(_m.values())})

NUMERIC_COLS = ['Age', 'Dependents', 'Work_Experience', 'Monthly_Income', 'Coapplicant_Income',
                'Existing_EMI', 'CIBIL_Score', 'Loan_Amount', 'Loan_Tenure', 'Collateral_Value']
PROTECTED = ['Gender', 'Marital_Status']


# --------------------------------------------------------------------------------------
# 1. Cleaning (stateless, row-wise: safe to run before the train/test split)
# --------------------------------------------------------------------------------------
def _to_number(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float)
    s = s.astype('string').str.replace(r'(?i)rs\.?|₹|,|\s', '', regex=True).replace('3+', '3')
    return pd.to_numeric(s, errors='coerce')


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Standardise one or many raw applications. Never drops rows; records every fix in dq_* columns."""
    df = df.copy()
    for c in CATEGORY_MAPS:
        if c not in df:
            df[c] = np.nan
        s = df[c].astype('string').str.strip().str.lower().replace('', pd.NA)
        mapped = s.map(CATEGORY_MAPS[c])
        df[f'dq_unmapped_{c}'] = (s.notna() & mapped.isna()).astype(int)
        df[c] = mapped.astype(object).where(mapped.notna(), np.nan)

    for c in NUMERIC_COLS:
        if c not in df:
            df[c] = np.nan
        df[c] = _to_number(df[c])
    df['Dependents'] = df['Dependents'].clip(0, 3)

    # Domain validity: recover when the error is unambiguous, otherwise null (and impute later)
    bad_age = df['Age'].notna() & ~df['Age'].between(18, 75)
    df.loc[bad_age, 'Age'] = np.nan
    neg_income = df['Monthly_Income'] < 0
    df.loc[neg_income, 'Monthly_Income'] = df.loc[neg_income, 'Monthly_Income'].abs()
    zero_income = df['Monthly_Income'] == 0
    df.loc[zero_income, 'Monthly_Income'] = np.nan
    bad_cibil = df['CIBIL_Score'].notna() & (df['CIBIL_Score'] != -1) & ~df['CIBIL_Score'].between(300, 900)
    df.loc[bad_cibil, 'CIBIL_Score'] = np.nan
    exp = df['Work_Experience']
    bad_exp = exp.notna() & ((exp < 0) | (exp > 50) | (exp > df['Age'] - 18))
    df.loc[bad_exp, 'Work_Experience'] = np.nan
    tenure_in_years = (df['Loan_Type'] == 'Home') & (df['Loan_Tenure'] <= 30)
    df.loc[tenure_in_years, 'Loan_Tenure'] *= 12
    for c in ['Coapplicant_Income', 'Existing_EMI', 'Collateral_Value']:
        df.loc[df[c] < 0, c] = np.nan
    for c in ['Loan_Amount', 'Loan_Tenure']:
        df.loc[df[c] <= 0, c] = np.nan

    df['dq_fixes'] = (bad_age.astype(int) + neg_income + zero_income + bad_cibil + bad_exp + tenure_in_years
                      + df.filter(like='dq_unmapped_').drop(columns='dq_unmapped_Loan_Status').sum(axis=1))
    return df


def prepare_training_data(raw: pd.DataFrame) -> pd.DataFrame:
    """clean() plus the steps that only make sense on a historical table: dedupe and drop unlabelled rows."""
    raw = raw.copy()
    for c in raw.select_dtypes(exclude='number').columns:
        raw[c] = raw[c].astype('string').str.strip()
    raw = raw.drop_duplicates().reset_index(drop=True)
    df = clean(raw)
    df = df[df['Loan_Status'].notna()].reset_index(drop=True)
    assert df.filter(like='dq_unmapped_').to_numpy().sum() == 0, 'unmapped category spelling in training data'
    df['target'] = (df['Loan_Status'] == 'Approved').astype(int)
    return df


# --------------------------------------------------------------------------------------
# 2. Imputation (learned on the training fold only)
# --------------------------------------------------------------------------------------
def _mode(s):
    m = s.mode()
    return m.iloc[0] if len(m) else np.nan


class Imputer(BaseEstimator, TransformerMixin):
    """Group-wise imputation from report §3.7. Adds imp_* flags so imputed records can be routed to review."""

    def fit(self, df, y=None):
        self.global_ = {c: df[c].median() for c in ['Age', 'Monthly_Income', 'Work_Experience']}
        self.emp_mode_ = _mode(df['Employment_Type'])
        self.loan_type_mode_ = _mode(df['Loan_Type'])
        self.area_mode_ = _mode(df['Property_Area'])
        self.dependents_global_ = _mode(df['Dependents'])
        self.dependents_by_marital_ = df.groupby('Marital_Status')['Dependents'].agg(_mode).to_dict()
        self.age_by_emp_ = df.groupby('Employment_Type')['Age'].median().to_dict()
        self.income_by_emp_area_ = df.groupby(['Employment_Type', 'Property_Area'])['Monthly_Income'].median().to_dict()
        self.exp_by_emp_ = df.groupby('Employment_Type')['Work_Experience'].median().to_dict()
        self.emi_median_ = df['Existing_EMI'].median()
        self.cibil_median_ = df.loc[df['CIBIL_Score'] != -1, 'CIBIL_Score'].median()
        self.amount_by_type_ = df.groupby('Loan_Type')['Loan_Amount'].median().to_dict()
        self.tenure_by_type_ = df.groupby('Loan_Type')['Loan_Tenure'].agg(_mode).to_dict()
        secured = df[df['Loan_Type'].isin(SECURED_TYPES) & (df['Collateral_Value'] > 0)]
        self.ltv_by_type_ = (secured['Loan_Amount'] / secured['Collateral_Value']).groupby(secured['Loan_Type']).median().to_dict()
        return self

    def transform(self, df):
        df = df.copy()
        for c in ['Employment_Type', 'Loan_Type', 'Property_Area', 'Dependents', 'Age', 'Monthly_Income',
                  'Work_Experience', 'Existing_EMI', 'CIBIL_Score', 'Loan_Amount', 'Loan_Tenure']:
            df[f'imp_{c}'] = df[c].isna().astype(int)

        df['Gender'] = df['Gender'].fillna('Unknown')               # protected: never guessed
        df['Marital_Status'] = df['Marital_Status'].fillna('Unknown')
        df['Employment_Type'] = df['Employment_Type'].fillna(self.emp_mode_)
        df['Loan_Type'] = df['Loan_Type'].fillna(self.loan_type_mode_)
        df['Property_Area'] = df['Property_Area'].fillna(self.area_mode_)
        df['Dependents'] = df['Dependents'].fillna(
            df['Marital_Status'].map(self.dependents_by_marital_)).fillna(self.dependents_global_)
        df['Age'] = df['Age'].fillna(df['Employment_Type'].map(self.age_by_emp_)).fillna(self.global_['Age'])
        key = list(zip(df['Employment_Type'], df['Property_Area']))
        df['Monthly_Income'] = df['Monthly_Income'].fillna(
            pd.Series([self.income_by_emp_area_.get(k) for k in key], index=df.index, dtype=float)
        ).fillna(self.global_['Monthly_Income'])
        df['Work_Experience'] = df['Work_Experience'].fillna(
            df['Employment_Type'].map(self.exp_by_emp_)).fillna(self.global_['Work_Experience'])
        df['Work_Experience'] = df['Work_Experience'].clip(lower=0, upper=(df['Age'] - 18).clip(lower=0))
        df['Existing_EMI'] = df['Existing_EMI'].fillna(self.emi_median_)
        df['CIBIL_Score'] = df['CIBIL_Score'].fillna(self.cibil_median_)
        df['Loan_Amount'] = df['Loan_Amount'].fillna(df['Loan_Type'].map(self.amount_by_type_))
        df['Loan_Tenure'] = df['Loan_Tenure'].fillna(df['Loan_Type'].map(self.tenure_by_type_))
        df['Coapplicant_Income'] = df['Coapplicant_Income'].fillna(0)   # structural: no earning co-applicant

        secured = df['Loan_Type'].isin(SECURED_TYPES)
        missing_coll = df['Collateral_Value'].isna() | (secured & (df['Collateral_Value'] == 0))
        df['collateral_backfilled'] = (secured & missing_coll).astype(int)
        backfill = df['Loan_Amount'] / df['Loan_Type'].map(self.ltv_by_type_)
        df['Collateral_Value'] = np.where(secured & missing_coll, backfill, df['Collateral_Value'].fillna(0))

        for c in ['Age', 'Dependents', 'Work_Experience', 'CIBIL_Score', 'Loan_Tenure']:
            df[c] = df[c].round()
        return df


# --------------------------------------------------------------------------------------
# 3. Feature engineering (stateless; all ratios from real, unscaled, uncapped values)
# --------------------------------------------------------------------------------------
def _slab(values, slabs):
    out = np.full(len(values), slabs[-1][1], dtype=float)
    for upper, limit in reversed(slabs):
        out = np.where(values <= upper, limit, out)
    return out


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    ti = df['Monthly_Income'] + df['Coapplicant_Income']
    r = df['Loan_Type'].map(INDICATIVE_RATES) / 12
    n = df['Loan_Tenure']
    growth = (1 + r) ** n
    df['total_income'] = ti
    df['proposed_emi'] = df['Loan_Amount'] * r * growth / (growth - 1)
    df['foir'] = (df['Existing_EMI'] + df['proposed_emi']) / ti
    # R4 slabs: < 50k -> 50%, 50k-1L -> 55%, above -> 65%
    (lo, lim1), (hi, lim2), (_, lim3) = POLICY['foir_slabs']
    df['foir_limit'] = np.select([ti < lo, ti <= hi], [lim1, lim2], lim3)
    df['foir_headroom'] = df['foir_limit'] - df['foir']
    df['disposable_income'] = ti - df['Existing_EMI'] - df['proposed_emi']
    df['disposable_per_member'] = df['disposable_income'] / (1 + df['Dependents'] + (df['Marital_Status'] == 'Married'))
    df['loan_to_income'] = df['Loan_Amount'] / (12 * ti)
    df['existing_emi_ratio'] = df['Existing_EMI'] / ti
    df['has_existing_loan'] = (df['Existing_EMI'] > 0).astype(int)
    df['has_coapplicant'] = (df['Coapplicant_Income'] > 0).astype(int)
    df['coapplicant_share'] = df['Coapplicant_Income'] / ti

    df['is_secured'] = (df['Collateral_Value'] > 0).astype(int)
    df['collateral_coverage'] = df['Collateral_Value'] / df['Loan_Amount']
    df['ltv'] = np.where(df['Collateral_Value'] > 0, df['Loan_Amount'] / df['Collateral_Value'].replace(0, np.nan), 0.0)
    df['ltv_cap'] = np.where(df['Loan_Type'] == 'Home', _slab(df['Loan_Amount'].to_numpy(), POLICY['ltv_slabs']), np.nan)
    df['ltv_headroom'] = np.where(df['Loan_Type'] == 'Home', df['ltv_cap'] - df['ltv'], 1.0)

    df['is_new_to_credit'] = (df['CIBIL_Score'] == -1).astype(int)
    df['cibil_filled'] = df['CIBIL_Score'].where(df['CIBIL_Score'] != -1)  # NaN for NTC: trees treat it as its own branch
    df['cibil_headroom'] = df['cibil_filled'] - POLICY['min_cibil']

    df['age_at_maturity'] = df['Age'] + n / 12
    df['max_maturity_age'] = df['Employment_Type'].map(POLICY['max_maturity_age'])
    df['maturity_headroom'] = df['max_maturity_age'] - df['age_at_maturity']
    df['min_experience'] = df['Employment_Type'].map(POLICY['min_experience'])
    df['experience_headroom'] = df['Work_Experience'] - df['min_experience']

    df['emp_sep'] = (df['Employment_Type'] == 'SEP').astype(int)
    df['emp_senp'] = (df['Employment_Type'] == 'SENP').astype(int)
    for t in ['Home', 'Vehicle', 'Business']:
        df[f'loan_type_{t.lower()}'] = (df['Loan_Type'] == t).astype(int)
    df['area_urban'] = (df['Property_Area'] == 'Urban').astype(int)
    df['area_rural'] = (df['Property_Area'] == 'Rural').astype(int)

    flags = evaluate_rules(df)
    df[[f'rule_{r}' for r in RULES]] = flags.to_numpy()
    df['n_rules_violated'] = flags.sum(axis=1)
    return df


# --------------------------------------------------------------------------------------
# 4. Policy rule engine (independent of the model)
# --------------------------------------------------------------------------------------
def evaluate_rules(f: pd.DataFrame) -> pd.DataFrame:
    """True = rule violated. Expects the columns produced by build_features()."""
    out = pd.DataFrame(index=f.index)
    out['R1'] = f['Age'] < POLICY['min_age']
    out['R2'] = f['age_at_maturity'] > f['max_maturity_age']
    out['R3'] = (f['CIBIL_Score'] != -1) & (f['CIBIL_Score'] < POLICY['min_cibil'])
    out['R4'] = f['foir'] > f['foir_limit']
    out['R5'] = (f['Loan_Type'] == 'Home') & (f['ltv'] > f['ltv_cap'])
    out['R6'] = f['total_income'] < POLICY['min_total_income']
    out['R7'] = f['Work_Experience'] < f['min_experience']
    return out.astype(int)


def rule_reasons(row: pd.Series) -> list[str]:
    ctx = {**row.to_dict(), **{k: v for k, v in POLICY.items() if not isinstance(v, (dict, list))}}
    ctx['max_maturity_age'] = row['max_maturity_age']
    ctx['min_experience'] = row['min_experience']
    return [f'{r}: ' + RULE_TEXT[r].format(**ctx) for r in RULES if row[f'rule_{r}']]


# --------------------------------------------------------------------------------------
# 5. Model feature set (chosen by cross-validated backward elimination on log-loss; see the notebook)
# --------------------------------------------------------------------------------------
MODEL_FEATURES = [
    'cibil_filled', 'is_new_to_credit', 'foir', 'foir_headroom', 'total_income', 'loan_to_income',
    'collateral_coverage', 'ltv_headroom', 'Work_Experience', 'experience_headroom',
    'age_at_maturity', 'maturity_headroom', 'Age', 'Loan_Tenure', 'Dependents',
    'emp_sep', 'emp_senp', 'loan_type_home', 'loan_type_vehicle', 'loan_type_business',
    'n_rules_violated',
]
# Not used by the model: Gender / Marital_Status (protected, RBI Fair Practices Code) and Property_Area
# (no measurable CV gain, and a potential geographic proxy for protected groups).

# Plain-language description of each model feature, used in decision reasons
FEATURE_TEXT = {
    'cibil_filled': ('moderate CIBIL score {CIBIL_Score:.0f}', 'strong CIBIL score {CIBIL_Score:.0f}'),
    'cibil_headroom': ('CIBIL score {CIBIL_Score:.0f}', 'strong CIBIL score {CIBIL_Score:.0f}'),
    'is_new_to_credit': ('no credit history (new to credit)', 'established credit history'),
    'foir': ('high FOIR of {foir:.0%}', 'comfortable FOIR of {foir:.0%}'),
    'foir_headroom': ('FOIR {foir:.0%} close to the {foir_limit:.0%} limit', 'FOIR {foir:.0%} well under the {foir_limit:.0%} limit'),
    'total_income': ('low total income Rs {total_income:,.0f}/month', 'good total income Rs {total_income:,.0f}/month'),
    'loan_to_income': ('loan is {loan_to_income:.1f} years of income', 'loan is only {loan_to_income:.1f} years of income'),
    'collateral_coverage': ('low collateral cover ({collateral_coverage:.2f}x the loan)', 'collateral cover {collateral_coverage:.2f}x the loan'),
    'ltv_headroom': ('LTV {ltv:.0%} close to the RBI cap', 'LTV {ltv:.0%} well under the RBI cap'),
    'Work_Experience': ('short work experience / vintage ({Work_Experience:.0f} yrs)', '{Work_Experience:.0f} yrs work experience / vintage'),
    'experience_headroom': ('experience {Work_Experience:.0f} yrs near the minimum', 'experience {Work_Experience:.0f} yrs well above the minimum'),
    'age_at_maturity': ('age at maturity {age_at_maturity:.0f}', 'age at maturity {age_at_maturity:.0f}'),
    'maturity_headroom': ('loan ends close to the retirement-age limit', 'loan ends well before the retirement-age limit'),
    'Age': ('applicant age {Age:.0f}', 'applicant age {Age:.0f}'),
    'Loan_Tenure': ('tenure of {Loan_Tenure:.0f} months', 'tenure of {Loan_Tenure:.0f} months'),
    'Dependents': ('{Dependents:.0f} dependents', '{Dependents:.0f} dependents'),
    'emp_sep': ('employment segment ({Employment_Type})', 'employment segment ({Employment_Type})'),
    'emp_senp': ('employment segment ({Employment_Type})', 'employment segment ({Employment_Type})'),
    'loan_type_home': ('product risk ({Loan_Type} loan)', 'product ({Loan_Type} loan)'),
    'loan_type_vehicle': ('product risk ({Loan_Type} loan)', 'product ({Loan_Type} loan)'),
    'loan_type_business': ('product risk ({Loan_Type} loan)', 'product ({Loan_Type} loan)'),
    'area_urban': ('location ({Property_Area})', 'location ({Property_Area})'),
    'area_rural': ('location ({Property_Area})', 'location ({Property_Area})'),
    'n_rules_violated': ('policy rule violations', 'all policy rules met'),
    'disposable_income': ('low disposable income Rs {disposable_income:,.0f}', 'disposable income Rs {disposable_income:,.0f}'),
    'existing_emi_ratio': ('existing EMIs take {existing_emi_ratio:.0%} of income', 'low existing EMIs'),
}


def describe_feature(feature: str, row: pd.Series, adverse: bool) -> str | None:
    """Plain-language reason for one feature, or None when it doesn't apply to this product."""
    if feature == 'ltv_headroom' and row['Loan_Type'] != 'Home':
        return None                                   # RBI LTV cap applies to housing loans only
    if feature == 'collateral_coverage' and row['Collateral_Value'] == 0:
        return 'unsecured loan (no collateral)' if adverse else None
    if feature == 'is_new_to_credit' and not row['is_new_to_credit'] and adverse:
        return None
    neg, pos = FEATURE_TEXT.get(feature, (feature, feature))
    try:
        return (neg if adverse else pos).format(**row.to_dict())
    except (KeyError, ValueError):
        return feature


# --------------------------------------------------------------------------------------
# 6. Hybrid decision layer
# --------------------------------------------------------------------------------------
DECISION = {
    'approve_at': 0.65,       # P(approve) >= this -> APPROVE
    'reject_below': 0.35,     # P(approve) < this  -> REJECT ; in between -> MANUAL_REVIEW (borderline)
    'large_exposure': 20_000_000,   # Rs 2 Cr+ loans always get a credit-committee look
}


def review_triggers(row: pd.Series, thresholds: dict = DECISION) -> list[str]:
    """Cases where the data or the exposure is too uncertain to auto-decide (report §6.4)."""
    t = []
    if row['is_new_to_credit']:
        t.append('New-to-credit applicant: no bureau history to verify repayment behaviour')
    if row['imp_CIBIL_Score']:
        t.append('CIBIL score missing or invalid in the application: pull a fresh bureau report')
    if row['imp_Existing_EMI']:
        t.append('Existing EMI not on record: verify obligations from the bureau report')
    if row['imp_Monthly_Income']:
        t.append('Income missing or invalid: verify salary slips / ITR')
    if row['collateral_backfilled']:
        t.append('Collateral value not on record for a secured loan: valuation required')
    for c, label in [('imp_Loan_Amount', 'loan amount'), ('imp_Loan_Tenure', 'loan tenure'),
                     ('imp_Employment_Type', 'employment type'), ('imp_Loan_Type', 'loan type'),
                     ('imp_Age', 'age')]:
        if row.get(c, 0):
            t.append(f'{label.capitalize()} missing or invalid in the application')
    if row['Loan_Amount'] >= thresholds['large_exposure']:
        t.append(f'Large exposure (Rs {row["Loan_Amount"] / 1e7:.2f} Cr): credit-committee sign-off')
    return t


def decide(features: pd.DataFrame, proba: np.ndarray, contributions: pd.DataFrame | None = None,
           thresholds: dict = DECISION, top_k: int = 3) -> pd.DataFrame:
    """Combine policy rules, data-quality triggers and the model probability into a final decision.

    Order of precedence:
      1. Any hard rule violated            -> REJECT (the rule layer overrides the model)
      2. Data/exposure review trigger      -> MANUAL_REVIEW (with the model's recommendation)
      3. P(approve) >= approve_at          -> APPROVE
      4. P(approve) <  reject_below        -> REJECT
      5. otherwise                         -> MANUAL_REVIEW (borderline score)
    """
    rows = []
    for i, (idx, row) in enumerate(features.iterrows()):
        p = float(proba[i])
        model_rec = 'APPROVE' if p >= 0.5 else 'REJECT'
        violated = rule_reasons(row)
        triggers = review_triggers(row, thresholds)
        contrib = contributions.loc[idx] if contributions is not None else None
        drivers_neg = drivers_pos = []
        if contrib is not None:
            neg = [describe_feature(f, row, True) for f in contrib.sort_values().index if contrib[f] < 0]
            pos = [describe_feature(f, row, False) for f in contrib.sort_values(ascending=False).index if contrib[f] > 0]
            drivers_neg = [d for d in dict.fromkeys(neg) if d][:top_k]
            drivers_pos = [d for d in dict.fromkeys(pos) if d][:top_k]

        if violated:
            decision, stage = 'REJECT', 'policy'
            reasons = violated
            if p >= thresholds['approve_at']:
                reasons = reasons + ['Note: model score is high; a policy deviation would need sanctioning-authority approval']
        elif triggers:
            decision, stage = 'MANUAL_REVIEW', 'data/exposure'
            reasons = triggers + [f'Model recommendation: {model_rec} (P(approve) = {p:.2f})']
        elif p >= thresholds['approve_at']:
            decision, stage, reasons = 'APPROVE', 'model', drivers_pos
        elif p < thresholds['reject_below']:
            decision, stage, reasons = 'REJECT', 'model', drivers_neg
        else:
            decision, stage = 'MANUAL_REVIEW', 'borderline'
            reasons = [f'Borderline score P(approve) = {p:.2f}'] + \
                      [f'Concern: {d}' for d in drivers_neg] + [f'Strength: {d}' for d in drivers_pos]
        rows.append({'decision': decision, 'decided_by': stage, 'p_approve': round(p, 4),
                     'model_recommendation': model_rec, 'rules_violated': ','.join(r for r in RULES if row[f'rule_{r}']),
                     'reasons': ' | '.join(reasons)})
    return pd.DataFrame(rows, index=features.index)


# --------------------------------------------------------------------------------------
# 7. End-to-end object: fit on history, decide on new applications
# --------------------------------------------------------------------------------------
class LoanDecisionEngine:
    def __init__(self, model, features=None, decision=None):
        self.model = model
        self.features = list(features or MODEL_FEATURES)
        self.decision = {**DECISION, **(decision or {})}

    def fit(self, cleaned: pd.DataFrame, y):
        self.imputer_ = Imputer().fit(cleaned)
        X = build_features(self.imputer_.transform(cleaned))[self.features]
        self.model.fit(X, y)
        return self

    def featurize(self, raw_or_clean: pd.DataFrame) -> pd.DataFrame:
        df = raw_or_clean if 'dq_fixes' in raw_or_clean else clean(raw_or_clean)
        return build_features(self.imputer_.transform(df))

    def predict_proba(self, raw_or_clean: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(self.featurize(raw_or_clean)[self.features])[:, 1]

    def contributions(self, F: pd.DataFrame) -> pd.DataFrame:
        """Per-feature contribution (log-odds) to each prediction, via SHAP TreeExplainer."""
        import shap
        X = F[self.features]
        sv = shap.TreeExplainer(self.model).shap_values(X)
        if isinstance(sv, list):
            sv = sv[1]
        sv = np.asarray(sv)
        if sv.ndim == 3:
            sv = sv[:, :, 1]
        return pd.DataFrame(sv, index=F.index, columns=self.features)

    def decide(self, raw_or_clean: pd.DataFrame, explain: bool = True) -> pd.DataFrame:
        F = self.featurize(raw_or_clean)
        proba = self.model.predict_proba(F[self.features])[:, 1]
        contrib = self.contributions(F) if explain else None
        out = decide(F, proba, contrib, self.decision)
        if 'Loan_ID' in F:
            out.insert(0, 'Loan_ID', F['Loan_ID'].to_numpy())
        return out
