"""Cleaning, imputation and encoding fitted on the training split only, saved with a version.

    python -m cognilend.data.preprocess
        -> data/processed/{train,val,test}.parquet, clean.parquet, protected.parquet, split_indices.json
        -> artifacts/encoders/preprocessor_v1.joblib

Order of operations:
  normalise()        stateless: spellings -> canonical, "Rs. 27,90,000" -> 2790000, "3+" -> 3
  repair_invalid()   stateless: sign errors, home tenure keyed in years, impossible values -> NaN
  split()            stratified 70 / 15 / 15, seed 42, BEFORE anything is fitted
  preprocessor       fitted on TRAIN only: BankingFeatures (median/mode imputation + FOIR, LTI, coverage,
                     LTV, age at maturity, NTC flag from real values) -> IQR capping (x3.0) -> MinMax [0,1]
                     on continuous features; ordinal / binary / one-hot columns are not scaled
  SMOTE              make_resampler(): SMOTENC inside an imblearn Pipeline, so it only runs during fit (train)
"""
from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import BaseEstimator, OneToOneFeatureMixin, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler, OneHotEncoder

from cognilend import config
from cognilend.data import contract, loaders, synthetic

CATEGORICALS = ['Gender', 'Marital_Status', 'Employment_Type', 'Loan_Type', 'Property_Area']
NUMERICS = ['Age', 'Dependents', 'Work_Experience', 'Monthly_Income', 'Coapplicant_Income', 'Existing_EMI',
            'CIBIL_Score', 'Loan_Amount', 'Loan_Tenure', 'Collateral_Value']
SIDE_TABLE = ['Loan_ID', 'Gender', 'Marital_Status', 'Age', 'Age_Band', 'Dependents', 'Property_Area']
TARGET = 'target'


class ContractError(ValueError):
    """A live application violates the data contract; .errors lists every violation."""

    def __init__(self, errors: list[str]):
        super().__init__('; '.join(errors))
        self.errors = errors


def _settings() -> dict:
    return config.load('settings')


def _spelling_lookup() -> dict[str, dict[str, str]]:
    """lower-case spelling -> canonical value, from the documented spellings (config/synthetic.yaml labels)."""
    labels = config.load('synthetic')['labels']
    out = {}
    for col, lab in labels.items():
        m = {k.lower(): k for k in lab['canonical']}
        m.update({v.lower(): k for k, v in lab['canonical'].items()})
        m.update({v.lower(): k for k, vs in lab['variants'].items() for v in vs})
        out[col] = m
    out['Loan_Status'] = {'approved': 'Approved', 'rejected': 'Rejected'}
    return out


LOOKUP = _spelling_lookup()


# --------------------------------------------------------------------------------------
# 1. Stateless cleaning
# --------------------------------------------------------------------------------------
def _parse_amount(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float)
    txt = s.astype('string').str.replace(r'(?i)rs\.?|₹|,|\s', '', regex=True)
    return pd.to_numeric(txt, errors='coerce').astype(float)


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Canonical spellings and numeric dtypes. Values that can't be mapped are kept as-is for the contract to report."""
    df = df.copy()
    for c in CATEGORICALS + ['Loan_Status']:
        if c not in df:
            df[c] = np.nan
        s = df[c].astype('string').str.strip()
        s = s.mask(s == '')
        df[c] = s.str.lower().map(LOOKUP[c]).fillna(s).astype(object).where(s.notna(), np.nan)
    if 'Dependents' in df:
        df['Dependents'] = df['Dependents'].astype('string').str.strip().replace('3+', '3')
    for c in NUMERICS:
        df[c] = _parse_amount(df[c]) if c in df else np.nan
    if 'Loan_ID' not in df:
        df['Loan_ID'] = np.nan
    return df


def repair_invalid(df: pd.DataFrame, historical: bool = True) -> pd.DataFrame:
    """Recover unambiguous errors, set impossible values to NaN, fill structural blanks. Stateless, row-wise.

    historical=True applies the repairs that are only justified for the historical file (sign errors, home-loan
    tenure keyed in years). Live applications are validated against the contract instead (historical=False),
    so a genuine 24-month home loan is never rescaled to 288 months.
    """
    p = _settings()['preprocess']
    f = contract.FIELDS
    df = df.copy()
    if historical:
        df.loc[df['Monthly_Income'] < 0, 'Monthly_Income'] *= -1                   # sign error
        years = (df['Loan_Type'] == 'Home') & (df['Loan_Tenure'] <= p['home_tenure_years_max'])
        df.loc[years, 'Loan_Tenure'] *= 12                                          # keyed in years
    for c in NUMERICS:
        lo, hi, special = f[c].min, f[c].max, f[c].special
        bad = df[c].notna() & ~df[c].isin(special) & ~df[c].between(lo, hi)
        df.loc[bad, c] = np.nan
    exp_bad = df['Work_Experience'] > df['Age'] - 18
    df.loc[exp_bad, 'Work_Experience'] = np.nan
    for c in CATEGORICALS + ['Loan_Status']:
        allowed = f[c].allowed
        df[c] = df[c].where(df[c].isin(allowed), np.nan)
    secured = df['Loan_Type'].isin(p['secured_loan_types'])
    df['flag_missing_cibil'] = df['CIBIL_Score'].isna().astype(int)
    df['flag_missing_emi'] = df['Existing_EMI'].isna().astype(int)
    df['flag_missing_income'] = df['Monthly_Income'].isna().astype(int)
    df['flag_missing_collateral'] = (secured & (df['Collateral_Value'].isna() | (df['Collateral_Value'] == 0))).astype(int)
    df['Coapplicant_Income'] = df['Coapplicant_Income'].fillna(0.0)              # blank = no co-applicant
    df.loc[~secured & df['Collateral_Value'].isna(), 'Collateral_Value'] = 0.0      # blank = unsecured
    df['Age_Band'] = [contract.age_band(a) for a in df['Age']]
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    return repair_invalid(normalise(df))


def prepare_dataset(raw: pd.DataFrame) -> pd.DataFrame:
    """Training-table cleaning: exact duplicates and unlabelled rows removed, then clean(), then the target."""
    n0 = len(raw)
    raw = raw.drop_duplicates()
    raw = raw.drop_duplicates(subset='Loan_ID', keep='first')
    df = clean(raw)
    df = df[df['Loan_Status'].notna()].reset_index(drop=True)
    df[TARGET] = (df['Loan_Status'] == 'Approved').astype(int)
    df.attrs['rows_in'], df.attrs['rows_out'] = n0, len(df)
    return df


def split(df: pd.DataFrame, seed: int | None = None) -> dict[str, pd.DataFrame]:
    s = _settings()
    seed = s['seed'] if seed is None else seed
    sp = s['split']
    train, rest = train_test_split(df, train_size=sp['train'], stratify=df[TARGET], random_state=seed)
    val, test = train_test_split(rest, test_size=sp['test'] / (sp['val'] + sp['test']),
                                 stratify=rest[TARGET], random_state=seed)
    return {'train': train, 'val': val, 'test': test}


# --------------------------------------------------------------------------------------
# 2. Fitted transformers
# --------------------------------------------------------------------------------------
class BankingFeatures(BaseEstimator, TransformerMixin):
    """Median/mode imputation (fitted) followed by banking features computed from real, uncapped values."""

    def fit(self, X: pd.DataFrame, y=None):
        cibil = X['CIBIL_Score']
        self.medians_ = {c: float(X[c].median()) for c in
                         ['Age', 'Work_Experience', 'Monthly_Income', 'Existing_EMI', 'Loan_Amount']}
        self.cibil_median_ = float(cibil[cibil != -1].median())     # median of SCORED applicants; -1 is not missing
        self.modes_ = {c: X[c].mode().iloc[0] for c in ['Dependents', 'Employment_Type', 'Loan_Type', 'Loan_Tenure']}
        secured = X[X['Collateral_Value'] > 0]
        self.coverage_by_type_ = (secured['Collateral_Value'] / secured['Loan_Amount']).groupby(
            secured['Loan_Type']).median().to_dict()
        self.rates_ = config.load('policies_v1')['indicative_rates']
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        X = X.copy()
        for c, v in self.medians_.items():
            X[c] = X[c].fillna(v)
        for c, v in self.modes_.items():
            X[c] = X[c].fillna(v)
        X['CIBIL_Score'] = X['CIBIL_Score'].fillna(self.cibil_median_)
        X['Coapplicant_Income'] = X['Coapplicant_Income'].fillna(0.0)
        miss_coll = X['Collateral_Value'].isna()
        X.loc[miss_coll, 'Collateral_Value'] = (X.loc[miss_coll, 'Loan_Amount']
                                                * X.loc[miss_coll, 'Loan_Type'].map(self.coverage_by_type_).fillna(0))
        X['Work_Experience'] = np.minimum(X['Work_Experience'], np.maximum(X['Age'] - 18, 0))

        out = pd.DataFrame(index=X.index)
        ti = X['Monthly_Income'] + X['Coapplicant_Income']
        r = X['Loan_Type'].map(self.rates_).astype(float) / 12
        g = (1 + r) ** X['Loan_Tenure']
        out['proposed_emi'] = X['Loan_Amount'] * r * g / (g - 1)
        out['total_income'] = ti
        out['foir'] = (X['Existing_EMI'] + out['proposed_emi']) / ti
        out['loan_to_income'] = X['Loan_Amount'] / (12 * ti)
        out['collateral_coverage'] = X['Collateral_Value'] / X['Loan_Amount']
        out['ltv'] = np.where(X['Collateral_Value'] > 0, X['Loan_Amount'] / X['Collateral_Value'].where(
            X['Collateral_Value'] > 0), np.nan)
        out['age_at_maturity'] = X['Age'] + X['Loan_Tenure'] / 12
        out['is_new_to_credit'] = (X['CIBIL_Score'] == -1).astype(int)
        out['cibil_score'] = X['CIBIL_Score'].where(X['CIBIL_Score'] != -1, self.cibil_median_)
        out['is_secured'] = (X['Collateral_Value'] > 0).astype(int)
        out['has_coapplicant'] = (X['Coapplicant_Income'] > 0).astype(int)
        out['work_experience'] = X['Work_Experience']
        out['existing_emi'] = X['Existing_EMI']
        out['loan_amount'] = X['Loan_Amount']
        out['loan_tenure'] = X['Loan_Tenure']
        out['dependents'] = X['Dependents'].astype(float)
        out['Employment_Type'] = X['Employment_Type'].astype(str)
        out['Loan_Type'] = X['Loan_Type'].astype(str)
        return out


class IQRCapper(OneToOneFeatureMixin, TransformerMixin, BaseEstimator):
    """Clip each column to [Q1 - k*IQR, Q3 + k*IQR] learned on fit. A column with IQR = 0 is not capped."""

    def __init__(self, factor: float = 3.0):
        self.factor = factor

    def fit(self, X, y=None):
        X = pd.DataFrame(X)
        q1, q3 = X.quantile(0.25), X.quantile(0.75)
        iqr = q3 - q1
        self.lower_ = (q1 - self.factor * iqr).where(iqr > 0, -np.inf).to_numpy(dtype=float)
        self.upper_ = (q3 + self.factor * iqr).where(iqr > 0, np.inf).to_numpy(dtype=float)
        self.n_features_in_ = X.shape[1]
        if hasattr(X, 'columns'):
            self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        return self

    def transform(self, X):
        arr = np.clip(np.asarray(X, dtype=float), self.lower_, self.upper_)
        return pd.DataFrame(arr, columns=getattr(X, 'columns', None), index=getattr(X, 'index', None)) \
            if isinstance(X, pd.DataFrame) else arr


def build_preprocessor() -> Pipeline:
    p = _settings()['preprocess']
    columns = ColumnTransformer([
        ('num', Pipeline([('cap', IQRCapper(p['iqr_factor'])), ('scale', MinMaxScaler(clip=True))]), p['continuous']),
        ('codes', 'passthrough', p['ordinal'] + p['binary']),
        ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), p['nominal']),
    ], remainder='drop', verbose_feature_names_out=False)
    pipe = Pipeline([('features', BankingFeatures()), ('columns', columns)])
    columns.set_output(transform='pandas')
    return pipe


def categorical_columns(feature_names: list[str]) -> list[str]:
    """Columns that are codes (ordinal, binary, one-hot): never scaled, and treated as nominal by SMOTENC."""
    cont = set(_settings()['preprocess']['continuous'])
    return [c for c in feature_names if c not in cont]


def make_resampler(feature_names: list[str], seed: int | None = None):
    """SMOTENC when both kinds of column are present, plain SMOTE / SMOTEN otherwise."""
    from imblearn.over_sampling import SMOTE, SMOTEN, SMOTENC
    seed = _settings()['seed'] if seed is None else seed
    k = _settings()['preprocess']['smote']['k_neighbors']
    cats = [i for i, c in enumerate(feature_names) if c in set(categorical_columns(feature_names))]
    if not cats:
        return SMOTE(k_neighbors=k, random_state=seed)
    if len(cats) == len(feature_names):
        return SMOTEN(k_neighbors=k, random_state=seed)
    return SMOTENC(categorical_features=cats, k_neighbors=k, random_state=seed)


def smote_counts(X: pd.DataFrame, y: pd.Series) -> dict:
    """Before/after class counts of the resampler on (X, y). Used for the report; never applied to val/test."""
    Xr, yr = make_resampler(list(X.columns)).fit_resample(X, y)
    return {'before': {int(k): int(v) for k, v in pd.Series(y).value_counts().sort_index().items()},
            'after': {int(k): int(v) for k, v in pd.Series(yr).value_counts().sort_index().items()}}


# --------------------------------------------------------------------------------------
# 3. Build, save, load, live transform
# --------------------------------------------------------------------------------------
def build(raw: pd.DataFrame | None = None) -> dict:
    """Clean, split, fit on train. Returns everything in memory (nothing written)."""
    raw = loaders.load_synthetic_raw() if raw is None else raw
    df = prepare_dataset(raw)
    parts = split(df)
    pre = build_preprocessor().fit(parts['train'])
    X = {k: pre.transform(v) for k, v in parts.items()}
    y = {k: v[TARGET] for k, v in parts.items()}
    return {'clean': df, 'parts': parts, 'preprocessor': pre, 'X': X, 'y': y,
            'feature_names': list(X['train'].columns)}


def preprocessor_path() -> Path:
    s = _settings()
    return config.ROOT / s['paths']['encoders'] / f"{s['preprocess']['version']}.joblib"


def processed_dir() -> Path:
    return config.ROOT / 'data' / 'processed'


def run() -> dict:
    """Build and write all Step 2 artefacts. Returns the build dict plus a summary."""
    b = build()
    s = _settings()
    out = processed_dir()
    out.mkdir(parents=True, exist_ok=True)
    for k in ('train', 'val', 'test'):
        frame = b['X'][k].copy()
        frame.insert(0, 'Loan_ID', b['parts'][k]['Loan_ID'].to_numpy())
        frame.index = b['parts'][k].index
        frame[TARGET] = b['y'][k].to_numpy()
        frame.reset_index(drop=True).to_parquet(out / f'{k}.parquet', index=False)
    split_of = pd.concat([pd.Series(k, index=v.index) for k, v in b['parts'].items()])
    clean_df = b['clean'].assign(split=split_of.sort_index())
    clean_df.drop(columns=[c for c in clean_df if c.startswith('_')]).to_parquet(out / 'clean.parquet', index=False)
    clean_df[SIDE_TABLE + ['split']].to_parquet(out / 'protected.parquet', index=False)
    (out / 'split_indices.json').write_text(json.dumps(
        {k: v['Loan_ID'].tolist() for k, v in b['parts'].items()}, indent=0))

    dist = {k: {'n': int(len(v)), 'approved_share': round(float(v.mean()), 4)} for k, v in b['y'].items()}
    dist['all'] = {'n': int(len(b['clean'])), 'approved_share': round(float(b['clean'][TARGET].mean()), 4)}
    summary = {
        'version': s['preprocess']['version'],
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'sklearn': sklearn.__version__, 'python': platform.python_version(),
        'data_sha256': synthetic.sha256(config.ROOT / s['paths']['synthetic_raw']),
        'rows_in': b['clean'].attrs['rows_in'], 'rows_out': b['clean'].attrs['rows_out'],
        'feature_names': b['feature_names'], 'class_distribution': dist,
        'smote_train_counts': smote_counts(b['X']['train'], b['y']['train']),
    }
    path = preprocessor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({**summary, 'preprocessor': b['preprocessor']}, path)
    report = config.ROOT / s['paths']['reports'] / 'preprocess_summary.json'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(summary, indent=2))
    b['summary'] = summary
    return b


def load_preprocessor(path: str | Path | None = None) -> dict:
    return joblib.load(path or preprocessor_path())


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA or (isinstance(v, str) and not v.strip())


def live_errors(record: dict, normalised: pd.DataFrame | None = None) -> list[str]:
    """Contract violations of a live application after spelling/number normalisation. A value that was given
    but could not be parsed is reported as unparseable rather than as missing. Never raises."""
    try:
        if not isinstance(record, dict):
            return [f'application must be a mapping of field -> value, got {type(record).__name__}']
        row = normalise(pd.DataFrame([dict(record)])) if normalised is None else normalised
        first = row.iloc[0]
        as_dict = {k: (first[k] if k in row.columns else v) for k, v in record.items()}
        errors = [f'{k}: could not parse {record[k]!r}' for k in record
                  if k in contract.FIELDS and not _missing(record[k]) and _missing(as_dict.get(k))]
        bad = {e.split(':')[0] for e in errors}
        return errors + [e for e in contract.validate(as_dict) if e.split(':')[0] not in bad]
    except Exception as e:  # noqa: BLE001 - validation must never crash the caller
        return [f'application could not be read: {type(e).__name__}: {e}']


def transform_applicant(record: dict, bundle: dict | None = None) -> pd.DataFrame:
    """One live application (raw or canonical spellings) -> one-row model feature frame.

    Raises ContractError (listing every violation) instead of imputing over invalid input.
    """
    bundle = bundle or load_preprocessor()
    row = normalise(pd.DataFrame([dict(record)]))
    errors = live_errors(record, row)
    if errors:
        raise ContractError(errors)
    features = bundle['preprocessor'].transform(repair_invalid(row, historical=False))
    return features[bundle['feature_names']]


# --------------------------------------------------------------------------------------
# 4. Secondary benchmark (Loan.csv): generic pipeline, banking-specific features omitted
# --------------------------------------------------------------------------------------
def build_generic_preprocessor(numeric: list[str], categorical: list[str], iqr_factor: float | None = None):
    k = _settings()['preprocess']['iqr_factor'] if iqr_factor is None else iqr_factor
    ct = ColumnTransformer([
        ('num', Pipeline([('impute', SimpleImputer(strategy='median')), ('cap', IQRCapper(k)),
                          ('scale', MinMaxScaler(clip=True))]), numeric),
        ('cat', Pipeline([('impute', SimpleImputer(strategy='most_frequent')),
                          ('onehot', OneHotEncoder(handle_unknown='ignore', sparse_output=False))]), categorical),
    ], remainder='drop', verbose_feature_names_out=False)
    return ct.set_output(transform='pandas')


def prepare_loan_csv(df: pd.DataFrame, target: str = 'Status', id_col: str = 'ID') -> tuple[pd.DataFrame, pd.Series, list, list]:
    """Drop the ID, the target and pricing fields (they leak the target), and split columns by type."""
    drop = {target, id_col} | {c for c in df if c.lower() in loaders.PRICING_COLUMNS}
    X = df.drop(columns=[c for c in drop if c in df])
    numeric = X.select_dtypes(include='number').columns.tolist()
    categorical = [c for c in X if c not in numeric]
    return X, df[target], numeric, categorical


if __name__ == '__main__':
    # Import through the package so pickled classes are stored as cognilend.data.preprocess.*, not __main__.*
    from cognilend.data import preprocess as _self
    result = _self.run()
    print(json.dumps({k: v for k, v in result['summary'].items() if k != 'feature_names'}, indent=2))
    print('features:', result['feature_names'])
    print('wrote', _self.preprocessor_path())
