import json

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from cognilend import config
from cognilend.db.models import FairnessReport
from cognilend.db.repository import Repository
from cognilend.fairness import disparate_impact as di
from cognilend.pipeline import DecisionPipeline

REPORTS = config.ROOT / config.load('settings')['paths']['reports']


def toy(rates: dict, n: int = 200, seed: int = 0) -> tuple[pd.Series, pd.Series]:
    rng = np.random.default_rng(seed)
    labels, y = [], []
    for g, (size, rate) in rates.items():
        k = int(round(size * rate))
        labels += [g] * size
        y += [1] * k + [0] * (size - k)
    return pd.Series(labels), pd.Series(y)


def test_di_is_rate_over_most_favoured():
    labels, y = toy({'A': (200, 0.5), 'B': (200, 0.3), 'C': (10, 0.0)})
    t = di.di_table(labels, y, 'gender').set_index('subgroup')
    assert t.loc['B', 'reference'] == 'A'
    assert t.loc['B', 'di'] == pytest.approx(0.6) and t.loc['B', 'flagged']
    assert t.loc['A', 'di'] == 1.0 and not t.loc['A', 'flagged']
    assert t.loc['B', 'ci_low'] < 0.6 < t.loc['B', 'ci_high']


def test_small_subgroup_is_reported_not_flagged():
    labels, y = toy({'A': (200, 0.5), 'C': (10, 0.0)})
    t = di.di_table(labels, y, 'gender').set_index('subgroup')
    assert t.loc['C', 'insufficient'] and not t.loc['C', 'flagged'] and t.loc['C', 'status'] == 'insufficient data'


def test_unknown_is_never_the_reference():
    labels, y = toy({'Unknown': (100, 0.9), 'A': (200, 0.5), 'B': (200, 0.45)})
    assert di.di_table(labels, y, 'gender')['reference'].iloc[0] == 'A'


def test_subgroup_bands():
    f = pd.DataFrame({'Gender': ['Female', None], 'Age': [24, 60], 'Dependents': [0, 3]})
    lab = di.subgroup_labels(f)
    assert lab['gender'].tolist() == ['Female', 'Unknown']
    assert lab['age_band'].tolist() == ['<=25', '>55'] and lab['dependents'].tolist() == ['0', '3+']


def test_breach_injection_is_flagged():
    labels, y = toy({'Male': (300, 0.4), 'Female': (300, 0.38)})
    frame = pd.DataFrame({'Gender': labels, 'Age': 40, 'Dependents': 1, 'pipeline': y, 'Loan_ID': range(600)})
    before = di.audit(frame, 'pipeline', 'x')
    assert not before['flagged'].any()
    after = di.audit(di.inject_breach(frame, 'pipeline'), 'pipeline', 'x')
    row = after[after['subgroup'] == 'SYNTHETIC-BREACH'].iloc[0]
    assert row['flagged'] and row['di'] < 0.8


# ---------- the real run ----------
@pytest.fixture(scope='module')
def report():
    if not (REPORTS / 'fairness.md').exists():
        di.run()
    return (REPORTS / 'fairness.md').read_text(encoding='utf-8')


def test_report_states_the_verdict_plainly(report):
    holds = '**DI >= 0.80 holds for every subgroup with sufficient data**' in report
    fails = '**DI >= 0.80 does NOT hold for every subgroup.**' in report
    assert holds != fails
    if fails:
        assert '## Mitigation analysis' in report and 'Not done, by rule' in report
        assert 'Decision needed' in report


def test_breach_surfaced_in_report_and_database(report):
    assert 'SYNTHETIC-BREACH' in report and 'flagged = **True**' in report
    repo = Repository()
    with repo.Session() as s:
        rows = s.execute(select(FairnessReport).where(FairnessReport.mode == 'breach_test',
                                                      FairnessReport.subgroup == 'SYNTHETIC-BREACH')).scalars().all()
    repo.engine.dispose()
    assert rows and rows[-1].flagged and json.loads(rows[-1].versions_json)['model'] == 'dt_v1'


def test_runs_saved_for_every_mode():
    repo = Repository()
    with repo.Session() as s:
        modes = set(s.execute(select(FairnessReport.mode)).scalars())
    repo.engine.dispose()
    assert {'rules_only', 'model_only', 'pipeline', 'breach_test'} <= modes


def test_audit_uses_the_stored_decisions_consistently(report):
    assert 'differ from the decisions table in **0** rows' in report
    assert 'differs from the protected side table in **0** rows' in report


def test_layer_table_and_chart_present(report):
    table = pd.read_csv(REPORTS / 'fairness_di.csv')
    assert {'label', 'rules_only', 'model_only', 'pipeline', 'pipeline_not_rejected'} <= set(table['mode'])
    assert set(table['group']) == set(di.GROUPS)
    assert (REPORTS / 'fairness_di.png').stat().st_size > 0
    assert (REPORTS / 'fairness_contrib_shift.csv').stat().st_size > 0


def test_gender_and_marital_status_never_change_a_decision():
    p = DecisionPipeline(persist=False)
    base = dict(Age=35, Employment_Type='Salaried', Work_Experience=10, Monthly_Income=60000, Existing_EMI=5000,
                CIBIL_Score=720, Loan_Type='Personal', Loan_Amount=300000, Loan_Tenure=36, Dependents=1)
    outs = {(g, m): p.decide({**base, 'Gender': g, 'Marital_Status': m})
            for g in ('Male', 'Female', 'Transgender', None) for m in ('Married', 'Single', None)}
    first = next(iter(outs.values()))
    for o in outs.values():
        assert (o['decision'], o['confidence'], o['reason']) == (first['decision'], first['confidence'], first['reason'])
