"""The 7 Minimum Engineering Evidence gates, plus the extra NFR checks, as one named index.

Each test is self-contained; several overlap deliberately with the per-module tests so this file alone proves
each gate. Requires the seeded project DB (python scripts/seed_demo.py).
"""
import json

import numpy as np
import pandas as pd
import pytest
from scipy.stats import entropy as scipy_entropy
from sklearn.metrics import confusion_matrix
from sqlalchemy import select, text

from cognilend import config, demo
from cognilend.data import contract, preprocess
from cognilend.db.models import Decision
from cognilend.db.repository import FallbackLog, Repository
from cognilend.fairness import disparate_impact as di
from cognilend.ml import confidence, entropy, tree
from cognilend.pipeline import REQUIRED_KEYS, DecisionPipeline
from cognilend.rules import engine

REPORTS = config.ROOT / config.load('settings')['paths']['reports']
BATCH = 'test-eval'


@pytest.fixture(scope='module')
def stored():
    """Test-split decisions from the seeded DB, aligned with the cleaned applications and labels."""
    repo = Repository()
    with repo.engine.connect() as c:
        dec = pd.read_sql(text('SELECT loan_id, source, outcome, confidence, fired_rules_json, model_prediction, '
                               'tree_path_json FROM decisions WHERE batch_id = :b'), c, params={'b': BATCH})
    repo.engine.dispose()
    apps = pd.read_csv(preprocess.processed_dir() / 'test_applications.csv', dtype=str)
    clean = pd.read_parquet(preprocess.processed_dir() / 'clean.parquet').set_index('Loan_ID')
    dec = dec.set_index('loan_id').loc[apps['Loan_ID']].reset_index()
    dec['fired'] = dec['fired_rules_json'].map(json.loads)
    dec['label'] = clean.loc[dec['loan_id'], 'target'].to_numpy()
    return dec, apps


# ---------- Gate 1: rule vs model conflict -> zero overrides ----------
def test_gate1_no_model_override_of_a_fired_hard_rule(stored):
    dec, _ = stored
    hard = dec['fired'].map(lambda f: any(r.startswith('R') or r == 'INPUT' for r in f))
    assert hard.sum() > 100
    assert (dec.loc[hard, 'outcome'] == 'Rejected').all()                 # zero overrides
    assert dec.loc[hard, 'model_prediction'].isna().all()                 # model never consulted (FR-6)
    soft = dec['fired'].map(lambda f: bool(f) and all(r.startswith('S') for r in f))
    assert (dec.loc[soft, 'outcome'] == 'Human Review').all()             # SOFT -> review, never auto


# ---------- Gate 2: rare / edge profiles -> review ----------
def rare_subset(dec: pd.DataFrame) -> pd.Series:
    """Rare/edge profiles: the two least-supported tree leaves, new-to-credit, or missing key data."""
    table = confidence.load()['leaf_table']
    smallest = set(table['n'].nsmallest(2).index)
    exp = DecisionPipeline(persist=False).explainer
    clean = pd.read_parquet(preprocess.processed_dir() / 'clean.parquet').set_index('Loan_ID')
    leaves = [e['leaf'] for e in exp.explain(clean.loc[dec['loan_id']].drop(columns=['split']).reset_index())]
    dec['leaf'] = leaves
    edge = dec['fired'].map(lambda f: 'S01' in f or 'S04' in f)
    return dec['leaf'].isin(smallest) | edge


def test_gate2_rare_profiles_routed_to_review_with_confusion_matrix(stored):
    dec, _ = stored
    rare = rare_subset(dec)
    sub = dec[rare]
    hard = sub['fired'].map(lambda f: any(r.startswith('R') or r == 'INPUT' for r in f))
    assert len(sub) > 50
    assert (sub.loc[~hard, 'outcome'] == 'Human Review').all()            # never auto-decided by the model
    assert not ((sub['outcome'] != 'Rejected') & hard).any()
    pred = (sub['model_prediction'] == 'Approved').astype(int)
    scored = sub['model_prediction'].notna()
    cm = confusion_matrix(sub.loc[scored, 'label'], pred[scored], labels=[0, 1])
    assert cm.sum() == scored.sum()
    (REPORTS / 'rare_subset.json').write_text(json.dumps({
        'definition': 'two least-supported leaves, new-to-credit (S01) or missing key data (S04)',
        'n': int(len(sub)), 'routed_to_review': int((sub['outcome'] == 'Human Review').sum()),
        'hard_rejected': int(hard.sum()), 'auto_decided_by_model': int(((sub['source'] == 'MODEL')
                                                                         & (sub['outcome'] != 'Human Review')).sum()),
        'confusion_matrix_model_vs_label': {'labels': ['Rejected', 'Approved'], 'matrix': cm.tolist()},
        'model_accuracy_on_rare': float(np.trace(cm) / cm.sum())}, indent=2))


# ---------- Gate 3: SMOTE train-only ----------
def test_gate3_smote_train_only_no_leakage():
    b = preprocess.build()
    original = b['clean'][preprocess.TARGET].mean()
    for k in ('val', 'test'):
        assert abs(b['y'][k].mean() - original) <= 0.01                   # distribution unchanged
        assert len(b['X'][k]) == len(b['parts'][k])                       # not resampled
    model = tree.load_model()['model']
    assert model.named_steps['smote'] != 'passthrough'                    # SMOTE is inside the pipeline...
    data = tree.load_processed()
    assert len(model.predict(data['test']['X'])) == len(data['test']['y'])  # ...and skipped at predict time
    bf = b['preprocessor'].named_steps['features']
    assert all(bf.medians_[c] == b['parts']['train'][c].median() for c in bf.medians_)   # fitted on train only


# ---------- Gate 4: DB write failure ----------
class _Broken(Repository):
    def record_decision(self, d):
        raise RuntimeError('injected write failure')


def test_gate4_db_failure_no_crash_no_silent_loss(tmp_path):
    broken = _Broken(f'sqlite:///{(tmp_path / "b.db").as_posix()}')
    fb = FallbackLog(tmp_path / 'fb.jsonl')
    p = DecisionPipeline(repo=broken, fallback=fb)
    outs = [p.decide(demo.clean(demo.CASES[n][1][-1])) for n in demo.CASES]
    assert all(o['decision'] in ('Approved', 'Rejected', 'Human Review') for o in outs)
    assert len(fb.pending()) == len(outs) and all(o['fallback_id'] for o in outs)
    ok = Repository(f'sqlite:///{(tmp_path / "ok.db").as_posix()}')
    assert fb.replay(ok)['replayed'] == len(outs) and ok.count(Decision) == len(outs)
    broken.engine.dispose()
    ok.engine.dispose()


# ---------- Gate 5: missing / invalid fields ----------
def test_gate5_missing_and_invalid_fields_100_percent_handled():
    bad_values = [None, '', 'abc', -1e9, 1e15, [], {}, object(), float('nan'), float('inf'), True]
    base = demo.clean(demo.CASES['auto_approve'][1][0])
    cases = [{**base, f: v} for f in contract.INPUT_FIELDS for v in bad_values]
    cases += [{k: v for k, v in base.items() if k != f} for f in base] + [None, [], 'x', 42, {}]
    p = DecisionPipeline(persist=False)
    handled = 0
    for c in cases:
        out = p.decide(c)
        assert out['decision'] in ('Approved', 'Rejected', 'Human Review') and out['reason']
        handled += 1
    assert handled == len(cases) > 200


# ---------- Gate 6: fairness breach ----------
def test_gate6_fairness_breach_detected_and_reported():
    frame = pd.DataFrame({'Gender': ['Male'] * 300 + ['Female'] * 300, 'Age': 40, 'Dependents': 1,
                          'pipeline': [1, 0] * 300, 'Loan_ID': range(600)})
    t = di.audit(di.inject_breach(frame, 'pipeline'), 'pipeline', 'gate6')
    assert t.loc[t['subgroup'] == 'SYNTHETIC-BREACH', 'flagged'].item()
    report = (REPORTS / 'fairness.md').read_text(encoding='utf-8')
    assert 'SYNTHETIC-BREACH' in report and 'flagged = **True**' in report


# ---------- Gate 7: reproducibility ----------
def test_gate7_reproducible_over_three_runs(tmp_path):
    md = (REPORTS / 'reproducibility.md').read_text(encoding='utf-8')
    assert '**Result: IDENTICAL**' in md
    sample = pd.read_csv(preprocess.processed_dir() / 'test_applications.csv', dtype=str).head(80)
    runs = []
    for i in range(3):
        repo = Repository(f'sqlite:///{(tmp_path / f"r{i}.db").as_posix()}')
        out = DecisionPipeline(repo=repo, fallback=FallbackLog(tmp_path / 'fb.jsonl')).decide_many(sample, 'g7')
        runs.append(out[['loan_id', 'decision', 'confidence', 'reason', 'fired_rules']])
        repo.engine.dispose()
    pd.testing.assert_frame_equal(runs[0], runs[1])
    pd.testing.assert_frame_equal(runs[0], runs[2])


# ---------- extra NFR checks ----------
def test_nfr_tree_caps_and_gap():
    m = json.loads((REPORTS / 'dt_metrics.json').read_text())
    clf = tree.load_model()['model'].named_steps['clf']
    assert clf.get_depth() <= 4 and clf.tree_.node_count <= 15
    assert m['generalization_gap'] <= 0.15


def test_nfr_entropy_error_below_1e_9():
    rng = np.random.default_rng(42)
    err = max(abs(entropy.entropy(p) - scipy_entropy(p, base=2)) for p in rng.random((1000, 10)))
    assert err <= 1e-9


def test_nfr_audit_tamper_detection(tmp_path):
    from cognilend.db import audit
    repo = Repository(f'sqlite:///{(tmp_path / "t.db").as_posix()}')
    with repo.Session.begin() as s:
        for i in range(5):
            audit.append(s, 'e', {'i': i})
    with repo.engine.begin() as c:
        c.exec_driver_sql('DROP TRIGGER audit_log_no_update')
        c.exec_driver_sql("UPDATE audit_log SET payload_json = '{\"i\":99}' WHERE seq = 3")
    assert repo.verify_chain().first_broken_seq == 3
    repo.engine.dispose()


def test_nfr_concurrency_lock_load_test_passed():
    r = json.loads((REPORTS / 'lock_load_test.json').read_text())
    assert r['pass'] and r['approved'] == r['collaterals'] and r['max_approvals_per_collateral'] == 1


def test_nfr_decision_log_coverage_100_percent(stored):
    dec, apps = stored
    assert len(dec) == len(apps) and dec['outcome'].notna().all()
    out = pd.read_csv(REPORTS / 'pipeline_decisions.csv')
    assert out[list(REQUIRED_KEYS)].notna().all().all()


def test_end_to_end_smoke(tmp_path):
    repo = Repository(f'sqlite:///{(tmp_path / "e2e.db").as_posix()}')
    p = DecisionPipeline(repo=repo, fallback=FallbackLog(tmp_path / 'fb.jsonl'))
    for name, (_, _, expected, source) in demo.CASES.items():
        d = demo.run_case(p, name)
        assert (d['decision'], d['source']) == (expected, source), name
        assert all(d[k] is not None for k in REQUIRED_KEYS)
    assert repo.verify_chain().ok
    with repo.Session() as s:
        assert len(s.execute(select(Decision)).scalars().all()) == sum(len(c[1]) for c in demo.CASES.values())
    repo.engine.dispose()


def test_rule_engine_never_raises_on_engine_level_garbage():
    for g in (None, 1, 'x', [], {'Age': object()}):
        assert engine.evaluate(g)['outcome'] == 'REJECT'
