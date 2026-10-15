import numpy as np
import pandas as pd
import pytest

from cognilend import config
from cognilend.data import contract, loaders, preprocess

P = config.load('settings')['preprocess']
APPLICANT = dict(Age=35, Gender='f', Marital_Status='Married', Dependents='3+', Employment_Type='Service',
                 Work_Experience=10, Monthly_Income=85000, Existing_EMI=5000, CIBIL_Score=760, Loan_Type='HL',
                 Loan_Amount='Rs. 30,00,000', Loan_Tenure=240, Collateral_Value=4500000, Property_Area='urban')


@pytest.fixture(scope='module')
def built():
    return preprocess.build()


@pytest.fixture(scope='module')
def saved():
    if not preprocess.preprocessor_path().exists() or not (preprocess.processed_dir() / 'train.parquet').exists():
        preprocess.run()
    return preprocess.load_preprocessor()


# ---------- cleaning ----------
def test_cleaning_removes_duplicates_and_unlabelled(built):
    df = built['clean']
    assert len(df) == 10000 - 135 - 18
    assert df['Loan_ID'].is_unique and df['Loan_Status'].notna().all()


def test_cleaning_fixes_documented_defects(built):
    df = built['clean']
    for c in preprocess.CATEGORICALS:
        assert set(df[c].dropna()) <= set(contract.FIELDS[c].allowed)
    assert df['Loan_Amount'].dropna().map(type).eq(float).all()
    assert df['Age'].dropna().between(18, 75).all()
    assert (df['Monthly_Income'].dropna() > 0).all()
    c = df['CIBIL_Score'].dropna()
    assert (c.between(300, 900) | (c == -1)).all() and (c == -1).any()
    assert not ((df['Loan_Type'] == 'Home') & (df['Loan_Tenure'] <= 30)).any()
    assert (df['Work_Experience'].dropna() >= 0).all()


def test_sign_error_recovered_not_dropped():
    raw = pd.DataFrame([{**APPLICANT, 'Monthly_Income': -85000, 'Loan_Status': 'Approved', 'Loan_ID': 'X1'}])
    assert preprocess.clean(raw)['Monthly_Income'].iloc[0] == 85000


# ---------- split ----------
def test_split_sizes_and_disjoint(built):
    parts = built['parts']
    n = len(built['clean'])
    assert len(parts['train']) == pytest.approx(0.70 * n, abs=2)
    assert len(parts['val']) == pytest.approx(0.15 * n, abs=2)
    ids = [set(p['Loan_ID']) for p in parts.values()]
    assert not (ids[0] & ids[1]) and not (ids[0] & ids[2]) and not (ids[1] & ids[2])
    assert sum(map(len, ids)) == n


@pytest.mark.parametrize('part', ['val', 'test'])
def test_class_distribution_within_one_point(built, part):
    original = built['clean'][preprocess.TARGET].mean()
    assert abs(built['y'][part].mean() - original) <= 0.01


# ---------- no leakage ----------
def test_fitted_statistics_come_from_train_only(built):
    train = built['parts']['train']
    pre = built['preprocessor']
    bf = pre.named_steps['features']
    for c, v in bf.medians_.items():
        assert v == train[c].median()
    scored = train['CIBIL_Score'][train['CIBIL_Score'] != -1]
    assert bf.cibil_median_ == scored.median()
    feats = bf.transform(train)[P['continuous']]
    num = pre.named_steps['columns'].named_transformers_['num']
    q1, q3 = feats.quantile(0.25), feats.quantile(0.75)
    iqr = q3 - q1
    np.testing.assert_allclose(num.named_steps['cap'].lower_, (q1 - 3.0 * iqr).to_numpy())
    np.testing.assert_allclose(num.named_steps['cap'].upper_, (q3 + 3.0 * iqr).to_numpy())
    capped = feats.clip(q1 - 3.0 * iqr, q3 + 3.0 * iqr, axis=1)
    np.testing.assert_allclose(num.named_steps['scale'].data_min_, capped.min().to_numpy())
    np.testing.assert_allclose(num.named_steps['scale'].data_max_, capped.max().to_numpy())


def test_full_data_statistics_would_differ(built):
    """Guards the test above: if train and full-data statistics were equal, it would prove nothing."""
    bf = built['preprocessor'].named_steps['features']
    full = built['clean']
    assert any(bf.medians_[c] != full[c].median() for c in bf.medians_) or \
        bf.cibil_median_ != full.loc[full['CIBIL_Score'] != -1, 'CIBIL_Score'].median() or \
        built['preprocessor'].named_steps['columns'].named_transformers_['num'].named_steps['scale'].data_max_.tolist() \
        != preprocess.build_preprocessor().fit(full).named_steps['columns'].named_transformers_['num'].named_steps[
            'scale'].data_max_.tolist()


def test_continuous_scaled_codes_not_scaled(built):
    X = built['X']['train']
    assert X[P['continuous']].min().min() >= 0 and X[P['continuous']].max().max() <= 1
    assert set(np.unique(X['dependents'])) <= {0, 1, 2, 3}
    for c in P['binary'] + [c for c in X if c.startswith(('Employment_Type_', 'Loan_Type_'))]:
        assert set(np.unique(X[c])) <= {0, 1}


def test_no_missing_values_after_transform(built):
    for X in built['X'].values():
        assert not X.isna().any().any()


# ---------- protected attributes ----------
def test_no_protected_attribute_in_feature_matrix(built, saved):
    banned = ('Gender', 'Marital_Status', 'Age', 'Age_Band', 'Property_Area', 'age_at_maturity')
    for names in (built['feature_names'], saved['feature_names']):
        assert not [c for c in names if c.startswith(banned)]
    for k in ('train', 'val', 'test'):
        cols = pd.read_parquet(preprocess.processed_dir() / f'{k}.parquet').columns
        assert not [c for c in cols if c.startswith(banned)]


def test_protected_side_table_keyed_by_loan_id(saved):
    side = pd.read_parquet(preprocess.processed_dir() / 'protected.parquet')
    assert {'Loan_ID', 'Gender', 'Marital_Status', 'Age_Band', 'split'} <= set(side.columns)
    assert side['Loan_ID'].is_unique and len(side) == 9847


# ---------- SMOTE ----------
def test_smote_changes_train_counts_only(built):
    from imblearn.pipeline import Pipeline
    from sklearn.tree import DecisionTreeClassifier
    X, y = built['X'], built['y']
    sampler = preprocess.make_resampler(built['feature_names'])
    Xr, yr = sampler.fit_resample(X['train'], y['train'])
    assert len(yr) > len(y['train'])
    assert pd.Series(yr).value_counts().nunique() == 1          # balanced
    pipe = Pipeline([('smote', preprocess.make_resampler(built['feature_names'])),
                     ('clf', DecisionTreeClassifier(max_depth=2, random_state=42))]).fit(X['train'], y['train'])
    for k in ('train', 'val', 'test'):
        assert len(pipe.predict(X[k])) == len(X[k])               # sampler is skipped at predict time


def test_smote_counts_logged(saved):
    c = saved['smote_train_counts']
    assert c['before'] != c['after']
    assert c['after'][0] == c['after'][1] == max(c['before'].values())


# ---------- saved artefact and live transform ----------
def test_saved_preprocessor_has_version(saved):
    assert saved['version'] == P['version']
    assert saved['data_sha256'] and saved['feature_names']


def test_transform_applicant_single_dict(saved):
    out = preprocess.transform_applicant(APPLICANT, saved)
    assert list(out.columns) == saved['feature_names'] and out.shape == (1, len(saved['feature_names']))
    assert np.isfinite(out.to_numpy(dtype=float)).all()
    assert out['Loan_Type_Home'].item() == 1 and out['Employment_Type_Salaried'].item() == 1
    assert out['dependents'].item() == 3


def test_transform_applicant_canonical_and_raw_spellings_agree(saved):
    canonical = {**APPLICANT, 'Gender': 'Female', 'Employment_Type': 'Salaried', 'Loan_Type': 'Home',
                 'Loan_Amount': 3_000_000, 'Dependents': 3, 'Property_Area': 'Urban'}
    pd.testing.assert_frame_equal(preprocess.transform_applicant(APPLICANT, saved),
                                  preprocess.transform_applicant(canonical, saved))


def test_transform_applicant_ignores_protected_inputs(saved):
    a = preprocess.transform_applicant(APPLICANT, saved)
    b = preprocess.transform_applicant({**APPLICANT, 'Gender': 'Male', 'Marital_Status': 'Single'}, saved)
    pd.testing.assert_frame_equal(a, b)


@pytest.mark.parametrize('bad', [{'Age': 999}, {'CIBIL_Score': 9999}, {'Loan_Type': 'Gold Loan'},
                                 {'Monthly_Income': None}])
def test_transform_applicant_rejects_invalid_input(saved, bad):
    with pytest.raises(preprocess.ContractError) as e:
        preprocess.transform_applicant({**APPLICANT, **bad}, saved)
    assert e.value.errors


def test_transform_applicant_matches_batch_transform(built, saved):
    row = loaders.load_synthetic_raw().drop_duplicates().iloc[[0]]
    clean_row = preprocess.clean(row)
    batch = saved['preprocessor'].transform(clean_row)[saved['feature_names']]
    rec = {k: v for k, v in clean_row.iloc[0].to_dict().items() if k in contract.INPUT_FIELDS and pd.notna(v)}
    live = preprocess.transform_applicant(rec, saved)
    np.testing.assert_allclose(live.to_numpy(dtype=float), batch.to_numpy(dtype=float))


# ---------- secondary benchmark pipeline (Loan.csv) ----------
def test_generic_pipeline_on_loan_csv_shaped_frame():
    rng = np.random.default_rng(42)
    n = 300
    df = pd.DataFrame({'ID': range(n), 'loan_amount': rng.integers(1, 9, n) * 1e5,
                       'rate_of_interest': rng.uniform(3, 5, n), 'Credit_Score': rng.integers(500, 900, n).astype(float),
                       'Region': rng.choice(['north', 'south'], n), 'Status': rng.integers(0, 2, n)})
    df.loc[:10, 'Credit_Score'] = np.nan
    X, y, num, cat = preprocess.prepare_loan_csv(df)
    assert 'rate_of_interest' not in X and 'ID' not in X and 'Status' not in X
    out = preprocess.build_generic_preprocessor(num, cat).fit(X.iloc[:200]).transform(X.iloc[200:])
    assert not out.isna().any().any() and out.shape[0] == 100
