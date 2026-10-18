import json

import numpy as np
import pandas as pd
import pytest

from cognilend import config
from cognilend.data import preprocess
from cognilend.ml import confidence, explain, tree


@pytest.fixture(scope='module')
def bundle():
    if not confidence.model_path().exists():
        confidence.run()
    return confidence.load()


@pytest.fixture(scope='module')
def data():
    return tree.load_processed()


@pytest.fixture(scope='module')
def explainer(bundle):
    return explain.Explainer(conf_bundle=bundle)


@pytest.fixture(scope='module')
def test_explanations(explainer, data):
    clean = pd.read_parquet(preprocess.processed_dir() / 'clean.parquet')
    rows = clean[clean['split'] == 'test'].drop(columns=['split'])
    rows = rows.set_index('Loan_ID').loc[data['test']['ids']].reset_index()   # same order as test.parquet
    return rows, explainer.explain(rows)


def test_leaf_counts_are_real_training_rows_not_smote(bundle, data):
    t = bundle['leaf_table']
    assert t['n'].sum() == len(data['train']['y'])
    assert t['k_approved'].sum() == int(data['train']['y'].sum())


def test_posterior_mean_beta_1_1(bundle):
    t = bundle['leaf_table']
    k_pred = np.where(t['predicted'] == 1, t['k_approved'], t['n'] - t['k_approved'])
    np.testing.assert_allclose(t['confidence'], (k_pred + 1) / (t['n'] + 2))
    assert ((t['ci_low'] < t['confidence']) & (t['confidence'] < t['ci_high'])).all()


def test_tau_in_settings_matches_tuning(bundle):
    assert config.load('settings')['confidence']['tau'] == pytest.approx(bundle['chosen']['tau'])


def test_every_test_prediction_has_confidence_path_and_sentence(test_explanations, data):
    rows, ex = test_explanations
    assert len(ex) == len(data['test']['y'])
    for e in ex:
        assert 0 < e['confidence'] < 1
        assert 1 <= len(e['path']) <= 4
        assert e['sentence'].startswith(('Approved', 'Rejected')) and 'because' in e['sentence']
        for step in e['path']:
            assert {'feature', 'threshold', 'applicant_value', 'direction'} <= set(step)
            assert step['direction'] in ('<=', '>')


def test_explanations_match_saved_model_predictions(test_explanations):
    _, ex = test_explanations
    saved = tree.load_model()['test_predictions']
    assert [1 if e['predicted'] == 'Approved' else 0 for e in ex] == saved


def test_clean_rows_reproduce_processed_test_matrix(test_explanations, explainer, data):
    rows, _ = test_explanations
    scaled, _ = explainer.matrices(rows)
    np.testing.assert_allclose(scaled.to_numpy(dtype=float), data['test']['X'].to_numpy(dtype=float))


def test_path_values_are_in_original_units_and_consistent(test_explanations):
    rows, ex = test_explanations
    for e, (_, r) in zip(ex[:200], rows.iloc[:200].iterrows()):
        for s in e['path']:
            if s['feature'] == 'cibil_score' and pd.isna(r['CIBIL_Score']):
                assert s['imputed'] and 'imputed' in s['text']           # never shown as a real score
            elif s['feature'] == 'cibil_score' and r['CIBIL_Score'] != -1:
                assert s['applicant_value'] == r['CIBIL_Score'] and not s['imputed']
                assert 300 <= s['threshold'] <= 900
            if s['feature'] in ('cibil_score', 'foir', 'work_experience'):
                ok = s['applicant_value'] <= s['threshold'] if s['direction'] == '<=' else \
                    s['applicant_value'] > s['threshold']
                assert ok, s


def test_contributions_sum_to_leaf_probability(test_explanations, bundle):
    _, ex = test_explanations
    nodes = bundle['node_table']
    for e in ex:
        total = e['prior'] + sum(e['contributions'].values())
        assert total == pytest.approx(nodes.p_approved[e['leaf']], abs=1e-9)


def test_evidence_gate_routes_smallest_leaves_to_review(bundle, data):
    t = bundle['leaf_table']
    smallest = t['n'].idxmin()
    n_min = int(t.loc[smallest, 'n']) + 1                   # gate set just above the smallest leaf
    s = confidence.score(tree.load_model()['model'], t, data['test']['X'], tau=0.0, n_min=n_min)
    assert (s.loc[s['leaf'] == smallest, 'route'] == 'review').all()
    assert (s.loc[s['n'] >= n_min, 'route'] == 'auto').all()   # tau = 0 -> only the gate routes


@pytest.mark.parametrize('conf,n,expected', [(0.95, 10, 'review'), (0.95, 500, 'auto'), (0.60, 500, 'review'),
                                             (0.70, 30, 'auto')])
def test_route_rule(conf, n, expected):
    assert confidence.route([conf], [n], tau=0.70, n_min=30)[0] == expected


def test_routing_split_none_dropped_and_majority_auto(bundle):
    for split in ('val', 'test'):
        r = bundle['routing'][split]
        assert r['auto'] + r['review'] == r['n'] and r['dropped'] == 0
        assert r['auto_share'] > 0.5
    print('routing:', json.dumps(bundle['routing'], indent=1))


def test_auto_cases_more_accurate_than_review_cases(bundle):
    r = bundle['routing']['test']
    assert r['auto_accuracy'] > r['overall_accuracy'] > r['review_accuracy']


def test_reports_written():
    d = tree.reports_dir()
    for f in ('calibration.png', 'routing.md', 'routing.json', 'explanations.md', 'explain_shift.csv'):
        assert (d / f).stat().st_size > 0
