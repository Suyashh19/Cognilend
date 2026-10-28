"""Benchmark the constrained tree against Random Forest, XGBoost and Gradient Boosting.

    python -m cognilend.ml.benchmark   -> artifacts/reports/benchmark.csv, benchmark.md, benchmark_cv.csv

Every number in benchmark.md is produced by this script. Same split, same 20 features, light tuning on the
validation split only, then one score on the shared test split, plus stratified k-fold CV on train.
"""
from __future__ import annotations

import itertools
import json

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_validate
from xgboost import XGBClassifier

from cognilend import config
from cognilend.ml import tree


def _settings():
    return config.load('settings')


def candidates(name: str) -> list:
    s = _settings()
    seed, grid = s['seed'], s['benchmark'][name]
    keys = list(grid)
    out = []
    for values in itertools.product(*grid.values()):
        p = dict(zip(keys, values))
        if name == 'random_forest':
            out.append(RandomForestClassifier(**p, random_state=seed, n_jobs=-1))
        elif name == 'xgboost':
            out.append(XGBClassifier(**p, random_state=seed, n_jobs=4, eval_metric='logloss'))
        else:
            out.append(GradientBoostingClassifier(**p, random_state=seed))
    return out


def tune(name: str, data: dict):
    """Pick the candidate with the best validation accuracy (ties: earlier = simpler grid entry)."""
    best, best_acc = None, -1.0
    for m in candidates(name):
        m.fit(data['train']['X'], data['train']['y'])
        acc = accuracy_score(data['val']['y'], m.predict(data['val']['X']))
        if acc > best_acc:
            best, best_acc = m, acc
    return best, best_acc


def complexity(name: str, model) -> str:
    if name == 'decision_tree':
        clf = model.named_steps['clf']
        return f'depth {clf.get_depth()}, {clf.tree_.node_count} nodes'
    if name == 'xgboost':
        return f'{model.n_estimators} trees, depth {model.max_depth}'
    if name == 'gradient_boosting':
        return f'{model.n_estimators} trees, depth {model.max_depth}'
    depths = [e.get_depth() for e in model.estimators_]
    return f'{len(model.estimators_)} trees, depth up to {max(depths)}'


EXPLAINABILITY = {'decision_tree': 'direct path (rules readable in original units)',
                  'random_forest': 'post-hoc only', 'xgboost': 'post-hoc only', 'gradient_boosting': 'post-hoc only'}


def run() -> dict:
    s = _settings()
    data = tree.load_processed()
    dt = tree.load_model()
    models = {'decision_tree': dt['model']}
    val_acc = {'decision_tree': accuracy_score(data['val']['y'], dt['model'].predict(data['val']['X']))}
    for name in ('random_forest', 'xgboost', 'gradient_boosting'):
        models[name], val_acc[name] = tune(name, data)

    rows, test_ids = [], {}
    Xte, yte = data['test']['X'], data['test']['y']
    for name, m in models.items():
        test_ids[name] = tuple(data['test']['ids'])
        p = m.predict_proba(Xte)[:, 1]
        pred = (p >= 0.5).astype(int)
        rows.append({'model': name, 'test_accuracy': accuracy_score(yte, pred), 'test_f1': f1_score(yte, pred),
                     'test_roc_auc': roc_auc_score(yte, p), 'val_accuracy': val_acc[name],
                     'complexity': complexity(name, m), 'explainability': EXPLAINABILITY[name],
                     'n_test': len(yte)})
    ref = test_ids['decision_tree']
    assert all(ids == ref for ids in test_ids.values()), 'models were not evaluated on identical test indices'

    cv = StratifiedKFold(s['benchmark']['cv_folds'], shuffle=True, random_state=s['seed'])
    cv_rows = []
    for name, m in models.items():
        r = cross_validate(clone(m), data['train']['X'], data['train']['y'], cv=cv,
                           scoring=['accuracy', 'roc_auc', 'f1'])
        cv_rows.append({'model': name, **{f'cv_{k}_{stat}': float(getattr(np, stat)(r[f'test_{k}']))
                                         for k in ('accuracy', 'roc_auc', 'f1') for stat in ('mean', 'std')}})
    table = pd.DataFrame(rows).merge(pd.DataFrame(cv_rows), on='model')

    out = tree.reports_dir()
    table.to_csv(out / 'benchmark.csv', index=False, float_format='%.4f')
    params = {n: {k: v for k, v in m.get_params().items() if k in s['benchmark'].get(n, {})}
              for n, m in models.items() if n != 'decision_tree'}
    params['decision_tree'] = dt['params']
    md = render(table, params, s)
    (out / 'benchmark.md').write_text(md, encoding='utf-8')
    # advisory comparison models for the app (the decision tree stays the only decision-maker)
    joblib.dump({'features': list(data['train']['X'].columns),
                 'models': {n: m for n, m in models.items() if n != 'decision_tree'}},
                tree.model_path().with_name('benchmark_models.joblib'))
    return {'table': table, 'params': params, 'markdown': md, 'test_ids': ref}


def render(t: pd.DataFrame, params: dict, s: dict) -> str:
    t = t.set_index('model')
    ens = t.drop(index='decision_tree')
    best = ens['test_accuracy'].idxmax()
    cost = t.loc[best, 'test_accuracy'] - t.loc['decision_tree', 'test_accuracy']
    cost_cv = ens['cv_accuracy_mean'].max() - t.loc['decision_tree', 'cv_accuracy_mean']
    cost_val = ens['val_accuracy'].max() - t.loc['decision_tree', 'val_accuracy']
    dt = t.loc['decision_tree']
    lines = [
        '# Benchmark: constrained tree vs ensembles',
        '',
        'Generated by `python -m cognilend.ml.benchmark`. Same split (70/15/15, seed 42) and the same 20 features '
        'for all models; hyper-parameters chosen on validation only; one score on the shared test split '
        f'(n = {int(dt["n_test"])}, identical Loan_IDs asserted). CV = stratified {s["benchmark"]["cv_folds"]}-fold '
        'on the training split (the tree\'s SMOTE runs inside each fold).',
        '',
        '| Model | Test acc | Test F1 | Test ROC-AUC | Val acc | CV acc (mean ± sd) | CV ROC-AUC | CV F1 | '
        'Size | Explainability |',
        '|---|---|---|---|---|---|---|---|---|---|',
    ]
    for name, r in t.iterrows():
        lines.append(f'| {name} | {r.test_accuracy:.4f} | {r.test_f1:.4f} | {r.test_roc_auc:.4f} | '
                     f'{r.val_accuracy:.4f} | {r.cv_accuracy_mean:.4f} ± {r.cv_accuracy_std:.4f} | '
                     f'{r.cv_roc_auc_mean:.4f} ± {r.cv_roc_auc_std:.4f} | {r.cv_f1_mean:.4f} ± {r.cv_f1_std:.4f} | '
                     f'{r.complexity} | {r.explainability} |')
    lines += [
        '',
        '## Interpretability cost',
        '',
        f'- Best ensemble on test: **{best}** ({t.loc[best, "test_accuracy"]:.4f}).',
        f'- Interpretability cost = best ensemble test accuracy − tree test accuracy = **{cost:.4f}** '
        f'({cost * 100:.1f} percentage points).',
        f'- Same comparison on validation: {cost_val:.4f}; on CV means: {cost_cv:.4f}.',
        f'- KPI (val accuracy ≥ {s["kpi"]["min_val_accuracy"]:.2f}): tree {dt.val_accuracy:.4f} '
        f'({"met" if dt.val_accuracy >= s["kpi"]["min_val_accuracy"] else "NOT met"}); best ensemble '
        f'{ens["val_accuracy"].max():.4f}.',
        '',
        '## Justification',
        '',
        f'The constrained tree gives up about {cost * 100:.1f} points of test accuracy against {best}. In return '
        f'every decision is a single path of at most {s["tree"]["max_depth"]} comparisons on named banking '
        'quantities (CIBIL, FOIR, experience), which a loan officer can read, the applicant can be told, and the '
        'audit log can store verbatim (FR-3, FR-9). The ensembles average hundreds of trees, so their reasons '
        'exist only as post-hoc approximations (SHAP, permutation importance) that are not the computation that '
        'made the decision. CogniLend does not rely on the tree alone: hard policy rules run first, and the '
        'Bayesian confidence layer (Step 5) sends the tree\'s least certain leaves to human review; routing.md '
        'reports how accurate the remaining auto-decided cases are. The trade is therefore a measured accuracy '
        'cost in exchange for decisions that are fully traceable, with uncertain cases handled by people rather '
        'than by an opaque model. If the panel judges the cost too high, an ensemble can be added as a second '
        'opinion shown to reviewers, never as the decision-maker.',
        '',
        '## Chosen hyper-parameters (validation)',
        '',
        '```json',
        json.dumps(params, indent=2, default=str),
        '```',
        '',
        '## Loan.csv benchmark',
        '',
        'Not run: `Loan.csv` has not been supplied (see docs/data_decision.md).',
    ]
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    r = run()
    print(r['table'].to_string(index=False, float_format=lambda x: f'{x:.4f}'))
    print(r['markdown'].split('## Interpretability cost')[1].split('## Justification')[0])
