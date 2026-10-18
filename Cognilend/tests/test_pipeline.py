import importlib.util
import json

import pandas as pd
import pytest
from sqlalchemy import func, select

from cognilend import config
from cognilend.data import preprocess
from cognilend.db.models import Decision
from cognilend.db.repository import FallbackLog, Repository
from cognilend.pipeline import REQUIRED_KEYS, DecisionPipeline

REPORTS = config.ROOT / config.load('settings')['paths']['reports']


def _script(name):
    spec = importlib.util.spec_from_file_location(name, config.ROOT / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def evaluation():
    """Full TEST split through decide_many on the project DB (scripts/evaluate_pipeline.py)."""
    if not (REPORTS / 'pipeline_decisions.csv').exists():
        _script('evaluate_pipeline').main()
    return pd.read_csv(REPORTS / 'pipeline_decisions.csv')


@pytest.fixture(scope='module')
def apps():
    return pd.read_csv(preprocess.processed_dir() / 'test_applications.csv', dtype=str)


def test_full_test_set_coverage_is_100_percent(evaluation, apps):
    assert len(evaluation) == len(apps) == len(tree_test_ids())
    repo = Repository()
    with repo.Session() as s:
        logged = s.execute(select(func.count()).select_from(Decision)
                           .where(Decision.batch_id == 'test-eval')).scalar_one()
        stored_ids = set(s.execute(select(Decision.loan_id).where(Decision.batch_id == 'test-eval')).scalars())
    assert logged == len(apps) and stored_ids == set(apps['Loan_ID'])
    assert evaluation['persisted'].all() and evaluation['fallback_id'].isna().all()
    assert repo.verify_chain().ok
    repo.engine.dispose()


def tree_test_ids():
    return pd.read_parquet(preprocess.processed_dir() / 'test.parquet', columns=['Loan_ID'])['Loan_ID']


def test_every_output_has_the_four_required_parts(evaluation):
    for k in REQUIRED_KEYS:
        assert evaluation[k].notna().all(), k
    assert set(evaluation['decision']) <= {'Approved', 'Rejected', 'Human Review'}
    assert evaluation['confidence'].between(0, 1).all() and (evaluation['reason'].str.len() > 20).all()


def test_none_dropped_and_majority_auto_cleared(evaluation):
    auto = evaluation['decision'].isin(['Approved', 'Rejected'])
    assert auto.mean() > 0.5


def test_reproducibility_report_says_identical():
    md = (REPORTS / 'reproducibility.md').read_text(encoding='utf-8')
    assert '**Result: IDENTICAL**' in md
    hashes = [line.split('`')[1] for line in md.splitlines() if line.startswith('| ') and '`' in line]
    assert len(hashes) == 3 and len(set(hashes)) == 1


def test_two_fresh_runs_identical(tmp_path, apps):
    sample = apps.head(150)
    frames = []
    for i in range(2):
        repo = Repository(f'sqlite:///{(tmp_path / f"r{i}.db").as_posix()}')
        out = DecisionPipeline(repo=repo, fallback=FallbackLog(tmp_path / 'fb.jsonl')).decide_many(sample, 'r')
        frames.append(out[['loan_id', 'decision', 'confidence', 'reason', 'source', 'fired_rules']])
        repo.engine.dispose()
    pd.testing.assert_frame_equal(frames[0], frames[1])


def test_batch_mode_equals_single_decisions(tmp_path, apps):
    sample = apps.iloc[200:260]
    p = DecisionPipeline(persist=False)
    batch = p.decide_many(sample)
    single = [p.decide({k: v for k, v in r.items() if isinstance(v, str)}) for r in sample.to_dict('records')]
    for b, s in zip(batch.to_dict('records'), single):
        assert (b['decision'], b['reason'], b['source']) == (s['decision'], s['reason'], s['source'])
        assert b['confidence'] == pytest.approx(s['confidence'])


def test_decide_returns_the_specified_shape(tmp_path):
    repo = Repository(f'sqlite:///{(tmp_path / "s.db").as_posix()}')
    p = DecisionPipeline(repo=repo, fallback=FallbackLog(tmp_path / 'fb.jsonl'))
    d = p.decide(dict(Age=35, Employment_Type='Salaried', Work_Experience=10, Monthly_Income=150000,
                      Existing_EMI=0, CIBIL_Score=800, Loan_Type='Home', Loan_Amount=3_000_000, Loan_Tenure=240,
                      Collateral_Value=5_000_000))
    for k in ('decision', 'confidence', 'reason', 'tree_path', 'fired_rules', 'audit_log_id', 'model_version',
              'policy_version'):
        assert k in d
    assert d['decision'] == 'Approved' and d['tree_path'] and d['audit_log_id'] and d['model_version'] == 'dt_v1'
    repo.engine.dispose()


def test_hard_reject_logged_without_model(tmp_path):
    repo = Repository(f'sqlite:///{(tmp_path / "h.db").as_posix()}')
    p = DecisionPipeline(repo=repo, fallback=FallbackLog(tmp_path / 'fb.jsonl'))
    d = p.decide({'Age': 20, 'Employment_Type': 'Salaried', 'Work_Experience': 1, 'Monthly_Income': 50000,
                  'Existing_EMI': 0, 'CIBIL_Score': 700, 'Loan_Type': 'Personal', 'Loan_Amount': 100000,
                  'Loan_Tenure': 24})
    assert d['decision'] == 'Rejected' and d['source'] == 'RULE' and d['tree_path'] is None
    with repo.Session() as s:
        dec = s.get(Decision, d['decision_id'])
        assert dec.model_version is None and json.loads(dec.fired_rules_json) == ['R01']
    repo.engine.dispose()
