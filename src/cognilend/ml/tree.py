"""Constrained entropy decision tree (depth <= 4, nodes <= 15).

    python -m cognilend.ml.tree
        -> artifacts/models/dt_v1.joblib
        -> artifacts/reports/{dt_metrics.json, tree_rules.txt, tree.png, tree.dot}

Hyper-parameters (min_samples_leaf, class_weight, SMOTE on/off, top-k features by information gain) are chosen
on the VALIDATION split only. Depth and node caps are fixed and never loosened. The test split is scored once,
after the choice is made.
"""
from __future__ import annotations

import itertools
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from imblearn.pipeline import Pipeline
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, roc_auc_score
from sklearn.tree import DecisionTreeClassifier, _tree, export_graphviz

from cognilend import config
from cognilend.data import preprocess
from cognilend.ml import entropy

CLASS_NAMES = ['Rejected', 'Approved']


class SelectColumns(BaseEstimator, TransformerMixin):
    def __init__(self, columns=None):
        self.columns = columns

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        return X[list(self.columns)]


def caps() -> dict:
    t = config.load('settings')['tree']
    return {'max_depth': t['max_depth'], 'max_total_nodes': t['max_total_nodes'],
            'max_leaf_nodes': (t['max_total_nodes'] + 1) // 2}     # binary tree: nodes = 2*leaves - 1


def make_model(features: list[str], min_samples_leaf: int, class_weight, smote: bool) -> Pipeline:
    s = config.load('settings')
    c = caps()
    clf = DecisionTreeClassifier(criterion=s['tree']['criterion'], max_depth=c['max_depth'],
                                 max_leaf_nodes=c['max_leaf_nodes'], min_samples_leaf=min_samples_leaf,
                                 class_weight=class_weight, random_state=s['seed'])
    return Pipeline([('select', SelectColumns(list(features))),
                     ('smote', preprocess.make_resampler(list(features)) if smote else 'passthrough'),
                     ('clf', clf)])


def check_constraints(model: Pipeline) -> dict:
    t = model.named_steps['clf']
    c = caps()
    depth, nodes = int(t.get_depth()), int(t.tree_.node_count)
    assert depth <= c['max_depth'], f'tree depth {depth} > {c["max_depth"]}'
    assert nodes <= c['max_total_nodes'], f'tree has {nodes} nodes > {c["max_total_nodes"]}'
    return {'depth': depth, 'node_count': nodes, 'n_leaves': int(t.get_n_leaves())}


def load_processed() -> dict:
    d = preprocess.processed_dir()
    if not (d / 'train.parquet').exists():
        preprocess.run()
    out = {}
    for k in ('train', 'val', 'test'):
        f = pd.read_parquet(d / f'{k}.parquet')
        out[k] = {'X': f.drop(columns=['Loan_ID', preprocess.TARGET]), 'y': f[preprocess.TARGET], 'ids': f['Loan_ID']}
    return out


def _score(model, X, y) -> dict:
    p = model.predict_proba(X)[:, 1]
    pred = (p >= 0.5).astype(int)
    return {'accuracy': float(accuracy_score(y, pred)), 'roc_auc': float(roc_auc_score(y, p)),
            'confusion_matrix': confusion_matrix(y, pred, labels=[0, 1]).tolist(),
            'per_class': {k: {m: round(float(v), 4) for m, v in d.items()} for k, d in classification_report(
                y, pred, labels=[0, 1], target_names=CLASS_NAMES, output_dict=True, zero_division=0).items()
                if k in CLASS_NAMES}}


def grid_search(data: dict) -> tuple[list[dict], list]:
    g = config.load('settings')['model']
    ranking = entropy.rank_features(data['train']['X'], data['train']['y'].to_numpy())
    ordered = [f for f, _, _ in ranking]
    results = []
    for k, smote, cw, msl in itertools.product(g['top_k_features'], g['smote'], g['class_weight'], g['min_samples_leaf']):
        feats = ordered if k is None else ordered[:k]
        m = make_model(feats, msl, cw, smote).fit(data['train']['X'], data['train']['y'])
        tr = accuracy_score(data['train']['y'], m.predict(data['train']['X']))
        va = accuracy_score(data['val']['y'], m.predict(data['val']['X']))
        results.append({'top_k': k, 'smote': smote, 'class_weight': cw, 'min_samples_leaf': msl,
                        'train_accuracy': round(float(tr), 6), 'val_accuracy': round(float(va), 6),
                        'gap': round(float(tr - va), 6), 'features': feats})
    # highest validation accuracy; ties -> smaller |gap| -> simpler (larger leaves, fewer features, no SMOTE)
    results.sort(key=lambda r: (-r['val_accuracy'], abs(r['gap']), -r['min_samples_leaf'],
                                len(r['features']), r['smote'], str(r['class_weight'])))
    return results, ranking


# --------------------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------------------
def raw_unit_converter(pre_bundle: dict):
    """Map a scaled threshold back to original units for continuous features (MinMax is invertible; IQR capping is
    monotone, so the split order is unchanged)."""
    cont = config.load('settings')['preprocess']['continuous']
    scale = pre_bundle['preprocessor'].named_steps['columns'].named_transformers_['num'].named_steps['scale']
    lo, rng = dict(zip(cont, scale.data_min_)), dict(zip(cont, scale.data_range_))
    return lambda f, t: lo[f] + t * rng[f] if f in lo else None


UNITS = {'cibil_score': ('CIBIL', '{:.0f}'), 'work_experience': ('years', '{:.1f}'),
         'total_income': ('INR/month', '{:,.0f}'), 'existing_emi': ('INR/month', '{:,.0f}'),
         'loan_amount': ('INR', '{:,.0f}'), 'loan_tenure': ('months', '{:.0f}'), 'foir': ('ratio', '{:.3f}'),
         'loan_to_income': ('years of income', '{:.2f}'), 'collateral_coverage': ('x loan', '{:.2f}')}


def describe_split(feature: str, threshold: float, to_raw) -> tuple[str, str]:
    """Plain-language (left, right) conditions for `feature <= threshold`."""
    raw = to_raw(feature, threshold)
    if raw is not None:
        unit, fmt = UNITS.get(feature, ('', '{:.4g}'))
        v = fmt.format(raw)
        return f'{feature} <= {v} {unit} (scaled {threshold:.4f})', f'{feature} > {v} {unit}'
    if '_' in feature and feature.split('_')[0] in ('Employment', 'Loan') and feature.count('_') >= 2:
        col, level = feature.rsplit('_', 1)
        return f'{col} is not {level}', f'{col} is {level}'
    if feature.startswith(('is_', 'has_')):
        return f'{feature} = no', f'{feature} = yes'
    return f'{feature} <= {threshold:.4g}', f'{feature} > {threshold:.4g}'


def export_rules(clf: DecisionTreeClassifier, features: list[str], to_raw) -> str:
    t = clf.tree_
    lines = []

    def walk(node, depth):
        pad = '|   ' * depth
        if t.feature[node] == _tree.TREE_UNDEFINED:
            v = t.value[node][0]
            p = v / v.sum()
            k = int(np.argmax(p))
            lines.append(f'{pad}|--> {CLASS_NAMES[k]}  (P(Approved)={p[1]:.3f}, n={int(t.n_node_samples[node])}, '
                         f'node {node})')
            return
        left, right = describe_split(features[t.feature[node]], t.threshold[node], to_raw)
        lines.append(f'{pad}|--- if {left}   [node {node}, entropy {t.impurity[node]:.4f}]')
        walk(t.children_left[node], depth + 1)
        lines.append(f'{pad}|--- if {right}')
        walk(t.children_right[node], depth + 1)

    walk(0, 0)
    return '\n'.join(lines)


def plot_tree_png(clf, features, path: Path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from sklearn.tree import plot_tree
    fig, ax = plt.subplots(figsize=(22, 10))
    plot_tree(clf, feature_names=features, class_names=CLASS_NAMES, filled=True, impurity=True,
              proportion=True, rounded=True, fontsize=9, ax=ax)
    ax.set_title('CogniLend dt_v1: entropy tree, depth <= 4, nodes <= 15 (thresholds are MinMax-scaled; '
                 'see tree_rules.txt for original units)')
    fig.savefig(path, dpi=120, bbox_inches='tight')
    plt.close(fig)


# --------------------------------------------------------------------------------------
# Train
# --------------------------------------------------------------------------------------
def model_path() -> Path:
    s = config.load('settings')
    return config.ROOT / s['paths']['models'] / f"{s['model']['version']}.joblib"


def reports_dir() -> Path:
    return config.ROOT / config.load('settings')['paths']['reports']


def train() -> dict:
    s = config.load('settings')
    data = load_processed()
    results, ranking = grid_search(data)
    best = results[0]
    model = make_model(best['features'], best['min_samples_leaf'], best['class_weight'], best['smote'])
    model.fit(data['train']['X'], data['train']['y'])
    shape = check_constraints(model)
    scores = {k: _score(model, data[k]['X'], data[k]['y']) for k in ('train', 'val', 'test')}
    gap = scores['train']['accuracy'] - scores['val']['accuracy']

    pre_bundle = preprocess.load_preprocessor()
    clf = model.named_steps['clf']
    rules = export_rules(clf, best['features'], raw_unit_converter(pre_bundle))
    out = reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'tree_rules.txt').write_text(rules + '\n', encoding='utf-8')
    (out / 'tree.dot').write_text(export_graphviz(clf, feature_names=best['features'], class_names=CLASS_NAMES,
                                                  filled=True, rounded=True), encoding='utf-8')
    plot_tree_png(clf, best['features'], out / 'tree.png')

    smote_log = None
    if best['smote']:
        Xs = data['train']['X'][best['features']]
        smote_log = preprocess.smote_counts(Xs, data['train']['y'])
    metrics = {
        'version': s['model']['version'], 'preprocessor_version': pre_bundle['version'],
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'sklearn': sklearn.__version__, 'python': platform.python_version(),
        'params': {k: best[k] for k in ('top_k', 'smote', 'class_weight', 'min_samples_leaf')},
        'features': best['features'], **shape, 'caps': caps(),
        'train_accuracy': scores['train']['accuracy'], 'val_accuracy': scores['val']['accuracy'],
        'test_accuracy': scores['test']['accuracy'], 'generalization_gap': gap,
        'kpi_val_accuracy_min': s['kpi']['min_val_accuracy'],
        'kpi_met': scores['val']['accuracy'] >= s['kpi']['min_val_accuracy'],
        'gap_max': s['tree']['max_generalization_gap'], 'gap_met': gap <= s['tree']['max_generalization_gap'],
        'scores': scores, 'smote_train_counts': smote_log,
        'information_gain_ranking': [{'feature': f, 'gain': round(g, 6), 'threshold_scaled': round(t, 6)}
                                     for f, g, t in ranking],
        'grid_top10': [{k: v for k, v in r.items() if k != 'features'} for r in results[:10]],
        'grid_size': len(results),
    }
    (out / 'dt_metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    path = model_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({'version': metrics['version'], 'created_utc': metrics['created_utc'], 'model': model,
                 'features': best['features'], 'params': metrics['params'],
                 'preprocessor_version': pre_bundle['version'], 'sklearn': sklearn.__version__,
                 'test_predictions': model.predict(data['test']['X']).tolist()}, path)
    return {'metrics': metrics, 'rules': rules, 'model': model}


def load_model(path: str | Path | None = None) -> dict:
    return joblib.load(path or model_path())


if __name__ == '__main__':
    from cognilend.ml import tree as _self      # pickle classes as cognilend.ml.tree.*, not __main__.*
    r = _self.train()
    m = r['metrics']
    print(json.dumps({k: m[k] for k in ('params', 'depth', 'node_count', 'n_leaves', 'train_accuracy',
                                        'val_accuracy', 'test_accuracy', 'generalization_gap', 'kpi_met',
                                        'gap_met', 'smote_train_counts')}, indent=2))
    print(json.dumps({k: {'roc_auc': v['roc_auc'], 'per_class': v['per_class'], 'cm': v['confusion_matrix']}
                      for k, v in m['scores'].items()}, indent=1))
    print(r['rules'])
