import numpy as np
import pandas as pd
import pytest

from cognilend.data import loaders


@pytest.fixture
def toy_loan_csv():
    """Mimics the pattern reported for Loan.csv: status=1 rows are never priced."""
    rng = np.random.default_rng(42)
    n = 400
    status = (rng.random(n) < 0.246).astype(int)
    return pd.DataFrame({
        'loan_amount': rng.integers(100, 500, n) * 1000,
        'rate_of_interest': np.where(status == 1, -1, rng.uniform(3, 5, n)),
        'Interest_rate_spread': np.where(status == 1, np.nan, rng.uniform(0, 1, n)),
        'Credit_Score': rng.integers(500, 900, n),
        'Status': status,
    })


def test_target_investigation_ranks_pricing_fields_first(toy_loan_csv):
    out = loaders.target_investigation(toy_loan_csv)
    assert set(out.head(2)['column']) == {'rate_of_interest', 'Interest_rate_spread'}
    assert out.loc[out['column'] == 'rate_of_interest', 'absent_rate_Status=1'].item() == 1.0
    assert out.loc[out['column'] == 'Credit_Score', 'gap'].item() == 0.0


def test_pricing_explains_target(toy_loan_csv):
    r = loaders.pricing_explains_target(toy_loan_csv)
    assert r['precision'] == 1.0 and r['recall'] == 1.0


def test_missing_loan_csv_gives_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match='Loan.csv has not been supplied'):
        loaders.load_loan_csv(tmp_path / 'Loan.csv')
