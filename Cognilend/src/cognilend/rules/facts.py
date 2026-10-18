"""Fact base derived from an application (FOIR, LTV, age at maturity, ...).

Facts are a flat dict. A missing / not-applicable fact is None. Derivations are small forward rules
(inputs -> output); the engine fires every derivation whose inputs are known until no new fact appears.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from cognilend import config

# canonical application field -> fact name
FIELD_TO_FACT = {
    'Loan_ID': 'loan_id', 'Applicant_ID': 'applicant_id', 'Age': 'age', 'Employment_Type': 'employment_type',
    'Work_Experience': 'work_experience', 'Monthly_Income': 'monthly_income',
    'Coapplicant_Income': 'coapplicant_income', 'Existing_EMI': 'existing_emi', 'CIBIL_Score': 'cibil_score',
    'Loan_Type': 'loan_type', 'Loan_Amount': 'loan_amount', 'Loan_Tenure': 'loan_tenure',
    'Collateral_Value': 'collateral_value', 'Dependents': 'dependents',
}
KEY_OPTIONAL = ['cibil_score', 'existing_emi', 'work_experience']      # never guessed for a live decision


def _known(v: Any) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def base_facts(application: dict, policy: dict) -> dict:
    """Canonical (normalised, contract-valid) application -> base facts. Structural blanks are filled here:
    no co-applicant income = 0; no collateral on an unsecured product = 0."""
    f = {fact: (application.get(field) if _known(application.get(field)) else None)
         for field, fact in FIELD_TO_FACT.items()}
    if f['coapplicant_income'] is None:
        f['coapplicant_income'] = 0.0
    secured = f['loan_type'] in policy['parameters']['secured_loan_types']
    if f['collateral_value'] is None and f['loan_type'] is not None and not secured:
        f['collateral_value'] = 0.0
    return f


@dataclass(frozen=True)
class Derivation:
    output: str
    inputs: tuple[str, ...]
    fn: Callable[[dict], Any]
    text: str


def _slab(value: float, slabs: list[dict], key_prefix: str, limit_key: str):
    for s in slabs:
        if f'{key_prefix}_below' in s and value < s[f'{key_prefix}_below']:
            return s[limit_key]
        if f'{key_prefix}_upto' in s and value <= s[f'{key_prefix}_upto']:
            return s[limit_key]
        if f'{key_prefix}_above' in s and value > s[f'{key_prefix}_above']:
            return s[limit_key]
    return slabs[-1][limit_key]


def load_registry(policy: dict) -> set[str]:
    path = config.ROOT / policy['parameters']['fraud_registry']
    if not Path(path).exists():
        return set()
    return set(map(str, yaml.safe_load(Path(path).read_text(encoding='utf-8')).get('applicant_ids', [])))


def derivations(policy: dict) -> list[Derivation]:
    p = policy['parameters']
    rates = policy['indicative_rates']
    registry = load_registry(policy)

    def emi(f):
        r = rates[f['loan_type']] / 12
        g = (1 + r) ** f['loan_tenure']
        return f['loan_amount'] * r * g / (g - 1)

    def borderline(f):
        return f['foir_limit'] - p['foir_borderline_margin'] < f['foir'] <= f['foir_limit']

    def missing(f):
        miss = [k for k in KEY_OPTIONAL if f.get(k) is None]
        if f['secured_loan'] and not (f.get('collateral_value') or 0) > 0:
            miss.append('collateral_value')
        return miss

    return [
        Derivation('total_income', ('monthly_income', 'coapplicant_income'),
                   lambda f: f['monthly_income'] + f['coapplicant_income'], 'monthly + co-applicant income'),
        Derivation('interest_rate', ('loan_type',), lambda f: rates.get(f['loan_type']), 'indicative rate by product'),
        Derivation('proposed_emi', ('loan_amount', 'interest_rate', 'loan_tenure'), emi,
                   'EMI = P r (1+r)^n / ((1+r)^n - 1)'),
        Derivation('foir', ('existing_emi', 'proposed_emi', 'total_income'),
                   lambda f: (f['existing_emi'] + f['proposed_emi']) / f['total_income'],
                   '(existing EMI + proposed EMI) / total income'),
        Derivation('foir_limit', ('total_income',), lambda f: _slab(f['total_income'], p['foir_slabs'], 'income',
                                                                    'max_foir'), 'FOIR limit by income slab'),
        Derivation('foir_borderline', ('foir', 'foir_limit'), borderline, 'FOIR within the margin under its limit'),
        Derivation('loan_to_income', ('loan_amount', 'total_income'),
                   lambda f: f['loan_amount'] / (12 * f['total_income']), 'loan / annual income'),
        Derivation('secured_loan', ('loan_type',), lambda f: f['loan_type'] in p['secured_loan_types'],
                   'product is secured'),
        Derivation('ltv', ('loan_amount', 'collateral_value'),
                   lambda f: f['loan_amount'] / f['collateral_value'] if f['collateral_value'] > 0 else None,
                   'loan / collateral value (None if unsecured)'),
        Derivation('ltv_cap', ('loan_type', 'loan_amount'),
                   lambda f: _slab(f['loan_amount'], p['ltv_slabs'], 'amount', 'max_ltv')
                   if f['loan_type'] == 'Home' else None, 'RBI LTV ceiling (housing loans only)'),
        Derivation('age_at_maturity', ('age', 'loan_tenure'), lambda f: f['age'] + f['loan_tenure'] / 12,
                   'age + tenure / 12'),
        Derivation('new_to_credit', ('cibil_score',), lambda f: f['cibil_score'] == -1, 'CIBIL == -1'),
        Derivation('min_experience', ('employment_type',), lambda f: p['min_experience'].get(f['employment_type']),
                   'minimum experience for the employment type'),
        Derivation('blacklist_hit', ('applicant_id',), lambda f: str(f['applicant_id']) in registry,
                   'applicant id in the fraud registry'),
        Derivation('missing_fields', ('secured_loan',), missing, 'key optional fields that are absent'),
        Derivation('missing_key_data', ('missing_fields',), lambda f: len(f['missing_fields']) > 0,
                   'any key field absent'),
    ]
