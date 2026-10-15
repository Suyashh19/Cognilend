"""End-to-end orchestrator: contract -> rules -> lock -> tree -> routing -> audit DB.

    decide(application) -> {decision, confidence, reason, tree_path, fired_rules, audit_log_id, model_version,
                            policy_version, loan_id, decision_id, source, persisted, ...}

 1. validate against the data contract (malformed -> Rejected, reason "invalid input: ...")
 2. derive facts and run the rule engine (HARD -> Rejected; the ML layer is NOT called)
 3. lock pre-check: if the applicant or collateral already has an approved active loan -> Human Review
 4. transform_applicant -> constrained tree -> prediction, Bayesian confidence, path
 5. route: SOFT rule fired, or confidence < tau, or leaf support < n_min -> Human Review
 6. persist applicant, loan, decision, rule results and a hash-chained audit event in ONE transaction; the
    binding lock check runs inside it (an approval that lost a race becomes Human Review)
 7. return the decision. If the DB write fails the decision is still returned, written to the fallback log
    for replay, and an Approved decision is downgraded to Human Review because its lock could not be verified.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from cognilend.data import contract, preprocess
from cognilend.rules import engine

REQUIRED_KEYS = ('decision', 'confidence', 'reason', 'audit_log_id')


def _py(v):
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and np.isnan(v):
        return None
    return v


def _valid_id(v, field) -> str | None:
    if isinstance(v, str) and re.fullmatch(contract.FIELDS[field].pattern, v):
        return v
    return None


class DecisionPipeline:
    def __init__(self, repo=None, persist: bool = True, policy_version: str = 'v1', fallback=None):
        from cognilend.db.repository import FallbackLog, Repository
        self.policy_version = policy_version
        self.repo = repo if repo is not None else (Repository() if persist else None)
        self.fallback = fallback or FallbackLog()
        self._explainer = None
        self.versions = None
        if self.repo is not None:
            try:
                self.versions = self.repo.register_versions(policy_version)
            except Exception as e:  # noqa: BLE001 - registration failure must not stop decisions
                self.fallback.write({'event': 'register_versions'}, e)

    @property
    def explainer(self):
        if self._explainer is None:
            from cognilend.ml.explain import Explainer
            self._explainer = Explainer()
        return self._explainer

    def _ml(self, application: dict) -> dict:
        row = preprocess.repair_invalid(preprocess.normalise(pd.DataFrame([dict(application)])), historical=False)
        return self.explainer.explain(row)[0]

    # ---------- records for the DB ----------
    @staticmethod
    def _records(application, loan_id, applicant_id, collateral_id) -> tuple[dict, dict]:
        canon = {}
        if isinstance(application, dict):
            try:
                row = preprocess.normalise(pd.DataFrame([dict(application)])).iloc[0]
                canon = {k: _py(row[k]) for k in contract.INPUT_FIELDS if k in row.index}
            except Exception:  # noqa: BLE001 - malformed input still gets logged
                canon = {}

        def num(k, cast):
            v = canon.get(k)
            try:
                return cast(v) if v is not None and np.isfinite(float(v)) else None
            except (TypeError, ValueError, OverflowError):
                return None

        def cat(k):
            v = canon.get(k)
            return v if v in contract.FIELDS[k].allowed else None

        applicant = {'applicant_id': applicant_id, 'age': num('Age', int), 'gender': cat('Gender'),
                     'marital_status': cat('Marital_Status'), 'dependents': num('Dependents', int),
                     'employment_type': cat('Employment_Type')}
        try:
            app_json = json.dumps(application, default=str, sort_keys=True)[:20000]
        except Exception:  # noqa: BLE001
            app_json = repr(application)[:20000]
        loan = {'loan_id': loan_id, 'applicant_id': applicant_id, 'collateral_id': collateral_id,
                'loan_type': cat('Loan_Type'), 'amount': num('Loan_Amount', float),
                'tenure_months': num('Loan_Tenure', int), 'application_json': app_json}
        return applicant, loan

    # ---------- decide ----------
    def _prepare(self, application, rule=None) -> dict:
        app = application if isinstance(application, dict) else {}
        loan_id = _valid_id(app.get('Loan_ID'), 'Loan_ID') or f'LN-{uuid.uuid4().hex[:16]}'
        return {'application': application, 'app': app, 'loan_id': loan_id,
                'applicant_id': _valid_id(app.get('Applicant_ID'), 'Applicant_ID') or f'APP-{loan_id}',
                'collateral_id': _valid_id(app.get('Collateral_ID'), 'Collateral_ID'),
                'rule': rule if rule is not None else engine.evaluate(application, self.policy_version)}

    def _finish(self, ctx: dict, ml: dict | None, batch_id: str | None) -> dict:
        rule, loan_id = ctx['rule'], ctx['loan_id']
        applicant_id, collateral_id = ctx['applicant_id'], ctx['collateral_id']
        source, lock_note = 'RULE', None
        if rule['outcome'] == 'REJECT':
            ml = None                                   # FR-6: the ML layer is never consulted
            decision, confidence, reason = 'Rejected', 1.0, '; '.join(rule['reasons'])
        else:
            if self.repo is not None:
                try:
                    pre = self.repo.lock_precheck(loan_id, applicant_id, collateral_id)
                    lock_note = None if pre.acquired else pre.reason
                except Exception:  # noqa: BLE001 - the binding check happens again at persist time
                    lock_note = None
            rec = f'Model recommendation: {ml["sentence"]}'
            if rule['outcome'] == 'REVIEW':
                decision, confidence = 'Human Review', ml['confidence']
                reason = '; '.join(rule['reasons']) + '. ' + rec
            elif lock_note:
                decision, confidence, reason = 'Human Review', ml['confidence'], f'{lock_note} {rec}'
            elif ml['route'] == 'review':
                source = 'MODEL'
                decision, confidence = 'Human Review', ml['confidence']
                reason = (f'Low model confidence ({ml["confidence"]:.2f}; leaf support {ml["support"]}) - '
                          f'routed to human review. {rec}')
            else:
                source = 'MODEL'
                decision, confidence, reason = ml['predicted'], ml['confidence'], ml['sentence']

        out = {'loan_id': loan_id, 'applicant_id': applicant_id, 'decision': decision, 'confidence': confidence,
               'reason': reason, 'source': source, 'fired_rules': rule['fired_rules'],
               'tree_path': ml['path'] if ml else None, 'model_prediction': ml['predicted'] if ml else None,
               'confidence_ci': ml['ci'] if ml else None, 'leaf': ml['leaf'] if ml else None,
               'leaf_support': ml['support'] if ml else None, 'rule_evaluations': rule['evaluations'],
               'invalid_fields': rule.get('invalid_fields', []),
               'model_version': self.explainer.dt['version'] if ml else None,
               'policy_version': rule['policy_version'], 'audit_log_id': None, 'decision_id': None,
               'persisted': False, 'fallback_id': None, 'batch_id': batch_id}
        if self.repo is None:
            return out
        applicant, loan = self._records(ctx['application'], loan_id, applicant_id, collateral_id)
        record = {**{k: out[k] for k in ('decision', 'confidence', 'reason', 'source', 'fired_rules', 'tree_path',
                                         'model_prediction', 'model_version', 'policy_version', 'batch_id')},
                  'applicant': applicant, 'loan': loan, 'rule_evaluations': rule['evaluations']}
        try:
            res = self.repo.record_decision(record)
            out.update(decision=res['decision'], reason=res['reason'], audit_log_id=res['audit_log_id'],
                       decision_id=res['decision_id'], persisted=True, lock=res['lock'],
                       lock_latency_ms=res['latency_ms'])
        except Exception as e:  # noqa: BLE001 - FR-4 fallback: never crash, never lose the decision
            if out['decision'] == 'Approved':
                out['decision'] = 'Human Review'
                out['reason'] = ('Decision store unavailable, so the approval lock (FR-10) could not be verified; '
                                 'routed to human review. ' + out['reason'])
                record.update(decision=out['decision'], reason=out['reason'])
            out['fallback_id'] = self.fallback.write(record, e)
        return out

    def decide(self, application, batch_id: str | None = None) -> dict:
        ctx = self._prepare(application)
        ml = self._ml(ctx['app']) if ctx['rule']['outcome'] != 'REJECT' else None
        return self._finish(ctx, ml, batch_id)

    def decide_many(self, source, batch_id: str | None = None) -> pd.DataFrame:
        """Batch mode for evaluation: a CSV path or DataFrame of applications (one per row). Same decisions as
        decide() per row; normalisation and the tree run once for the batch, and every decision is still
        persisted in its own transaction."""
        df = pd.read_csv(source, dtype=str) if isinstance(source, (str, Path)) else source
        batch_id = batch_id or f'batch-{uuid.uuid4().hex[:8]}'
        apps = [{k: v for k, v in rec.items() if not (v is None or (isinstance(v, float) and np.isnan(v)))}
                for rec in df.to_dict('records')]
        rules = engine.evaluate_many(apps, self.policy_version)
        ctxs = [self._prepare(a, r) for a, r in zip(apps, rules)]
        need = [i for i, c in enumerate(ctxs) if c['rule']['outcome'] != 'REJECT']
        mls = {}
        if need:
            frame = preprocess.repair_invalid(preprocess.normalise(pd.DataFrame([apps[i] for i in need])),
                                              historical=False)
            mls = dict(zip(need, self.explainer.explain(frame)))
        rows = []
        for i, ctx in enumerate(ctxs):
            d = self._finish(ctx, mls.get(i), batch_id)
            rows.append({k: d[k] for k in ('loan_id', 'decision', 'confidence', 'reason', 'source', 'audit_log_id',
                                           'decision_id', 'persisted', 'model_prediction', 'fallback_id')}
                        | {'fired_rules': ','.join(d['fired_rules']), 'batch_id': batch_id})
        return pd.DataFrame(rows)

    def complete_review(self, review_id: int, officer: str, outcome: str, notes: str = '') -> dict:
        return self.repo.complete_review(review_id, officer, outcome, notes)


_default: DecisionPipeline | None = None


def decide(application) -> dict:
    global _default
    if _default is None:
        _default = DecisionPipeline()
    return _default.decide(application)
