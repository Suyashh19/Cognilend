import numpy as np
import pandas as pd
import pytest

from cognilend.data import contract

CLEAN = dict(Loan_ID='LN2025000001', Age=35, Gender='Female', Marital_Status='Married', Dependents=1,
             Employment_Type='Salaried', Work_Experience=10, Monthly_Income=85000.0, Coapplicant_Income=None,
             Existing_EMI=5000.0, CIBIL_Score=760, Loan_Type='Home', Loan_Amount=3_000_000.0, Loan_Tenure=240,
             Collateral_Value=4_500_000.0, Property_Area='Urban')


def test_clean_row_is_accepted():
    assert contract.validate(CLEAN) == []
    assert contract.is_valid(CLEAN)


def test_age_999_is_rejected():
    errors = contract.validate({**CLEAN, 'Age': 999})
    assert len(errors) == 1 and errors[0].startswith('Age:') and 'outside the valid range' in errors[0]


@pytest.mark.parametrize('changes,field', [
    ({'Age': -30}, 'Age'),
    ({'Age': 35.5}, 'Age'),                              # whole years only
    ({'CIBIL_Score': 9999}, 'CIBIL_Score'),
    ({'CIBIL_Score': 100}, 'CIBIL_Score'),
    ({'Monthly_Income': -150000}, 'Monthly_Income'),
    ({'Monthly_Income': 0}, 'Monthly_Income'),
    ({'Loan_Amount': 'Rs. 27,90,000'}, 'Loan_Amount'),   # raw text is cleaned before validation, not here
    ({'Loan_Type': 'HL'}, 'Loan_Type'),
    ({'Gender': 'm'}, 'Gender'),
    ({'Dependents': '3+'}, 'Dependents'),
    ({'Loan_Tenure': 20.5}, 'Loan_Tenure'),
    ({'Work_Experience': 30}, 'Work_Experience'),         # 30 years at age 35 is impossible
    ({'Monthly_Income': None}, 'Monthly_Income'),        # required
    ({'Employment_Type': ''}, 'Employment_Type'),        # required, blank
])
def test_invalid_values_are_rejected(changes, field):
    errors = contract.validate({**CLEAN, **changes})
    assert any(e.startswith(field) for e in errors), errors


def test_new_to_credit_sentinel_is_valid():
    assert contract.validate({**CLEAN, 'CIBIL_Score': -1}) == []


def test_optional_fields_may_be_missing():
    record = {k: v for k, v in CLEAN.items() if contract.FIELDS[k].required}
    assert contract.validate(record) == []


def test_unknown_field_is_reported():
    assert any('unknown field' in e for e in contract.validate({**CLEAN, 'Religion': 'X'}))


@pytest.mark.parametrize('bad', [{'Age': object()}, {'Age': [1, 2]}, {'Age': float('inf')},
                                 {'Monthly_Income': True}, {'CIBIL_Score': 'abc'}])
def test_never_crashes_on_garbage(bad):
    errors = contract.validate({**CLEAN, **bad})
    assert isinstance(errors, list) and errors


def test_empty_record_lists_all_required_fields():
    errors = contract.validate({})
    required = [n for n, f in contract.FIELDS.items() if f.required]
    assert len(errors) == len(required)


def test_numpy_scalars_are_accepted():
    assert contract.validate({**CLEAN, 'Age': np.int64(40), 'Monthly_Income': np.float64(90000)}) == []


def test_protected_fields_are_excluded_from_model():
    assert set(contract.PROTECTED) == {'Gender', 'Marital_Status', 'Age_Band'}
    assert not set(contract.PROTECTED) & set(contract.MODEL_ELIGIBLE)
    assert 'Age' not in contract.MODEL_ELIGIBLE and 'Loan_Status' not in contract.MODEL_ELIGIBLE


def test_every_field_documents_dtype_unit_and_flags():
    for f in contract.FIELDS.values():
        assert f.dtype in {'str', 'int', 'float', 'category'}
        if f.dtype in {'int', 'float'}:
            assert f.unit and f.min is not None and f.max is not None
        if f.dtype == 'category':
            assert f.allowed


@pytest.mark.parametrize('age,band', [(21, '<=25'), (25, '<=25'), (26, '26-35'), (60, '>55'), (None, None)])
def test_age_band(age, band):
    assert contract.age_band(age) == band


def test_validate_frame():
    out = contract.validate_frame(pd.DataFrame([CLEAN, {**CLEAN, 'Age': 999}]))
    assert out.iloc[0] == [] and len(out.iloc[1]) == 1
