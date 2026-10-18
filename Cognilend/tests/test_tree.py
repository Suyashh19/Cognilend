import json

import numpy as np
import pytest
from scipy.stats import entropy as scipy_entropy
from sklearn.tree import DecisionTreeClassifier

from cognilend import config
from cognilend.ml import entropy, tree

TOL = config.load('settings')['tree']['entropy_tolerance']


@pytest.fixture(scope='module')
def saved():
    if not tree.model_path().exists() or not (tree.reports_dir() / 'dt_metrics.json').exists():
        tree.train()
    return tree.load_model()


@pytest.fixture(scope='module')
def metrics(saved):
    return json.loads((tree.reports_dir() / 'dt_metrics.json').read_text())


@pytest.fixture(scope='module')
def data():
    return tree.load_processed()


# ---------- NFR-7: entropy ----------
def test_entropy_matches_scipy_on_1000_random_distributions():
    rng = np.random.default_rng(42)
    worst = 0.0
    for _ in range(1000):
        k = int(rng.integers(2, 21))
        p = rng.random(k)
        p[rng.random(k) < 0.2] = 0.0                 # include zero-probability classes
        if p.sum() == 0:
            p[0] = 1.0
        worst = max(worst, abs(entropy.entropy(p) - scipy_entropy(p, base=2)))
    assert worst <= TOL, worst


@pytest.mark.parametrize('p,h', [([1, 0], 0.0), ([1, 1], 1.0), ([1, 1, 1, 1], 2.0), ([0, 0], 0.0)])
def test_entropy_known_values(p, h):
    assert entropy.entropy(p) == pytest.approx(h, abs=TOL)


def test_entropy_rejects_bad_input():
    for bad in ([], [-1, 2], [np.nan, 1]):
        with pytest.raises(ValueError):
            entropy.entropy(bad)


def test_information_gain_brute_force():
    rng = np.random.default_rng(42)
    x, y = rng.normal(size=200), rng.integers(0, 2, 200)
    gain, thr = entropy.best_threshold(x, y)
    brute = max(entropy.information_gain(y, x <= t) for t in np.unique(x))
    assert gain == pytest.approx(brute, abs=TOL)
    assert entropy.information_gain(y, x <= thr) == pytest.approx(gain, abs=TOL)


def test_information_gain_matches_sklearn_root_split(data):
    X, y = data['train']['X'], data['train']['y'].to_numpy()
    stump = DecisionTreeClassifier(criterion='entropy', max_depth=1, random_state=42).fit(X, y)
    t = stump.tree_
    n = t.n_node_samples
    sk_gain = t.impurity[0] - (n[1] * t.impurity[1] + n[2] * t.impurity[2]) / n[0]
    best_feature, best_gain, _ = entropy.rank_features(X, y)[0]
    assert X.columns[t.feature[0]] == best_feature
    assert best_gain == pytest.approx(sk_gain, abs=TOL)
    assert entropy.label_entropy(y) == pytest.approx(t.impurity[0], abs=TOL)


# ---------- synopsis constraints on the saved model ----------
def test_saved_model_depth_and_node_caps(saved):
    clf = saved['model'].named_steps['clf']
    assert clf.get_depth() <= 4
    assert clf.tree_.node_count <= 15
    assert clf.criterion == 'entropy'
    tree.check_constraints(saved['model'])


def test_generalization_gap_within_limit(metrics):
    gap = metrics['train_accuracy'] - metrics['val_accuracy']
    assert gap == pytest.approx(metrics['generalization_gap'])
    assert gap <= config.load('settings')['tree']['max_generalization_gap'], gap


def test_metrics_report_has_required_fields(metrics):
    for k in ('train_accuracy', 'val_accuracy', 'test_accuracy', 'generalization_gap', 'depth', 'node_count',
              'kpi_met', 'params'):
        assert k in metrics
    for split in ('train', 'val', 'test'):
        s = metrics['scores'][split]
        assert 0.5 < s['roc_auc'] <= 1 and len(s['confusion_matrix']) == 2
        assert set(s['per_class']) == {'Rejected', 'Approved'}
        assert {'precision', 'recall', 'f1-score'} <= set(s['per_class']['Approved'])


def test_kpi_flag_is_honest(metrics):
    assert metrics['kpi_met'] == (metrics['val_accuracy'] >= 0.80)


def test_no_protected_feature_in_model(saved):
    assert not [f for f in saved['features'] if f.startswith(('Gender', 'Marital', 'Age', 'age_', 'Property'))]


# ---------- reproducibility ----------
def test_retraining_gives_identical_predictions(saved, data):
    p = saved['params']
    again = tree.make_model(saved['features'], p['min_samples_leaf'], p['class_weight'], p['smote'])
    again.fit(data['train']['X'], data['train']['y'])
    assert again.predict(data['test']['X']).tolist() == saved['test_predictions']
    np.testing.assert_array_equal(again.predict_proba(data['val']['X']), saved['model'].predict_proba(data['val']['X']))


def test_exports_exist_and_rules_use_original_units(saved):
    d = tree.reports_dir()
    for f in ('tree.png', 'tree.dot', 'tree_rules.txt', 'dt_metrics.json'):
        assert (d / f).stat().st_size > 0
    rules = (d / 'tree_rules.txt').read_text(encoding='utf-8')
    leaves = saved['model'].named_steps['clf'].get_n_leaves()
    assert rules.count('|-->') == leaves
    assert 'CIBIL' in rules or 'INR' in rules or 'ratio' in rules
