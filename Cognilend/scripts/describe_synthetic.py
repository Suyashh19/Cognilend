"""Profile the generated synthetic dataset for docs/data_decision.md.

    python scripts/describe_synthetic.py   -> prints the profile, writes artifacts/reports/synthetic_profile.json

The rule checks here are a diagnostic re-implementation of R1-R7 on the CLEAN frame, only to measure how
far the label is from the policy rules. The real rule engine is built in Step 3.
"""
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.tree import DecisionTreeClassifier

from cognilend import config
from cognilend.data import synthetic


def diagnostic_rules(df, pol):
    h = config.load('synthetic')['diagnostic_rules']
    ti = df['Monthly_Income'] + df['Coapplicant_Income'].fillna(0)
    r = df['Loan_Type'].map(pol['indicative_rates']) / 12
    g = (1 + r) ** df['Loan_Tenure']
    foir = (df['Existing_EMI'] + df['Loan_Amount'] * r * g / (g - 1)) / ti
    s = h['R4']['foir_slabs']
    foir_lim = np.select([ti < s[0]['income_below'], ti <= s[1]['income_upto']],
                         [s[0]['max_foir'], s[1]['max_foir']], s[2]['max_foir'])
    ltv = df['Loan_Amount'] / df['Collateral_Value']
    ls = h['R5']['ltv_slabs']
    ltv_cap = np.select([df['Loan_Amount'] <= ls[0]['amount_upto'], df['Loan_Amount'] <= ls[1]['amount_upto']],
                        [ls[0]['max_ltv'], ls[1]['max_ltv']], ls[2]['max_ltv'])
    return pd.DataFrame({
        'R1': df['Age'] < h['R1']['min_age'],
        'R2': df['Age'] + df['Loan_Tenure'] / 12 > df['Employment_Type'].map(h['R2']['max_maturity_age']),
        'R3': (df['CIBIL_Score'] != -1) & (df['CIBIL_Score'] < h['R3']['min_cibil']),
        'R4': foir > foir_lim,
        'R5': (df['Loan_Type'] == 'Home') & (ltv > ltv_cap),
        'R6': ti < h['R6']['min_total_income'],
        'R7': df['Work_Experience'] < df['Employment_Type'].map(h['R7']['min_experience']),
    })


def main():
    raw, clean = synthetic.generate(return_clean=True)
    pol = config.load('policies_v1')
    y = (clean['Loan_Status'] == 'Approved').astype(int)
    viol = diagnostic_rules(clean, pol)
    any_v = viol.any(axis=1)

    # Learnability: simple numeric features from the clean frame (no protected attributes)
    X = pd.DataFrame({
        'cibil': clean['CIBIL_Score'], 'ntc': (clean['CIBIL_Score'] == -1).astype(int),
        'income': clean['Monthly_Income'] + clean['Coapplicant_Income'].fillna(0),
        'emi': clean['Existing_EMI'], 'amount': clean['Loan_Amount'], 'tenure': clean['Loan_Tenure'],
        'coverage': clean['Collateral_Value'].fillna(0) / clean['Loan_Amount'],
        'exp': clean['Work_Experience'], 'age': clean['Age'],
        'sep': (clean['Employment_Type'] == 'SEP').astype(int), 'senp': (clean['Employment_Type'] == 'SENP').astype(int),
    })
    X['foir_proxy'] = (X['emi'] + X['amount'] / X['tenure']) / X['income']
    cv = StratifiedKFold(5, shuffle=True, random_state=42)
    dt4 = cross_val_score(DecisionTreeClassifier(criterion='entropy', max_depth=4, random_state=42), X, y, cv=cv).mean()
    rf = cross_val_score(RandomForestClassifier(300, min_samples_leaf=5, random_state=42, n_jobs=-1), X, y, cv=cv).mean()
    rules_only = ((~any_v).astype(int) == y).mean()
    noise_free = ((clean['_score'] >= np.quantile(clean['_score'], 1 - 0.585)).astype(int) == y).mean()

    by_gender = y.groupby(clean['Gender']).agg(['size', 'mean'])
    ref = by_gender.loc['Male', 'mean']
    profile = {
        'raw_shape': list(raw.shape),
        'sha256': synthetic.sha256(config.ROOT / config.load('settings')['paths']['synthetic_raw']),
        'approval_rate_unique_rows': round(float(y.mean()), 4),
        'rule_violation_rate': {k: round(float(v), 4) for k, v in viol.mean().items()},
        'any_rule_violated': round(float(any_v.mean()), 4),
        'approval_rate_if_violation': round(float(y[any_v].mean()), 4),
        'approval_rate_if_compliant': round(float(y[~any_v].mean()), 4),
        'accuracy_rules_only_predictor': round(float(rules_only), 4),
        'accuracy_noise_free_latent_score': round(float(noise_free), 4),
        'cv5_accuracy_entropy_tree_depth4': round(float(dt4), 4),
        'cv5_accuracy_random_forest': round(float(rf), 4),
        'ntc_rate': round(float((clean['CIBIL_Score'] == -1).mean()), 4),
        'label_rate_by_gender': {g: {'n': int(r['size']), 'approval_rate': round(float(r['mean']), 4),
                                     'DI_vs_male': round(float(r['mean'] / ref), 4)}
                                 for g, r in by_gender.iterrows()},
        'median_monthly_income': float(clean['Monthly_Income'].median()),
        'loan_type_share': clean['Loan_Type'].value_counts(normalize=True).round(4).to_dict(),
    }
    out = config.ROOT / 'artifacts' / 'reports' / 'synthetic_profile.json'
    out.write_text(json.dumps(profile, indent=2))
    print(json.dumps(profile, indent=2))


if __name__ == '__main__':
    main()
