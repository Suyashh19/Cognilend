import math

import numpy as np
import pandas as pd
import pytest

from cognilend import config, pipeline
from cognilend.data import contract, preprocess
from cognilend.ml import tree
from cognilend.rules import engine
from cognilend.rules.rules import load_policy, load_rules

GOOD = dict(Applicant_ID='ABCDE1234F', Age=35, Gender='Female', Marital_Status='Married', Dependents=1,
            Employment_Type='Salaried', Work_Experience=10, Monthly_Income=150000, Existing_EMI=0, CIBIL_Score=800,
            Loan_Type='Home', Loan_Amount=3_000_000, Loan_Tenure=240, Collateral_Value=5_000_000,
            Property_Area='Urban')
PERSONAL = dict(Loan_Type='Personal', Loan_Amount=100_000, Loan_Tenure=24, Collateral_Value=None)


def run(**changes):
    return engine.evaluate({**GOOD, **changes})


def status(result, rule_id):
    return next(e['status'] for e in result['evaluations'] if e['rule_id'] == rule_id)


def test_baseline_applicant_passes_every_rule():
    r = run()
    assert r['outcome'] == 'PASS' and r['fired_rules'] == [] and r['policy_version'] == 'v1'


# ---------- one positive and one negative test per rule ----------
def test_r01_fires_below_21():
    r = run(Age=20, Work_Experience=1)
    assert r['outcome'] == 'REJECT' and 'R01' in r['fired_rules'] and 'minimum age' in r['reasons'][0]


def test_r01_passes_at_21():
    assert status(run(Age=21, Work_Experience=3), 'R01') == 'passed'


def test_r02_fires_on_registry_hit():
    r = run(Applicant_ID='FRAUD0001')
    assert r['outcome'] == 'REJECT' and r['fired_rules'] == ['R02']


def test_r02_passes_for_clean_applicant_and_skips_without_id():
    assert status(run(), 'R02') == 'passed'
    no_id = {k: v for k, v in GOOD.items() if k != 'Applicant_ID'}
    assert status(engine.evaluate(no_id), 'R02') == 'not_evaluated'


def test_r03_fires_above_65_at_maturity():
    r = run(Age=50, Loan_Tenure=240)              # 70 at maturity
    assert 'R03' in r['fired_rules'] and r['outcome'] == 'REJECT'


def test_r03_passes_at_exactly_65():
    assert status(run(Age=45, Loan_Tenure=240), 'R03') == 'passed'


def test_r04_fires_at_649():
    assert 'R04' in run(CIBIL_Score=649)['fired_rules']


def test_r04_passes_at_650_and_exempts_new_to_credit():
    assert status(run(CIBIL_Score=650), 'R04') == 'passed'
    r = run(CIBIL_Score=-1)
    assert status(r, 'R04') == 'exempt' and r['outcome'] == 'REVIEW'


def test_r05_fires_when_foir_exceeds_slab_limit():
    r = run(Monthly_Income=40_000, Existing_EMI=15_000)
    assert 'R05' in r['fired_rules'] and r['facts']['foir_limit'] == 0.50


@pytest.mark.parametrize('income,limit', [(49_999, 0.50), (50_000, 0.55), (100_000, 0.55), (100_001, 0.65)])
def test_r05_passes_and_uses_income_slabs(income, limit):
    r = run(Monthly_Income=income, Loan_Amount=500_000, Collateral_Value=2_000_000)
    assert r['facts']['foir_limit'] == limit and status(r, 'R05') == 'passed'


@pytest.mark.parametrize('amount,collateral,fires', [
    (2_500_000, 2_700_000, True), (2_500_000, 2_800_000, False),     # <= 30 L: 90%
    (5_000_000, 6_000_000, True), (5_000_000, 6_300_000, False),     # 30-75 L: 80%
    (9_000_000, 11_500_000, True), (9_000_000, 12_500_000, False),   # > 75 L: 75%
])
def test_r06_rbi_ltv_tiers(amount, collateral, fires):
    r = run(Monthly_Income=500_000, Loan_Amount=amount, Collateral_Value=collateral)
    assert (status(r, 'R06') == 'fired') == fires


def test_r06_not_applicable_to_vehicle_loans():
    r = run(Loan_Type='Vehicle', Loan_Amount=900_000, Collateral_Value=950_000, Loan_Tenure=60)
    assert status(r, 'R06') == 'not_applicable'


def test_r07_fires_below_minimum_income():
    assert 'R07' in run(Monthly_Income=12_000, **PERSONAL)['fired_rules']


def test_r07_passes_with_coapplicant_income_clubbed():
    r = run(Monthly_Income=12_000, Coapplicant_Income=8_000, **PERSONAL)
    assert status(r, 'R07') == 'passed' and r['facts']['total_income'] == 20_000


def test_s01_new_to_credit_goes_to_review():
    r = run(CIBIL_Score=-1)
    assert r['outcome'] == 'REVIEW' and r['fired_rules'] == ['S01']


def test_s01_scored_applicant_not_flagged():
    assert status(run(CIBIL_Score=700), 'S01') == 'passed'


def test_s02_self_employed_below_three_years():
    r = run(Employment_Type='SENP', Work_Experience=2)
    assert r['outcome'] == 'REVIEW' and 'S02' in r['fired_rules']


def test_s02_passes_at_minimum():
    assert status(run(Employment_Type='SENP', Work_Experience=3), 'S02') == 'passed'


def test_s03_borderline_foir_goes_to_review():
    r = run(Existing_EMI=67_000)                  # FOIR ~0.62 against a 0.65 limit
    assert r['facts']['foir'] == pytest.approx(0.6202, abs=1e-3)
    assert r['outcome'] == 'REVIEW' and r['fired_rules'] == ['S03']


def test_s03_comfortable_foir_not_flagged():
    assert status(run(Existing_EMI=0), 'S03') == 'passed'


def test_s04_missing_key_data_goes_to_review():
    r = run(CIBIL_Score=None)
    assert r['outcome'] == 'REVIEW' and 'S04' in r['fired_rules'] and r['facts']['missing_fields'] == ['cibil_score']
    r = run(Collateral_Value=None)                # secured product without a valuation
    assert 'S04' in r['fired_rules'] and 'collateral_value' in r['facts']['missing_fields']


def test_s04_complete_application_not_flagged():
    assert status(run(), 'S04') == 'passed'
    assert status(run(**PERSONAL), 'S04') == 'passed'          # unsecured: collateral not needed


# ---------- forward chaining, precedence, policy file ----------
def test_forward_chaining_derives_facts_in_dependency_order():
    r = run()
    f, trace = r['facts'], r['trace']
    rate = 0.085 / 12
    g = (1 + rate) ** 240
    assert f['proposed_emi'] == pytest.approx(3_000_000 * rate * g / (g - 1))
    assert f['foir'] == pytest.approx(f['proposed_emi'] / 150_000)
    assert f['age_at_maturity'] == 55 and f['ltv'] == pytest.approx(0.6) and f['ltv_cap'] == 0.90
    for later, earlier in [('proposed_emi', 'interest_rate'), ('foir', 'proposed_emi'), ('foir', 'total_income'),
                           ('foir_borderline', 'foir_limit'), ('missing_key_data', 'missing_fields')]:
        assert trace.index(later) > trace.index(earlier)


def test_missing_input_stops_dependent_derivations():
    f = run(Existing_EMI=None)['facts']
    assert f.get('foir') is None and f['proposed_emi'] is not None


def test_hard_beats_soft_and_reasons_list_hard_first():
    r = run(CIBIL_Score=-1, Age=20, Work_Experience=1)
    assert r['outcome'] == 'REJECT' and r['fired_rules'][0] == 'R01' and 'S01' in r['fired_rules']


def test_every_rule_is_recorded_for_audit():
    ids = {e['rule_id'] for e in run()['evaluations']}
    assert ids == {r['id'] for r in load_policy('v1')['rules']}


def test_policy_file_schema():
    policy = load_policy('v1')
    rules = load_rules(policy)
    assert {r.id for r in rules if r.type == 'HARD'} == {f'R0{i}' for i in range(1, 8)}
    for r in rules:
        assert r.rationale and r.source and r.condition.startswith(r.fact)
        expected = f'{r.fact} {r.op} {r.threshold_fact if r.threshold_fact else str(r.threshold).lower()}'
        assert r.condition.startswith(expected), (r.condition, expected)


# ---------- malformed input: never an exception ----------
BAD_VALUES = [None, '', '   ', 'abc', -1e9, 1e15, [], {}, object(), float('nan'), float('inf'), True]


@pytest.mark.parametrize('field', [f for f in contract.INPUT_FIELDS])
def test_malformed_fields_are_handled_without_exceptions(field):
    for bad in BAD_VALUES:
        r = engine.evaluate({**GOOD, field: bad})
        assert r['outcome'] in {'REJECT', 'REVIEW', 'PASS'}
        if r['fired_rules'] == ['INPUT']:
            assert all(x.startswith('invalid input: ') for x in r['reasons'])


@pytest.mark.parametrize('field', [n for n, f in contract.FIELDS.items() if f.required])
def test_required_field_missing_gives_graceful_reject(field):
    r = engine.evaluate({k: v for k, v in GOOD.items() if k != field})
    assert r['outcome'] == 'REJECT' and r['fired_rules'] == ['INPUT'] and field in r['invalid_fields']


@pytest.mark.parametrize('application', [None, [], 'text', 42, {'Age': [1, 2]}, {}])
def test_non_mapping_or_empty_input(application):
    r = engine.evaluate(application)
    assert r['outcome'] == 'REJECT' and r['reasons'][0].startswith('invalid input: ')


def test_out_of_range_reports_field():
    r = run(Age=999)
    assert r['outcome'] == 'REJECT' and r['invalid_fields'] == ['Age']
    assert r['reasons'] == ['invalid input: Age: 999 outside the valid range [18, 75] years']


def test_live_home_loan_tenure_is_not_rescaled():
    """A genuine 24-month home loan must stay 24 months (the years->months repair is historical-only)."""
    r = run(Loan_Tenure=24, Loan_Amount=1_000_000)
    assert r['facts']['loan_tenure'] == 24
    out = preprocess.transform_applicant({**GOOD, 'Loan_Tenure': 24, 'Loan_Amount': 1_000_000})
    assert out.shape[0] == 1


# ---------- pipeline: rules before ML ----------
PIPE = pipeline.DecisionPipeline(persist=False)


class _NoML(pipeline.DecisionPipeline):
    def _ml(self, application):
        raise AssertionError('ML layer must not be called after a HARD rule or invalid input')


def test_hard_reject_never_calls_ml():
    p = _NoML(persist=False)
    for changes in ({'Age': 20, 'Work_Experience': 1}, {'Applicant_ID': 'FRAUD0001'}, {'Age': 999}):
        d = p.decide({**GOOD, **changes})
        assert d['decision'] == 'Rejected' and d['tree_path'] is None and d['model_prediction'] is None and d['source'] == 'RULE'


def test_soft_rule_routes_to_human_review_with_model_recommendation():
    d = PIPE.decide({**GOOD, 'CIBIL_Score': -1})
    assert d['decision'] == 'Human Review' and 'S01' in d['reason'] and 'Model recommendation' in d['reason']


def test_strong_applicant_approved_with_traceable_reason():
    d = PIPE.decide(GOOD)
    assert d['decision'] == 'Approved' and 0 < d['confidence'] < 1
    assert d['reason'].startswith('Approved') and 'CIBIL' in d['reason'] and d['tree_path']


def test_rule_vs_model_conflict_hard_rule_always_wins():
    """Every test-split applicant the tree would APPROVE but a HARD rule rejects must end as Rejected."""
    clean = pd.read_parquet(preprocess.processed_dir() / 'clean.parquet')
    test_rows = clean[clean['split'] == 'test'].reset_index(drop=True)
    X = pd.read_parquet(preprocess.processed_dir() / 'test.parquet').set_index('Loan_ID').loc[test_rows['Loan_ID']]
    model_pred = tree.load_model()['model'].predict(X.drop(columns=['target']))
    p = _NoML(persist=False)
    conflicts = 0
    for row, pred in zip(test_rows.to_dict('records'), model_pred):
        app = {k: v for k, v in row.items() if k in contract.INPUT_FIELDS and not pd.isna(v)}
        rule = engine.evaluate(app)
        hard = [x for x in rule['fired_rules'] if x.startswith('R')]
        if pred == 1 and hard:
            conflicts += 1
            assert p.decide(app)['decision'] == 'Rejected'
    assert conflicts > 50, conflicts          # the scenario genuinely occurs in the data
