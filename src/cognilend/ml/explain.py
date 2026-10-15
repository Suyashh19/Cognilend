"""Feature-by-feature tree path for every prediction (FR-9), in original units, plus path contributions (G3).

    python -m cognilend.ml.explain   -> artifacts/reports/explanations.md, explain_shift.csv

Path contribution of a split = P(Approved | child) - P(Approved | parent), with node probabilities from REAL
training counts (Beta prior, see confidence.node_table). Root prior + sum of contributions = leaf P(Approved).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from cognilend.data import preprocess
from cognilend.ml import confidence, tree

LABELS = {'cibil_score': 'CIBIL', 'foir': 'FOIR', 'work_experience': 'work experience', 'total_income': 'total income',
          'existing_emi': 'existing EMI', 'loan_amount': 'loan amount', 'loan_tenure': 'tenure',
          'loan_to_income': 'loan-to-income', 'collateral_coverage': 'collateral cover', 'dependents': 'dependents'}
FORMATS = {'cibil_score': '{:.0f}', 'foir': '{:.3f}', 'work_experience': '{:.1f} yrs', 'total_income': 'Rs {:,.0f}/month',
           'existing_emi': 'Rs {:,.0f}/month', 'loan_amount': 'Rs {:,.0f}', 'loan_tenure': '{:.0f} months',
           'loan_to_income': '{:.2f} yrs of income', 'collateral_coverage': '{:.2f}x', 'dependents': '{:.0f}'}


# model feature -> raw input columns it is computed from (missing input = imputed feature value)
SOURCES = {'cibil_score': ['CIBIL_Score'], 'work_experience': ['Work_Experience'], 'existing_emi': ['Existing_EMI'],
           'total_income': ['Monthly_Income'], 'loan_amount': ['Loan_Amount'], 'loan_tenure': ['Loan_Tenure'],
           'foir': ['Existing_EMI', 'Monthly_Income', 'Loan_Amount', 'Loan_Tenure'],
           'loan_to_income': ['Loan_Amount', 'Monthly_Income'], 'collateral_coverage': ['Collateral_Value', 'Loan_Amount'],
           'dependents': ['Dependents']}


def imputed_features(clean_row: pd.Series) -> set[str]:
    return {f for f, cols in SOURCES.items() if any(c in clean_row.index and pd.isna(clean_row[c]) for c in cols)}


class Explainer:
    """Holds the fitted artefacts; explain() works on cleaned application rows (preprocess.clean output)."""

    def __init__(self, dt_bundle=None, pre_bundle=None, conf_bundle=None):
        self.dt = dt_bundle or tree.load_model()
        self.pre = pre_bundle or preprocess.load_preprocessor()
        self.conf = conf_bundle or confidence.load()
        self.model = self.dt['model']
        self.clf = self.model.named_steps['clf']
        self.features = list(self.dt['features'])
        self.to_raw = tree.raw_unit_converter(self.pre)
        self.nodes = self.conf['node_table']

    # ---------- matrices ----------
    def matrices(self, clean_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """(scaled model features, raw engineered features) for cleaned rows."""
        scaled = self.pre['preprocessor'].transform(clean_rows)[self.pre['feature_names']]
        raw = self.pre['preprocessor'].named_steps['features'].transform(clean_rows)
        return scaled, raw

    # ---------- text ----------
    def condition(self, feature: str, direction: str, threshold_raw, value_raw, raw_row, imputed=()) -> str:
        if feature in LABELS:
            fmt = FORMATS[feature]
            if feature == 'cibil_score' and raw_row.get('is_new_to_credit', 0) == 1:
                v = f'n/a (new to credit; median {fmt.format(value_raw)} used)'
            elif feature in imputed:
                v = f'{fmt.format(value_raw)} (imputed: input missing)'
            else:
                v = fmt.format(value_raw)
            return f'{LABELS[feature]} {v} {direction} {fmt.format(threshold_raw)}'
        if feature.startswith(('Employment_Type_', 'Loan_Type_')):
            col, level = feature.rsplit('_', 1)
            name = 'employment type' if col == 'Employment_Type' else 'loan type'
            return f'{name} is {"not " if direction == "<=" else ""}{level}'
        flag = feature.replace('_', ' ')
        return f'{flag}: {"no" if direction == "<=" else "yes"}'

    # ---------- explain ----------
    def explain(self, clean_rows: pd.DataFrame) -> list[dict]:
        scaled, raw = self.matrices(clean_rows)
        X = scaled[self.features]
        ind = self.clf.decision_path(X)
        conf = confidence.score(self.model, self.conf['leaf_table'], scaled)
        t = self.clf.tree_
        out = []
        for i in range(len(X)):
            nodes = ind.indices[ind.indptr[i]:ind.indptr[i + 1]]
            raw_row = raw.iloc[i]
            imputed = imputed_features(clean_rows.iloc[i])
            steps, contrib = [], {}
            for parent, child in zip(nodes[:-1], nodes[1:]):
                f = self.features[t.feature[parent]]
                thr = float(t.threshold[parent])
                direction = '<=' if child == t.children_left[parent] else '>'
                thr_raw = self.to_raw(f, thr)
                val_raw = float(raw_row[f]) if f in raw_row.index else float(X.iloc[i][f])
                delta = float(self.nodes.p_approved[child] - self.nodes.p_approved[parent])
                contrib[f] = contrib.get(f, 0.0) + delta
                steps.append({'node': int(parent), 'feature': f, 'direction': direction,
                              'threshold': thr_raw if thr_raw is not None else thr, 'threshold_scaled': thr,
                              'applicant_value': val_raw, 'imputed': f in imputed, 'contribution': delta,
                              'text': self.condition(f, direction, thr_raw, val_raw, raw_row, imputed)})
            c = conf.iloc[i]
            decision = 'Approved' if c['predicted'] == 1 else 'Rejected'
            sentence = (f'{decision} (confidence {c["confidence"]:.2f}, leaf of {int(c["n"])} past applicants) '
                        f'because ' + ' and '.join(s['text'] for s in steps) + '.')
            out.append({'leaf': int(c['leaf']), 'predicted': decision, 'confidence': float(c['confidence']),
                        'ci': [float(c['ci_low']), float(c['ci_high'])], 'support': int(c['n']),
                        'route': c['route'], 'p_approved': float(c['p_approved']),
                        'prior': float(self.nodes.p_approved[0]), 'path': steps, 'contributions': contrib,
                        'sentence': sentence})
        return out


def contribution_frame(explanations: list[dict], features: list[str]) -> pd.DataFrame:
    return pd.DataFrame([{f: e['contributions'].get(f, 0.0) for f in features} for e in explanations])


def run() -> dict:
    ex = Explainer()
    clean = pd.read_parquet(preprocess.processed_dir() / 'clean.parquet')
    res = {}
    for split in ('train', 'test'):
        rows = clean[clean['split'] == split].drop(columns=['split'])
        res[split] = ex.explain(rows)
    cf = {k: contribution_frame(v, ex.features) for k, v in res.items()}
    imp = pd.DataFrame({
        'tree_importance': ex.clf.feature_importances_,
        'mean_abs_contribution_train': cf['train'].abs().mean(),
        'mean_abs_contribution_test': cf['test'].abs().mean(),
        'mean_contribution_train': cf['train'].mean(),
        'mean_contribution_test': cf['test'].mean(),
    }, index=ex.features)
    imp['shift_abs'] = imp['mean_abs_contribution_test'] - imp['mean_abs_contribution_train']
    imp = imp[(imp['tree_importance'] > 0) | (imp['mean_abs_contribution_train'] > 0)].sort_values(
        'tree_importance', ascending=False)
    leaf_mix = pd.DataFrame({k: pd.Series([e['leaf'] for e in v]).value_counts(normalize=True)
                             for k, v in res.items()}).fillna(0).sort_index()
    out = tree.reports_dir()
    imp.to_csv(out / 'explain_shift.csv', float_format='%.6f')
    md = ['# Explanations and feature contributions', '',
          'Generated by `python -m cognilend.ml.explain`. Path contribution of a split = P(Approved | child) − '
          'P(Approved | parent), with node probabilities from real training counts.', '',
          '## Global importance and known (train) vs held-out (test) contributions', '',
          '| Feature | Tree importance | mean abs contribution train | test | shift |', '|---|---|---|---|---|']
    for f, r in imp.iterrows():
        md.append(f'| {f} | {r.tree_importance:.4f} | {r.mean_abs_contribution_train:.4f} | '
                  f'{r.mean_abs_contribution_test:.4f} | {r.shift_abs:+.4f} |')
    md += ['', '## Leaf mix, train vs test', '', '| Leaf | train share | test share | shift |', '|---|---|---|---|']
    for leaf, r in leaf_mix.iterrows():
        md.append(f'| {leaf} | {r["train"]:.4f} | {r["test"]:.4f} | {r["test"] - r["train"]:+.4f} |')
    md += ['', '## Example explanations (first three test applicants)', '']
    ids = clean.loc[clean['split'] == 'test', 'Loan_ID'].tolist()
    for i in range(3):
        e = res['test'][i]
        md += [f'**{ids[i]}**: {e["sentence"]}', '', '```json',
               json.dumps([{k: s[k] for k in ('feature', 'direction', 'threshold', 'applicant_value', 'contribution')}
                           for s in e['path']], indent=1), '```', '']
    (out / 'explanations.md').write_text('\n'.join(md), encoding='utf-8')
    return {'importance': imp, 'leaf_mix': leaf_mix, 'explanations': res}


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    r = run()
    print(r['importance'].round(4).to_string())
    print(r['leaf_mix'].round(4).to_string())
    for e in r['explanations']['test'][:3]:
        print(e['sentence'])
