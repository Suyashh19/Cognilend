"""Scenario tests for the hybrid decision engine: every rejection / acceptance / review path and its boundaries.

Run:  pytest -q test_scenarios.py
"""
import numpy as np
import pandas as pd
import pytest

import model_training.loan_engine as le
from model_training.train import make_model

GOOD = dict(Loan_ID='T', Age=35, Gender='Male', Marital_Status='Married', Dependents='1',
            Employment_Type='Salaried', Work_Experience=10, Monthly_Income=150_000, Coapplicant_Income=None,
            Existing_EMI=0, CIBIL_Score=800, Loan_Type='Home Loan', Loan_Amount=3_000_000,
            Loan_Tenure=240, Collateral_Value=5_000_000, Property_Area='Urban')


@pytest.fixture(scope='module')
def engine():
    df = le.prepare_training_data(pd.read_csv('loan_applications_raw.csv'))
    return le.LoanDecisionEngine(make_model()).fit(df, df['target'])


def run(engine, **changes):
    out = engine.decide(pd.DataFrame([{**GOOD, **changes}]))
    return out.iloc[0]


def features(engine, **changes):
    return engine.featurize(pd.DataFrame([{**GOOD, **changes}])).iloc[0]


# ---------- the happy path ----------
def test_strong_applicant_is_approved(engine):
    r = run(engine)
    assert r.decision == 'APPROVE' and r.rules_violated == ''
    assert r.p_approve > 0.8


# ---------- R1: minimum age ----------
def test_r1_underage_rejected(engine):
    r = run(engine, Age=20, Work_Experience=1)
    assert r.decision == 'REJECT' and 'R1' in r.rules_violated


def test_r1_boundary_21_passes(engine):
    assert 'R1' not in run(engine, Age=21, Work_Experience=2).rules_violated


# ---------- R2: age at maturity ----------
def test_r2_salaried_beyond_60_rejected(engine):
    r = run(engine, Age=45, Loan_Tenure=240)            # matures at 65 > 60
    assert r.decision == 'REJECT' and 'R2' in r.rules_violated


def test_r2_self_employed_allowed_to_65(engine):
    assert 'R2' not in run(engine, Age=45, Loan_Tenure=240, Employment_Type='SEP').rules_violated   # exactly 65
    assert 'R2' in run(engine, Age=46, Loan_Tenure=240, Employment_Type='SEP').rules_violated


# ---------- R3: CIBIL ----------
@pytest.mark.parametrize('score,violates', [(649, True), (650, False), (900, False)])
def test_r3_cibil_threshold(engine, score, violates):
    assert ('R3' in run(engine, CIBIL_Score=score).rules_violated) == violates


def test_new_to_credit_is_not_rejected_but_reviewed(engine):
    r = run(engine, CIBIL_Score=-1)
    assert 'R3' not in r.rules_violated
    assert r.decision == 'MANUAL_REVIEW' and 'New-to-credit' in r.reasons


# ---------- R4: FOIR slabs ----------
def test_r4_high_foir_rejected(engine):
    r = run(engine, Monthly_Income=40_000, Existing_EMI=15_000, Loan_Type='Personal Loan',
            Loan_Amount=500_000, Loan_Tenure=36, Collateral_Value=None)
    assert r.decision == 'REJECT' and 'R4' in r.rules_violated


@pytest.mark.parametrize('income,limit', [(49_999, 0.50), (50_000, 0.55), (100_000, 0.55), (100_001, 0.65)])
def test_r4_foir_limit_slabs(engine, income, limit):
    assert features(engine, Monthly_Income=income).foir_limit == limit


# ---------- R5: RBI LTV caps for housing loans ----------
@pytest.mark.parametrize('amount,collateral,violates', [
    (2_500_000, 2_700_000, True),     # 92.6% > 90% (<= 30 L slab)
    (2_500_000, 2_800_000, False),    # 89.3%
    (5_000_000, 6_000_000, True),     # 83.3% > 80% (30-75 L slab)
    (9_000_000, 11_500_000, True),    # 78.3% > 75% (> 75 L slab)
    (9_000_000, 12_500_000, False),   # 72%
])
def test_r5_ltv_slabs(engine, amount, collateral, violates):
    r = run(engine, Monthly_Income=400_000, Loan_Amount=amount, Collateral_Value=collateral)
    assert ('R5' in r.rules_violated) == violates


def test_r5_does_not_apply_to_vehicle_loans(engine):
    r = run(engine, Loan_Type='Car Loan', Loan_Amount=900_000, Collateral_Value=950_000, Loan_Tenure=60)
    assert 'R5' not in r.rules_violated


# ---------- R6: minimum income ----------
def test_r6_low_income_rejected(engine):
    r = run(engine, Monthly_Income=12_000, Loan_Type='Personal Loan', Loan_Amount=50_000,
            Loan_Tenure=24, Collateral_Value=None)
    assert r.decision == 'REJECT' and 'R6' in r.rules_violated


def test_r6_coapplicant_income_is_clubbed(engine):
    r = run(engine, Monthly_Income=12_000, Coapplicant_Income=8_000, Loan_Type='Personal Loan',
            Loan_Amount=50_000, Loan_Tenure=24, Collateral_Value=None)
    assert 'R6' not in r.rules_violated


# ---------- R7: experience / vintage ----------
def test_r7_self_employed_needs_three_years(engine):
    assert 'R7' in run(engine, Employment_Type='SENP', Work_Experience=2).rules_violated
    assert 'R7' not in run(engine, Employment_Type='SENP', Work_Experience=3).rules_violated


def test_r7_salaried_needs_one_year(engine):
    assert 'R7' in run(engine, Work_Experience=0).rules_violated


# ---------- several violations: all are reported ----------
def test_multiple_violations_all_listed(engine):
    r = run(engine, Age=20, CIBIL_Score=600, Monthly_Income=12_000, Work_Experience=0,
            Loan_Type='Personal Loan', Loan_Amount=100_000, Loan_Tenure=24, Collateral_Value=None)
    assert r.decision == 'REJECT'
    for rule in ['R1', 'R3', 'R6', 'R7']:
        assert rule in r.rules_violated and rule + ':' in r.reasons


# ---------- data quality: messy, missing and invalid input ----------
def test_messy_input_is_parsed_like_clean_input(engine):
    messy = run(engine, Gender=' m ', Employment_Type='SERVICE', Loan_Type=' HL',
                Loan_Amount='Rs. 30,00,000', Property_Area='urban ', Dependents='1')
    clean = run(engine)
    assert messy.decision == clean.decision and messy.p_approve == pytest.approx(clean.p_approve)


@pytest.mark.parametrize('field,value,phrase', [
    ('CIBIL_Score', None, 'CIBIL score missing'),
    ('CIBIL_Score', 9999, 'CIBIL score missing'),        # out of range -> treated as missing
    ('Existing_EMI', None, 'Existing EMI not on record'),
    ('Monthly_Income', 0, 'Income missing'),
    ('Collateral_Value', None, 'Collateral value not on record'),
    ('Age', 999, 'Age missing or invalid'),
    ('Loan_Type', 'Gold Loan', 'Loan type missing or invalid'),
])
def test_uncertain_data_goes_to_manual_review(engine, field, value, phrase):
    r = run(engine, **{field: value})
    assert r.decision == 'MANUAL_REVIEW' and phrase in r.reasons


def test_policy_violation_beats_review_trigger(engine):
    r = run(engine, CIBIL_Score=-1, Age=20, Work_Experience=1)   # NTC (review) but under-age (reject)
    assert r.decision == 'REJECT'


def test_sign_error_in_income_is_recovered_not_reviewed(engine):
    assert run(engine, Monthly_Income=-150_000).decision == run(engine).decision


def test_home_loan_tenure_in_years_is_rescaled(engine):
    assert features(engine, Loan_Tenure=20).Loan_Tenure == 240


def test_large_exposure_goes_to_committee(engine):
    r = run(engine, Monthly_Income=1_500_000, Loan_Amount=25_000_000, Collateral_Value=40_000_000)
    assert r.decision == 'MANUAL_REVIEW' and 'Large exposure' in r.reasons


# ---------- model-driven outcomes ----------
def test_weak_but_policy_compliant_applicant_not_auto_approved(engine):
    r = run(engine, CIBIL_Score=655, Monthly_Income=30_000, Existing_EMI=5_000, Work_Experience=1,
            Loan_Type='Business Loan', Loan_Amount=250_000, Loan_Tenure=36, Collateral_Value=None,
            Property_Area='Rural', Dependents='3+')
    assert r.rules_violated == ''
    assert r.decision in ('REJECT', 'MANUAL_REVIEW')
    assert r.reasons     # always explained


def test_every_decision_has_reasons(engine):
    df = pd.read_csv('loan_applications_raw.csv').drop_duplicates().head(300)
    out = engine.decide(df)
    assert (out['reasons'].str.len() > 0).all()


# ---------- fairness: protected attributes cannot change the outcome ----------
@pytest.mark.parametrize('gender', ['Female', 'Transgender', None])
@pytest.mark.parametrize('marital', ['Single', 'Widowed', None])
def test_gender_and_marital_status_do_not_change_score(engine, gender, marital):
    base = run(engine, Dependents='0')
    other = run(engine, Gender=gender, Marital_Status=marital, Dependents='0')
    assert other.p_approve == pytest.approx(base.p_approve) and other.decision == base.decision


# ---------- monotonicity: better credit facts never lower the score ----------
@pytest.mark.parametrize('field,values', [
    ('CIBIL_Score', [660, 700, 750, 800, 850]),
    ('Monthly_Income', [60_000, 80_000, 120_000, 200_000, 400_000]),
    ('Existing_EMI', [40_000, 20_000, 10_000, 0]),
])
def test_monotone_in_key_credit_factors(engine, field, values):
    p = [run(engine, Loan_Amount=2_000_000, **{field: v}).p_approve for v in values]
    assert all(b >= a - 1e-9 for a, b in zip(p, p[1:])), p
