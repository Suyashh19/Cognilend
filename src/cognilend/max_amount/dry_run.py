"""Side-effect-free scoring: the exact decision pipeline.decide would return, without saving anything.

    evaluate_without_saving(application) -> {decision, outcome, confidence, reason, source, fired_rules, ...}

It CALLS the existing pipeline read-only: DecisionPipeline(repo=None) runs the same steps as decide()
(contract validation -> facts -> rule engine -> transform_applicant -> constrained tree -> Bayesian confidence
-> routing with tau / n_min / SOFT rules) with the same model, preprocessor and policy artefacts, but with no
repository it opens no DB session, takes no lock, writes no audit event and no fallback file.

Not modelled: the FR-10 lock pre-check (it needs the DB). A dry-run Approved can still become Human Review in
the real pipeline if the applicant or collateral already has an approved active loan.
"""
from __future__ import annotations

import copy
from functools import lru_cache

import pandas as pd

from cognilend.pipeline import DecisionPipeline
from cognilend.rules import engine

OUTCOME = {'Approved': 'APPROVE', 'Rejected': 'REJECT', 'Human Review': 'REVIEW'}
KEYS = ('decision', 'confidence', 'reason', 'source', 'fired_rules', 'tree_path', 'model_prediction',
        'confidence_ci', 'leaf', 'leaf_support', 'rule_evaluations', 'invalid_fields', 'model_version',
        'policy_version')


class _NoWrite:
    """Fallback log that refuses to write: with repo=None the pipeline never calls it, this makes sure."""

    def write(self, record, error):
        raise RuntimeError('dry run must not write a fallback record')


@lru_cache(maxsize=None)
def pipeline(policy_version: str = 'v1') -> DecisionPipeline:
    """Non-persisting pipeline (cached: loading the artefacts is the expensive part)."""
    return DecisionPipeline(repo=None, persist=False, policy_version=policy_version, fallback=_NoWrite())


def evaluate_without_saving(application, policy_version: str = 'v1') -> dict:
    """Decision for `application` exactly as pipeline.decide computes it, with nothing persisted.

    Extra keys: outcome (APPROVE | REJECT | REVIEW), rule_outcome, rule_reasons (aligned with fired_rules) and
    facts (the rule engine's fact base, e.g. proposed_emi, foir, ltv)."""
    app = copy.deepcopy(application)
    pipe = pipeline(policy_version)
    d = pipe.decide(app)
    rule = engine.evaluate(copy.deepcopy(application), policy_version)
    out = {k: d.get(k) for k in KEYS}
    out.update(outcome=OUTCOME.get(d['decision'], d['decision']), rule_outcome=rule['outcome'],
               rule_reasons=list(rule['reasons']), facts=dict(rule['facts']))
    return out


def decisions_without_saving(applications: list[dict], policy_version: str = 'v1') -> list[str]:
    """Batch: the decision string (Approved / Rejected / Human Review) per application, via decide_many with no
    repository (same per-row decisions as decide)."""
    if not applications:
        return []
    frame = pd.DataFrame([copy.deepcopy(a) for a in applications])
    return pipeline(policy_version).decide_many(frame, batch_id='dry-run')['decision'].tolist()
