import inspect

import numpy as np
import pytest

from cognilend import pipeline
from cognilend.stress_twin import simulator as st

INP = st.StressInputs(income_mean=80000, income_cv=0.15, income_day=1, essentials=35000, existing_emi=5000,
                      loan_amount=1_500_000, annual_rate=0.105, tenure_months=60, emi_due_day=5, savings=60000)


# ---------- metric formulas ----------
def test_emi_formula():
    r = 0.12 / 12
    g = (1 + r) ** 12
    assert st.emi(120000, 0.12, 12) == pytest.approx(120000 * r * g / (g - 1))
    assert st.emi(120000, 0.0, 12) == 10000


def test_min_cash_balance():
    np.testing.assert_array_equal(st.min_cash_balance(np.array([[5, -3, 2], [1, 2, 3]])), [-3, 1])


def test_shortfall_probability():
    assert st.shortfall_probability(np.array([-3, 1, 2, -0.01])) == 0.5


def test_max_shortfall():
    assert st.max_shortfall(np.array([-3, 1, -7])) == 7
    assert st.max_shortfall(np.array([0, 1])) == 0


def test_months_in_deficit():
    np.testing.assert_array_equal(st.months_in_deficit(np.array([[1, -1, -2, 3], [1, 1, 1, 1]])), [2, 0])


def test_recovery_time():
    me = np.array([[1, -1, -2, 3],       # first deficit month 1, back >= 0 in month 3 -> 2 months
                   [1, -1, -1, -1],      # never recovers -> censored at horizon - first = 3
                   [1, 1, 1, 1]])        # never in deficit -> 0
    np.testing.assert_array_equal(st.recovery_time(me), [2, 3, 0])


def test_stressed_foir():
    out = st.stressed_foir(30000, np.array([[100000, 60000], [0, 50000]]))
    assert out[0] == 0.5 and np.isinf(out[1])


def test_buffer_coverage():
    assert st.buffer_coverage(60000, 35000, 25000) == 1.0
    assert st.buffer_coverage(1, 0, 0) == float('inf')


@pytest.mark.parametrize('p,buf,foir,score', [(0.0, 6, 0.0, 100.0), (1.0, 0, 1.0, 0.0), (0.2, 3, 0.5, 65.0),
                                              (0.0, 12, float('inf'), 75.0)])
def test_resilience_score(p, buf, foir, score):
    assert st.resilience_score(p, buf, foir) == score


@pytest.mark.parametrize('p,label', [(0.05, 'Resilient'), (0.10, 'Vulnerable - consider alternative terms'),
                                     (0.29, 'Vulnerable - consider alternative terms'),
                                     (0.30, 'High stress - suggest review'),
                                     (None, 'Insufficient data - suggest review')])
def test_bands(p, label):
    assert st.band(p) == label


# ---------- simulation ----------
def test_deterministic_with_seed():
    assert st.simulate(INP) == st.simulate(INP)
    assert st.simulate(INP, seed=7) != st.simulate(INP)


def test_shape_of_result():
    r = st.simulate(INP)
    assert set(r['scenarios']) == {'baseline', 'income_drop', 'expense_spike', 'payment_delay', 'combined'}
    for m in r['scenarios'].values():
        assert 0 <= m['shortfall_probability'] <= 1 and m['max_shortfall'] >= 0
        assert m['min_cash_balance_p05'] <= m['min_cash_balance_median']
    assert 0 <= r['resilience'] <= 100 and r['illustrative'] is True


def test_shocks_never_make_things_better_than_baseline():
    s = st.simulate(INP)['scenarios']
    for sc in ('income_drop', 'expense_spike', 'combined'):
        assert s[sc]['shortfall_probability'] >= s['baseline']['shortfall_probability']
    assert s['combined']['shortfall_probability'] >= max(s['income_drop']['shortfall_probability'],
                                                         s['expense_spike']['shortfall_probability'])


def test_payment_delay_bites_when_income_lands_after_the_due_date():
    # surplus of only 1,000 a month: savings never grow enough to cover the EMI before a late salary
    tight = st.StressInputs(income_mean=51000, income_cv=0.0, income_day=3, essentials=20000, proposed_emi=30000,
                            emi_due_day=5, savings=5000)
    s = st.simulate(tight, scenarios=['baseline', 'payment_delay'])['scenarios']
    assert s['baseline']['shortfall_probability'] == 0.0
    assert s['payment_delay']['shortfall_probability'] == 1.0     # one month's salary lands after the EMI


def test_insufficient_data_suggests_review():
    r = st.simulate(st.StressInputs(income_mean=None, income_cv=0.1, income_day=1, essentials=20000,
                                    proposed_emi=5000))
    assert r['band'] == 'Insufficient data - suggest review' and 'income_mean' in r['missing'][0]


def test_alternatives_lower_the_burden():
    base = st.simulate(INP, scenarios=['combined'])['scenarios']['combined']['shortfall_probability']
    alts = {a['alternative']: a for a in st.alternatives(INP)}
    lower = next(v for k, v in alts.items() if k.startswith('loan amount'))
    longer = next(v for k, v in alts.items() if k.startswith('tenure'))
    assert lower['total_emi'] < INP.total_emi() and lower['shortfall_probability'] <= base
    assert longer['total_emi'] < INP.total_emi() and longer['shortfall_probability'] <= base


def test_advisory_only_not_used_by_the_decision_pipeline():
    assert 'stress_twin' not in inspect.getsource(pipeline)
