"""Forward-chaining inference: HARD violation -> reject (FR-6), SOFT -> human review.

    evaluate(application) -> {outcome: REJECT | REVIEW | PASS, fired_rules, reasons, policy_version,
                              evaluations, facts, trace, input_errors}

1. The application is normalised and validated against the data contract. Invalid input gives a graceful
   REJECT ("invalid input: <field>"), never an exception.
2. Working memory = base facts. Derivations fire whenever all their inputs are known and their output is not,
   until a fixpoint (no new facts).
3. Policy rules are evaluated on the final facts. Every rule is recorded (fired / passed / exempt /
   not_applicable / not_evaluated) for the audit trail. Outcome: any HARD fired -> REJECT; else any SOFT fired
   -> REVIEW; else PASS. On REJECT the caller must not call the ML layer.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from cognilend.data import contract, preprocess
from cognilend.rules import facts as F
from cognilend.rules.rules import load_policy, load_rules


@lru_cache(maxsize=None)
def _policy(version: str):
    policy = load_policy(version)
    return policy, load_rules(policy), F.derivations(policy)


def _py(v):
    """numpy scalars -> python, NaN -> None, so facts compare and serialise cleanly."""
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and np.isnan(v):
        return None
    return v


def _reason(rule, value, limit, facts, policy) -> str:
    ctx = {**facts, 'threshold': limit, 'margin': policy['parameters']['foir_borderline_margin']}
    if isinstance(ctx.get('missing_fields'), list):
        ctx['missing_fields'] = ', '.join(ctx['missing_fields'])
    try:
        return rule.reason.format(**ctx)
    except (KeyError, TypeError, ValueError):
        return f'{rule.id} {rule.name}: {rule.condition} (value {value}, threshold {limit})'


def _invalid(errors: list[str], version: str) -> dict:
    fields = []
    for e in errors:
        name = e.split(':')[0].strip()
        if name not in fields:
            fields.append(name)
    return {'outcome': 'REJECT', 'fired_rules': ['INPUT'], 'policy_version': version,
            'reasons': [f'invalid input: {e}' for e in errors], 'invalid_fields': fields,
            'evaluations': [], 'facts': {}, 'trace': [], 'input_errors': errors}


def infer(canonical: dict, version: str = 'v1') -> dict:
    """Forward chaining on an already normalised, contract-valid application."""
    policy, rules, derivs = _policy(version)
    wm = F.base_facts({k: _py(v) for k, v in canonical.items()}, policy)
    trace = []
    changed = True
    while changed:
        changed = False
        for d in derivs:
            if d.output in wm:
                continue
            if all(wm.get(i) is not None for i in d.inputs):
                wm[d.output] = _py(d.fn(wm))
                trace.append(d.output)
                changed = True

    evaluations, fired, reasons = [], [], []
    for rule in rules:
        status, value, limit = rule.evaluate(wm)
        evaluations.append({'rule_id': rule.id, 'type': rule.type, 'name': rule.name, 'status': status,
                            'value': _py(value), 'threshold': _py(limit)})
        if status == 'fired':
            fired.append(rule)
            reasons.append(_reason(rule, value, limit, wm, policy))
    hard = [r.id for r in fired if r.type == 'HARD']
    soft = [r.id for r in fired if r.type == 'SOFT']
    wm['hard_violation'], wm['review_required'] = bool(hard), bool(soft)
    outcome = 'REJECT' if hard else 'REVIEW' if soft else 'PASS'
    # HARD reasons first: they decide the outcome
    ordered = [x for x in zip(fired, reasons) if x[0].type == 'HARD'] + [x for x in zip(fired, reasons) if x[0].type == 'SOFT']
    return {'outcome': outcome, 'fired_rules': [r.id for r, _ in ordered], 'reasons': [t for _, t in ordered],
            'policy_version': policy['version'], 'evaluations': evaluations, 'facts': wm, 'trace': trace,
            'input_errors': []}


def evaluate(application, version: str = 'v1') -> dict:
    """Validate, normalise and infer. Never raises."""
    try:
        if not isinstance(application, dict):
            return _invalid([f'application: must be a mapping of field -> value, got {type(application).__name__}'],
                            version)
        row = preprocess.normalise(pd.DataFrame([dict(application)]))
        errors = preprocess.live_errors(application, row)
        if errors:
            return _invalid(errors, version)
        first = row.iloc[0]
        canonical = {k: first[k] for k in contract.INPUT_FIELDS if k in row.columns}
        return infer(canonical, version)
    except Exception as e:  # noqa: BLE001 - the engine must never crash the pipeline
        return _invalid([f'application: could not be evaluated ({type(e).__name__}: {e})'], version)


def evaluate_clean(clean_row: dict, version: str = 'v1') -> dict:
    """Fast path for rows already cleaned by preprocess.clean (batch analysis); still contract-checked."""
    rec = {k: _py(v) for k, v in clean_row.items() if k in contract.INPUT_FIELDS}
    rec = {k: v for k, v in rec.items() if v is not None}
    errors = contract.validate(rec)
    return _invalid(errors, version) if errors else infer(rec, version)


def evaluate_many(applications: list, version: str = 'v1') -> list[dict]:
    """Batch version of evaluate(): one pandas normalisation for all rows, identical per-row results."""
    try:
        dicts = [a for a in applications if isinstance(a, dict)]
        if len(dicts) != len(applications):
            raise TypeError('non-mapping application in batch')
        frame = preprocess.normalise(pd.DataFrame([dict(a) for a in applications]))
    except Exception:  # noqa: BLE001 - fall back to the per-row path, which never raises
        return [evaluate(a, version) for a in applications]
    out = []
    for i, app in enumerate(applications):
        try:
            row = frame.iloc[[i]]
            errors = preprocess.live_errors(app, row)
            if errors:
                out.append(_invalid(errors, version))
                continue
            first = row.iloc[0]
            canonical = {k: first[k] for k in contract.INPUT_FIELDS if k in row.columns}
            out.append(infer(canonical, version))
        except Exception:  # noqa: BLE001
            out.append(evaluate(app, version))
    return out
