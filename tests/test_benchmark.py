import pandas as pd
import pytest

from cognilend.ml import benchmark, tree


@pytest.fixture(scope='module')
def table():
    path = tree.reports_dir() / 'benchmark.csv'
    if not path.exists():
        benchmark.run()
    return pd.read_csv(path)


def test_four_models_on_the_same_test_set(table):
    assert set(table['model']) == {'decision_tree', 'random_forest', 'xgboost', 'gradient_boosting'}
    assert table['n_test'].nunique() == 1 and table['n_test'].iloc[0] == len(tree.load_processed()['test']['y'])


def test_cv_and_test_numbers_reported(table):
    for c in ('test_accuracy', 'test_f1', 'test_roc_auc', 'cv_accuracy_mean', 'cv_accuracy_std',
              'cv_roc_auc_mean', 'cv_f1_mean'):
        assert table[c].notna().all() and table[c].between(0, 1).all()


def test_markdown_numbers_come_from_the_csv(table):
    md = (tree.reports_dir() / 'benchmark.md').read_text(encoding='utf-8')
    for _, r in table.iterrows():
        assert f'{r.test_accuracy:.4f}' in md and f'{r.cv_accuracy_mean:.4f}' in md
    t = table.set_index('model')
    cost = t.drop(index='decision_tree')['test_accuracy'].max() - t.loc['decision_tree', 'test_accuracy']
    assert f'**{cost:.4f}**' in md


def test_decision_tree_row_matches_saved_metrics(table):
    import json
    m = json.loads((tree.reports_dir() / 'dt_metrics.json').read_text())
    dt = table.set_index('model').loc['decision_tree']
    assert dt['test_accuracy'] == pytest.approx(m['test_accuracy'], abs=1e-4)
