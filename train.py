"""Train, evaluate and save the Cognilend hybrid loan-decision engine.

    python train.py            -> prints evaluation, writes artifacts/ (model, test-set decisions, fairness audit)
"""
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

import loan_engine as le

# Monotone constraints: a better value of these credit facts may never lower P(approve)
MONOTONE = {'cibil_filled': 1, 'foir': -1, 'foir_headroom': 1, 'total_income': 1, 'loan_to_income': -1,
            'collateral_coverage': 1, 'ltv_headroom': 1, 'Work_Experience': 1, 'experience_headroom': 1,
            'maturity_headroom': 1, 'n_rules_violated': -1}

# Tuned with Optuna (60 trials, TPE, 2x5-fold CV log-loss on the training split only).
# CV on the training split: accuracy 0.897, ROC-AUC 0.946, log-loss 0.275 (with the monotone constraints)
PARAMS = dict(n_estimators=300, learning_rate=0.0356, max_depth=3, min_child_weight=7.75, subsample=0.768,
              colsample_bytree=0.594, reg_lambda=12.44, gamma=0.48)


def make_model(features=None):
    features = features or le.MODEL_FEATURES
    mono = '(' + ','.join(str(MONOTONE.get(f, 0)) for f in features) + ')'
    return XGBClassifier(**PARAMS, monotone_constraints=mono, random_state=0, n_jobs=4)


def proportion_ci(k, n, z=1.96):
    """Wilson score interval."""
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def fairness_audit(frame: pd.DataFrame, group: str, pred_col='approved', label_col='target'):
    """Approval rate, disparate-impact ratio vs the largest group, and TPR (equal opportunity) per group."""
    rows = []
    for g, d in frame.groupby(group, observed=True):
        k, n = int(d[pred_col].sum()), len(d)
        lo, hi = proportion_ci(k, n)
        pos = d[d[label_col] == 1]
        rows.append({group: g, 'n': n, 'historical_rate': d[label_col].mean(), 'approval_rate': k / n,
                     'ci_low': lo, 'ci_high': hi,
                     'tpr': pos[pred_col].mean() if len(pos) else np.nan})
    out = pd.DataFrame(rows)
    ref = out.loc[out['n'].idxmax()]
    out['DIR'] = out['approval_rate'] / ref['approval_rate']
    out['TPR_gap'] = out['tpr'] - ref['tpr']
    return out.round(3)


def main(out_dir='artifacts', seed=42):
    out = Path(out_dir)
    out.mkdir(exist_ok=True)
    df = le.prepare_training_data(pd.read_csv('loan_applications_raw.csv'))
    train, test = train_test_split(df, test_size=0.2, random_state=seed, stratify=df['target'])

    engine = le.LoanDecisionEngine(make_model()).fit(train, train['target'])
    p = engine.predict_proba(test)
    y = test['target'].to_numpy()
    print(f'Model alone  : accuracy={accuracy_score(y, p >= .5):.4f}  ROC-AUC={roc_auc_score(y, p):.4f}  '
          f'F1={f1_score(y, p >= .5):.4f}')

    decisions = engine.decide(test)
    F = engine.featurize(test)
    auto = decisions['decision'] != 'MANUAL_REVIEW'
    auto_pred = (decisions.loc[auto, 'decision'] == 'APPROVE').astype(int)
    print(f'Hybrid engine: auto-decided {auto.mean():.1%} of applications, '
          f'accuracy on those = {accuracy_score(y[auto.to_numpy()], auto_pred):.4f}; '
          f'{(~auto).mean():.1%} sent to manual review')
    print(decisions.groupby(['decision', 'decided_by']).size().to_string())

    audit = pd.concat([test[['Loan_ID', 'Gender', 'Marital_Status', 'Age', 'Employment_Type', 'Loan_Type',
                             'Property_Area', 'Loan_Status']].reset_index(drop=True),
                       F[['CIBIL_Score', 'total_income', 'foir', 'ltv', 'age_at_maturity']].reset_index(drop=True),
                       decisions.drop(columns='Loan_ID').reset_index(drop=True)], axis=1)
    audit['timestamp'] = pd.Timestamp.now().isoformat(timespec='seconds')
    audit.to_csv(out / 'test_decisions.csv', index=False)

    frame = test[['Gender', 'Property_Area', 'target']].copy()
    frame['Gender'] = frame['Gender'].fillna('Unknown')
    frame['approved'] = (p >= .5).astype(int)
    for g in ['Gender', 'Property_Area']:
        fa = fairness_audit(frame, g)
        print('\nFairness audit by', g, '\n', fa.to_string(index=False))
        fa.to_csv(out / f'fairness_{g.lower()}.csv', index=False)

    # Production model: refit on all labelled history
    final = le.LoanDecisionEngine(make_model()).fit(df, df['target'])
    joblib.dump(final, out / 'loan_engine.joblib')
    print(f'\nSaved {out / "loan_engine.joblib"} and audit files to {out}/')
    return engine, decisions


if __name__ == '__main__':
    main()
