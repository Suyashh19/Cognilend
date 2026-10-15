"""Input schema (FR-1): field names, types, units and valid ranges for an application.

The schema itself lives in config/data_contract.yaml. This module turns it into Field objects and validates
records. validate() never raises on bad input (NFR: no crash on bad input). It returns a list of messages,
and an empty list means the record is valid.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

from cognilend import config


@dataclass(frozen=True)
class Field:
    name: str
    dtype: str                      # str | int | float | category
    unit: str | None
    required: bool
    role: str
    protected: bool
    model: bool
    min: float | None = None
    max: float | None = None
    allowed: tuple = ()
    special: tuple = ()             # extra valid values outside [min, max], e.g. CIBIL -1
    pattern: str | None = None
    note: str | None = None


def _load() -> tuple[dict[str, Field], dict]:
    spec = config.load('data_contract')
    fields = {}
    for name, f in spec['fields'].items():
        fields[name] = Field(name=name, dtype=f['dtype'], unit=f.get('unit'), required=f['required'],
                             role=f['role'], protected=f['protected'], model=f['model'], min=f.get('min'),
                             max=f.get('max'), allowed=tuple(f.get('allowed', ())), special=tuple(f.get('special', ())),
                             pattern=f.get('pattern'), note=f.get('note'))
    return fields, spec['derived']


FIELDS, DERIVED = _load()
PROTECTED = [n for n, f in FIELDS.items() if f.protected] + [n for n, d in DERIVED.items() if d['protected']]
MODEL_ELIGIBLE = [n for n, f in FIELDS.items() if f.model]
INPUT_FIELDS = [n for n, f in FIELDS.items() if f.role != 'target']


def _missing(v: Any) -> bool:
    if v is None or v is pd.NA or v is pd.NaT:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return isinstance(v, str) and v.strip() == ''


def _as_number(v: Any) -> float | None:
    """Strict numeric parse: real numbers and numeric strings only (bools and text such as '12,50,000' fail)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str):
        try:
            x = float(v.strip())
        except ValueError:
            return None
        return x if math.isfinite(x) else None
    try:  # numpy scalars
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _check(f: Field, v: Any) -> str | None:
    if f.dtype == 'str':
        if not isinstance(v, str):
            return f'{f.name}: expected text, got {type(v).__name__}'
        if f.pattern and not re.fullmatch(f.pattern, v):
            return f'{f.name}: {v!r} does not match {f.pattern}'
        return None
    if f.dtype == 'category':
        if v not in f.allowed:
            return f'{f.name}: {v!r} not in {list(f.allowed)}'
        return None
    x = _as_number(v)
    if x is None:
        return f'{f.name}: {v!r} is not a number'
    if f.dtype == 'int' and x != int(x):
        return f'{f.name}: {x:g} must be a whole number'
    if x in f.special:
        return None
    if (f.min is not None and x < f.min) or (f.max is not None and x > f.max):
        unit = f' {f.unit}' if f.unit else ''
        return f'{f.name}: {x:g} outside the valid range [{f.min:g}, {f.max:g}]{unit}'
    return None


def validate(record: Mapping[str, Any], require_target: bool = False) -> list[str]:
    """Return every contract violation in one application. An empty list means valid. Never raises."""
    try:
        errors = []
        unknown = sorted(set(record) - set(FIELDS))
        if unknown:
            errors.append(f'unknown field(s): {unknown}')
        for name, f in FIELDS.items():
            v = record.get(name)
            if _missing(v):
                if f.required or (require_target and f.role == 'target'):
                    errors.append(f'{name}: required field is missing')
                continue
            msg = _check(f, v)
            if msg:
                errors.append(msg)
        # cross-field: experience cannot start before age 18
        age, exp = _as_number(record.get('Age')), _as_number(record.get('Work_Experience'))
        if age is not None and exp is not None and not any(e.startswith(('Age', 'Work_Experience')) for e in errors):
            if exp > age - 18:
                errors.append(f'Work_Experience: {exp:g} years is impossible at age {age:g} (max {age - 18:g})')
        return errors
    except Exception as e:  # defensive: validation itself must never crash the pipeline
        return [f'record could not be validated: {type(e).__name__}: {e}']


def is_valid(record: Mapping[str, Any]) -> bool:
    return not validate(record)


def validate_frame(df: pd.DataFrame) -> pd.Series:
    """Per-row list of violations, indexed like df."""
    return pd.Series([validate({k: v for k, v in r.items() if k in FIELDS}) for r in df.to_dict('records')],
                     index=df.index, dtype=object)


def age_band(age: float) -> str | None:
    """Protected fairness band for an age (bins from config/fairness.yaml); None if age is missing."""
    if _as_number(age) is None:
        return None
    g = config.load('fairness')['groups']['age_band']
    return str(pd.cut([float(age)], bins=g['bins'], labels=g['labels'], right=True)[0])
