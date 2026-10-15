"""Dataset loaders: the synthetic Indian dataset (primary) and Loan.csv (secondary ML benchmark, if supplied)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cognilend import config

# Kaggle "Loan Default" naming; matched case-insensitively. Fields that only exist once a loan has been priced.
PRICING_COLUMNS = ['rate_of_interest', 'interest_rate_spread', 'upfront_charges']
SENTINELS = (-1,)


def _path(key: str) -> Path:
    return config.ROOT / config.load('settings')['paths'][key]


def load_synthetic_raw(path: str | Path | None = None) -> pd.DataFrame:
    """The raw (dirty) primary dataset, read as-is. Cleaning happens in preprocess.py."""
    return pd.read_csv(path or _path('synthetic_raw'), dtype={'Loan_Amount': object, 'Dependents': object})


def load_loan_csv(path: str | Path | None = None) -> pd.DataFrame:
    p = Path(path or _path('loan_csv'))
    if not p.exists():
        raise FileNotFoundError(f'{p} not found. Loan.csv has not been supplied (see docs/data_decision.md).')
    return pd.read_csv(p)


def target_investigation(df: pd.DataFrame, target: str = 'Status') -> pd.DataFrame:
    """For every column, the share of missing / sentinel (-1) values within each target class.

    A column that is missing almost only for one class is evidence about what the class means. Example: pricing
    fields that are absent for status=1 suggest those loans were never priced or disbursed.
    """
    rows = []
    for c in df.columns.drop(target):
        s = df[c]
        absent = s.isna() | (s.isin(SENTINELS) if pd.api.types.is_numeric_dtype(s) else False)
        rate = absent.groupby(df[target]).mean()
        rows.append({'column': c, **{f'absent_rate_{target}={k}': v for k, v in rate.items()},
                     'gap': float(rate.max() - rate.min()), 'is_pricing_field': c.lower() in PRICING_COLUMNS})
    out = pd.DataFrame(rows).sort_values('gap', ascending=False).reset_index(drop=True)
    out.attrs['class_balance'] = df[target].value_counts(normalize=True).to_dict()
    return out


def pricing_explains_target(df: pd.DataFrame, target: str = 'Status', positive=1) -> dict:
    """How well 'all pricing fields absent' reproduces target == positive (precision, recall)."""
    cols = [c for c in df.columns if c.lower() in PRICING_COLUMNS]
    if not cols:
        return {'pricing_columns': [], 'note': 'no pricing columns found'}
    absent = np.logical_and.reduce([(df[c].isna() | df[c].isin(SENTINELS)).to_numpy() for c in cols])
    pos = (df[target] == positive).to_numpy()
    return {'pricing_columns': cols,
            'precision': float(pos[absent].mean()) if absent.any() else float('nan'),
            'recall': float(absent[pos].mean()) if pos.any() else float('nan')}
