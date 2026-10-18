"""Maximum approvable amount for a REJECTED application (advisory only; never creates a decision).

    find_max_approvable_amount(application) -> {applicable, possible, requested_amount, max_amount, emi_at_max,
        tenure_months, confidence_at_max, binding_limit, explanation, tree_path_at_max, model_version,
        policy_version, candidates_checked, runtime_ms, ...}

Only the loan amount changes; every other field of the application is held fixed.

1. The application is scored with dry_run.evaluate_without_saving. Not Rejected -> {applicable: False}.
2. Every fired rule is classified as amount-dependent or not from the fact derivation graph: a rule depends on
   the amount when its fact or threshold fact is derived (transitively) from loan_amount. One amount-independent
   fired rule (age, CIBIL, blacklist, income, missing data, invalid input, ...) -> possible=False, no search.
3. Analytical upper bound from the rule formulas (the facts module's own EMI derivation is reused):
   FOIR (incl. the S03 borderline margin, since a borderline FOIR goes to review) and the RBI LTV cap.
4. The tree is not monotonic in the amount, so candidates are: the largest step multiple below every breakpoint
   (tree split thresholds on loan_amount / foir / loan_to_income / collateral_coverage, FOIR and LTV limits,
   LTV slab edges, converted to rupees) plus the full step grid when the range is small. Between two
   breakpoints every amount-dependent fact stays on the same side of every threshold, so the outcome is
   constant and the candidate set is exhaustive over step multiples. All candidates are scored in one batch;
   the highest Approved one is re-confirmed with evaluate_without_saving.

Protected attributes (Gender, Marital_Status) are never read here; the application is copied as a whole.
"""
from __future__ import annotations

import copy
import math
import os
import time
from functools import lru_cache
from pathlib import Path

import yaml

from cognilend import config
from cognilend.addons.dry_run import decisions_without_saving, evaluate_without_saving, pipeline
from cognilend.data import contract
from cognilend.rules import facts as F
from cognilend.rules.rules import load_policy, load_rules

FEATURES_YAML = config.CONFIG_DIR / 'features.yaml'
AMOUNT = 'loan_amount'
LIMIT_OF_RULE = {'foir': 'FOIR', 'foir_borderline': 'FOIR', 'ltv': 'LTV'}   # fact -> binding_limit label


def settings(path: str | Path | None = None) -> dict:
    """config/features.yaml -> max_amount_suggestion block (read fresh, so toggling the flag needs no restart)."""
    path = path or os.environ.get('COGNILEND_FEATURES_YAML') or FEATURES_YAML      # env override: tests / ops
    try:
        data = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    except OSError:
        data = {}
    s = {'enabled': False, 'step': 10000, 'min_loan_amount': 50000, 'max_grid_points': 60, 'log_suggestions': True}
    s.update(data.get('max_amount_suggestion') or {})
    return s


def enabled(path: str | Path | None = None) -> bool:
    return bool(settings(path).get('enabled'))


def fmt_inr(x: float) -> str:
    """Indian digit grouping: 2790000 -> '₹27,90,000'."""
    n = int(round(float(x)))
    sign, s = ('-' if n < 0 else ''), str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ','.join([head, *groups, tail]) if head else ','.join([*groups, tail])
    return f'{sign}₹{s}'


# ---------------------------------------------------------------------------------------------------------
# Which rules depend on the amount (derived from the fact graph, not a hand-typed list)
# ---------------------------------------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _policy(version: str):
    policy = load_policy(version)
    return policy, load_rules(policy), F.derivations(policy)


@lru_cache(maxsize=None)
def amount_dependent_facts(version: str = 'v1') -> frozenset:
    _, _, derivs = _policy(version)
    dep, changed = {AMOUNT}, True
    while changed:
        changed = False
        for d in derivs:
            if d.output not in dep and any(i in dep for i in d.inputs):
                dep.add(d.output)
                changed = True
    return frozenset(dep)


@lru_cache(maxsize=None)
def amount_dependent_rules(version: str = 'v1') -> dict:
    """rule id -> True when the rule's fact or threshold fact depends on loan_amount."""
    _, rules, _ = _policy(version)
    dep = amount_dependent_facts(version)
    return {r.id: (r.fact in dep or (r.threshold_fact or '') in dep) for r in rules}


def _rule_fact(rule_id: str, version: str) -> str | None:
    return next((r.fact for r in _policy(version)[1] if r.id == rule_id), None)


def _limit_label(fired: list[str], decision: str, version: str) -> str:
    """binding_limit for a decision that is not an auto-approval."""
    for rid in fired:
        label = LIMIT_OF_RULE.get(_rule_fact(rid, version))
        if label:
            return label
    if fired:
        return f'RULE:{fired[0]}'
    return 'MODEL' if decision != 'Approved' else 'NONE'


# ---------------------------------------------------------------------------------------------------------
# Analytical bounds and breakpoints, all in rupees
# ---------------------------------------------------------------------------------------------------------
def emi_per_rupee(facts: dict, version: str = 'v1') -> float:
    """EMI of a ₹1 loan at this product rate and tenure, from the facts module's own proposed_emi derivation."""
    d = next(d for d in _policy(version)[2] if d.output == 'proposed_emi')
    return float(d.fn({**facts, 'loan_amount': 1.0}))


def foir_amount(foir: float, facts: dict, epr: float) -> float | None:
    """Loan amount at which FOIR equals `foir` (FOIR = (existing EMI + amount * epr) / total income)."""
    ti, emi = facts.get('total_income'), facts.get('existing_emi')
    if ti is None or emi is None or epr <= 0:
        return None
    return (foir * ti - emi) / epr


def ltv_max_amount(facts: dict, version: str = 'v1') -> float | None:
    """Largest amount with ltv <= ltv_cap(amount). None when no LTV cap applies (non-housing / no collateral)."""
    if facts.get('ltv_cap') is None or not (facts.get('collateral_value') or 0) > 0:
        return None
    slabs = _policy(version)[0]['parameters']['ltv_slabs']
    c = float(facts['collateral_value'])
    points = [s['max_ltv'] * c for s in slabs] + [v for s in slabs for k, v in s.items() if k.startswith('amount_')]
    ok = [p for p in points if p > 0 and p / c <= F._slab(p, slabs, 'amount', 'max_ltv') + 1e-12]
    return max(ok) if ok else 0.0


def ltv_slab_edges(version: str = 'v1') -> list[float]:
    slabs = _policy(version)[0]['parameters']['ltv_slabs']
    return [float(v) for s in slabs for k, v in s.items() if k.startswith('amount_')]


def tree_breakpoints(facts: dict, epr: float) -> list[float]:
    """Tree split thresholds on amount-derived model features, converted to rupees."""
    ex = pipeline().explainer
    t = ex.clf.tree_
    ti, coll = facts.get('total_income'), facts.get('collateral_value') or 0
    out = []
    for node in range(t.node_count):
        if t.children_left[node] == t.children_right[node]:
            continue
        f = ex.features[t.feature[node]]
        thr = ex.to_raw(f, float(t.threshold[node]))
        if thr is None:
            continue
        if f == 'loan_amount':
            out.append(thr)
        elif f == 'foir':
            a = foir_amount(thr, facts, epr)
            if a is not None:
                out.append(a)
        elif f == 'loan_to_income' and ti:
            out.append(thr * 12 * ti)
        elif f == 'collateral_coverage' and coll > 0 and thr > 0:
            out.append(coll / thr)
    return out


def candidate_amounts(lower: float, upper: float, step: int, breakpoints: list[float], max_grid: int) -> list[int]:
    """Largest step multiple below/at every breakpoint (+ the one under it, for <= vs < edges), the bounds, and
    the whole grid when it is small. Sorted high -> low."""
    fl = lambda x: int(math.floor(x / step) * step)  # noqa: E731
    lo, hi = int(math.ceil(lower / step) * step), fl(upper)
    cands = {hi, lo}
    for bp in breakpoints:
        if bp is not None and math.isfinite(bp):
            cands.update({fl(bp), fl(bp) - step})
    if (hi - lo) // step + 1 <= max_grid:
        cands.update(range(lo, hi + 1, step))
    return sorted((c for c in cands if lo <= c <= hi), reverse=True)


# ---------------------------------------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------------------------------------
def _with_amount(application: dict, amount: int) -> dict:
    app = copy.deepcopy(application)
    app['Loan_Amount'] = int(amount)
    return app


def _not_possible(base: dict, binding: str, explanation: str, **extra) -> dict:
    return {**base, 'possible': False, 'max_amount': None, 'emi_at_max': None, 'confidence_at_max': None,
            'binding_limit': binding, 'explanation': explanation, 'tree_path_at_max': None, **extra}


def find_max_approvable_amount(application: dict, policy_version: str = 'v1') -> dict:
    t0 = time.perf_counter()
    s = settings()
    step = int(s['step'])
    original = evaluate_without_saving(application, policy_version)
    if original['decision'] != 'Rejected':
        return {'applicable': False, 'original_decision': original['decision']}

    facts = original['facts']
    requested = facts.get(AMOUNT)
    base = {'applicable': True, 'requested_amount': requested, 'tenure_months': facts.get('loan_tenure'),
            'model_version': original['model_version'] or pipeline(policy_version).explainer.dt['version'],
            'policy_version': original['policy_version'], 'original_reason': original['reason'],
            'blocking_rule': None, 'candidates_checked': 0}

    def done(r):
        r['runtime_ms'] = round(1000 * (time.perf_counter() - t0), 1)
        return r

    # ---- 1. classify the rejection ----
    fired = list(original['fired_rules'] or [])
    reasons = dict(zip(fired, original['rule_reasons']))
    if 'INPUT' in fired or requested is None:
        return done(_not_possible({**base, 'blocking_rule': 'INPUT'}, 'RULE:INPUT',
                                  'No lower amount can be approved: the application has invalid input '
                                  f'({original["reason"]}). Correct the input and apply again.'))
    dependent = amount_dependent_rules(policy_version)
    independent = [r for r in fired if not dependent.get(r, False)]
    if independent:
        rid = independent[0]
        return done(_not_possible({**base, 'blocking_rule': rid}, f'RULE:{rid}',
                                  f'No lower amount can be approved: rule {rid} does not depend on the loan amount '
                                  f'({reasons.get(rid, original["reason"])}).'))

    # ---- 2. analytical bounds ----
    policy = _policy(policy_version)[0]
    epr = emi_per_rupee(facts, policy_version)
    margin = policy['parameters']['foir_borderline_margin']
    limit = facts.get('foir_limit')
    foir_cap = foir_amount(limit - margin, facts, epr) if limit is not None else None
    ltv_cap = ltv_max_amount(facts, policy_version)
    below_requested = math.ceil(requested / step) * step - step
    bounds = {'REQUESTED': below_requested, 'FOIR': foir_cap, 'LTV': ltv_cap}
    known = {k: v for k, v in bounds.items() if v is not None}
    analytic = min(known, key=known.get)
    upper = known[analytic]
    lower = max(float(s['min_loan_amount']), float(contract.FIELDS['Loan_Amount'].min))
    base.update(lower_bound=lower, upper_bound=max(upper, 0.0), max_amount_foir=foir_cap, max_amount_ltv=ltv_cap)
    if upper < lower:
        why = {'FOIR': f'the FOIR limit (with its review margin) allows at most {fmt_inr(max(upper, 0))}',
               'LTV': f'the LTV cap allows at most {fmt_inr(max(upper, 0))}',
               'REQUESTED': 'the requested amount is already at the minimum'}[analytic]
        return done(_not_possible(base, analytic, f'No lower amount can be approved: {why}, below the minimum '
                                                  f'loan of {fmt_inr(lower)}.'))

    # ---- 3. candidates (exhaustive over step multiples, see module docstring) ----
    bps = tree_breakpoints(facts, epr) + ltv_slab_edges(policy_version)
    bps += [b for b in (foir_cap, foir_amount(limit, facts, epr) if limit is not None else None, ltv_cap) if b]
    cands = candidate_amounts(lower, upper, step, bps, int(s['max_grid_points']))
    if not cands:
        return done(_not_possible(base, analytic, f'No lower amount can be approved: no {fmt_inr(step)} step '
                                                  f'between {fmt_inr(lower)} and {fmt_inr(upper)}.'))
    decisions = decisions_without_saving([_with_amount(application, c) for c in cands], policy_version)
    base['candidates_checked'] = len(cands)

    # ---- 4. highest auto-approval, re-confirmed one by one ----
    for amount, dec in zip(cands, decisions):
        if dec != 'Approved':
            continue
        at = evaluate_without_saving(_with_amount(application, amount), policy_version)
        base['candidates_checked'] += 1
        if at['decision'] != 'Approved':
            continue
        nxt_amount = min(amount + step, requested)
        nxt = evaluate_without_saving(_with_amount(application, nxt_amount), policy_version)
        binding = _limit_label(nxt['fired_rules'] or [], nxt['decision'], policy_version)
        if binding == 'NONE':                      # cannot happen in practice: the requested amount was rejected
            binding = analytic
        what = {'FOIR': 'the FOIR (affordability) limit', 'LTV': 'the RBI LTV cap',
                'MODEL': 'the model (a higher amount falls in a leaf that is not auto-approved)'}
        limit_txt = what.get(binding, f'rule {binding.split(":", 1)[-1]}')
        return done({**base, 'possible': True, 'max_amount': amount,
                     'emi_at_max': at['facts'].get('proposed_emi'), 'confidence_at_max': at['confidence'],
                     'leaf_support_at_max': at['leaf_support'], 'binding_limit': binding,
                     'next_step_amount': nxt_amount, 'next_step_decision': nxt['decision'],
                     'tree_path_at_max': [p['text'] for p in at['tree_path'] or []],
                     'model_version': at['model_version'] or base['model_version'],
                     'explanation': f'This loan can be approved for up to {fmt_inr(amount)} (instead of '
                                    f'{fmt_inr(requested)} requested); above that, {limit_txt} decides.'})

    # ---- 5. nothing in range approves ----
    at_low = evaluate_without_saving(_with_amount(application, cands[-1]), policy_version)
    blocker = _limit_label(at_low['fired_rules'] or [], at_low['decision'], policy_version)
    who = 'the model' if blocker == 'MODEL' else 'the policy rules'
    return done(_not_possible(base, blocker, f'No lower amount can be approved: no amount down to {fmt_inr(lower)} '
                                             f'is auto-approved; {who} blocks it ({at_low["reason"]}).'))
