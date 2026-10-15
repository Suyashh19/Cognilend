import numpy as np
import pytest

from cognilend import config
from cognilend.data import loaders, synthetic

CFG = config.load('synthetic')
D = CFG['defects']


@pytest.fixture(scope='module')
def raw():
    return loaders.load_synthetic_raw()


@pytest.fixture(scope='module')
def unique(raw):
    return raw.drop_duplicates().reset_index(drop=True)


@pytest.fixture(scope='module')
def clean():
    return synthetic.generate(return_clean=True)[1]


def canonical(series, column):
    """Map raw spellings back to canonical keys using the generator's label tables."""
    lab = CFG['labels'][column]
    lookup = {v: k for k, v in lab['canonical'].items()}
    lookup.update({v: k for k, vs in lab['variants'].items() for v in vs})
    return series.str.strip().map(lookup)


# ---------- determinism ----------
def test_generator_is_deterministic(tmp_path):
    a, b = synthetic.write(tmp_path / 'a.csv'), synthetic.write(tmp_path / 'b.csv')
    assert synthetic.sha256(a) == synthetic.sha256(b)


def test_committed_file_matches_generator(tmp_path):
    fresh = synthetic.write(tmp_path / 'fresh.csv')
    committed = config.ROOT / config.load('settings')['paths']['synthetic_raw']
    assert synthetic.sha256(fresh) == synthetic.sha256(committed)


def test_different_seed_gives_different_file(tmp_path):
    assert synthetic.sha256(synthetic.write(tmp_path / 'a.csv')) != \
        synthetic.sha256(synthetic.write(tmp_path / 'b.csv', seed=7))


# ---------- shape and label ----------
def test_shape_and_columns(raw):
    assert raw.shape == (CFG['n_rows'], 17)
    assert list(raw.columns) == synthetic.COLUMNS


def test_approval_rate(unique):
    labelled = unique['Loan_Status'].dropna()
    assert set(labelled) == {'Approved', 'Rejected'}
    assert (labelled == 'Approved').mean() == pytest.approx(CFG['approval_rate'], abs=0.005)


def test_label_is_not_a_function_of_policy_rules(clean):
    approved = clean['Loan_Status'] == 'Approved'
    violates = ((clean['CIBIL_Score'] != -1) & (clean['CIBIL_Score'] < 650)) | (clean['Age'] < 21)
    # rule violators are sometimes approved, compliant applicants are sometimes rejected
    assert 0.05 < approved[violates].mean() < 0.95
    assert 0.05 < (~approved[~violates]).mean() < 0.95
    # the label follows the latent repayment score
    hi = clean['_score'] > clean['_score'].median()
    assert approved[hi].mean() > approved[~hi].mean() + 0.3


# ---------- every documented defect type is present ----------
def test_exact_duplicates(raw):
    assert raw.duplicated().sum() == CFG['n_duplicates']


def test_unlabelled_rows(unique):
    assert unique['Loan_Status'].isna().sum() == CFG['n_unlabelled']


@pytest.mark.parametrize('col', synthetic.TEXT_CATEGORICALS)
def test_whitespace_and_spelling_variants(raw, col):
    s = raw[col].dropna()
    assert (s != s.str.strip()).sum() > 0, 'no whitespace defects'
    canon = set(CFG['labels'][col]['canonical'].values())
    assert (~s.str.strip().isin(canon)).sum() > 0, 'no spelling variants'
    assert canonical(s, col).notna().all(), 'a value outside the documented spellings'


def test_amounts_as_indian_grouped_text(unique):
    s = unique['Loan_Amount'].dropna().astype(str)
    grouped = s.str.contains(',')
    assert grouped.sum() == D['amount_as_text']
    assert s.str.startswith('Rs. ').sum() == D['amount_with_rs_prefix']
    assert s[grouped].str.fullmatch(r'(Rs\. )?\d{1,2}(,\d{2})*,\d{3}').all()


def test_dependents_three_plus(raw):
    assert (raw['Dependents'] == '3+').sum() > 0


def test_impossible_ages(unique):
    age = unique['Age'].dropna()
    bad = age[~age.between(18, 75)]
    assert len(bad) == D['impossible_age']
    assert set(bad) <= set(D['impossible_age_values']) and 999 in set(bad)


def test_negative_and_zero_income(unique):
    assert (unique['Monthly_Income'] < 0).sum() == D['negative_income']
    assert (unique['Monthly_Income'] == 0).sum() == D['zero_income']


def test_invalid_cibil_and_ntc_sentinel(unique):
    c = unique['CIBIL_Score'].dropna()
    invalid = c[(c != -1) & ~c.between(300, 900)]
    assert len(invalid) == D['invalid_cibil'] and 9999 in set(invalid)
    assert (c == -1).sum() > 0     # -1 is the NTC convention, not an error


def test_impossible_experience(unique):
    ok_age = unique['Age'].between(18, 75)
    exp, age = unique.loc[ok_age, 'Work_Experience'], unique.loc[ok_age, 'Age']
    assert ((exp < 0) | (exp > age - 18)).sum() == D['impossible_experience']


def test_home_tenure_keyed_in_years(unique):
    home = canonical(unique['Loan_Type'].dropna(), 'Loan_Type') == 'Home'
    tenure = unique.loc[home[home].index, 'Loan_Tenure']
    assert (tenure <= 30).sum() == D['home_tenure_in_years']
    assert set(tenure[tenure <= 30]) <= {10, 15, 20, 25, 30}


@pytest.mark.parametrize('col,rate', D['missing_rate'].items())
def test_random_missing_values(unique, col, rate):
    observed = unique[col].isna().mean()
    assert observed == pytest.approx(rate, rel=0.35), f'{col}: {observed:.4f} vs {rate}'


def test_ten_columns_have_random_missing_values():
    assert len(D['missing_rate']) == 10


def test_structural_missing(unique, clean):
    assert unique['Coapplicant_Income'].isna().mean() > 0.5
    assert clean.loc[clean['Loan_Type'] == 'Personal', 'Collateral_Value'].isna().all()
    assert clean.loc[clean['Loan_Type'].isin(['Home', 'Vehicle']), 'Collateral_Value'].notna().all()


def test_injected_group_bias_is_visible_in_labels(clean):
    rate = (clean['Loan_Status'] == 'Approved').groupby(clean['Gender']).mean()
    assert rate['Female'] < rate['Male']
    assert np.isclose(CFG['latent']['group_bias']['Male'], 0.0)
