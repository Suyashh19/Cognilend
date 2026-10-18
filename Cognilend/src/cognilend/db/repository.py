"""Data-access layer over the models.

record_decision() writes everything about one decision in ONE transaction: applicant, loan, the lock check for
approvals (downgrade to Human Review if the applicant or collateral already has an approved active loan),
decision, rule results, review-queue entry and the hash-chained audit event. Either all of it is stored or none.

FallbackLog keeps decisions whose DB write failed (one JSON line each) so they can be replayed later; nothing is
dropped silently.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from cognilend import config
from cognilend.db import audit, lock
from cognilend.db.models import (Applicant, Base, Decision, Loan, ModelRegistry, PolicyVersion, ReviewQueue,
                                 RuleResult, utcnow)

STATUS = {'Approved': 'APPROVED', 'Rejected': 'REJECTED', 'Human Review': 'IN_REVIEW'}


def make_engine(url: str | None = None):
    s = config.load('settings')
    url = url or s['paths']['database_url']
    if url.startswith('sqlite:///') and not url.startswith('sqlite:///:memory:'):
        p = Path(url.replace('sqlite:///', '', 1))
        if not p.is_absolute():
            p = config.ROOT / p
            url = f'sqlite:///{p.as_posix()}'
        p.parent.mkdir(parents=True, exist_ok=True)
    db = s['database']
    if url.startswith('sqlite'):
        engine = create_engine(url, connect_args={'timeout': db['busy_timeout_s'], 'check_same_thread': False},
                               pool_size=db['pool_size'], max_overflow=db['max_overflow'], pool_timeout=120)

        @event.listens_for(engine, 'connect')
        def _connect(dbapi_conn, _):
            dbapi_conn.isolation_level = None             # let SQLAlchemy's 'begin' hook issue BEGIN itself
            cur = dbapi_conn.cursor()
            cur.execute('PRAGMA journal_mode=WAL')
            cur.execute('PRAGMA synchronous=NORMAL')
            cur.execute('PRAGMA foreign_keys=ON')
            cur.close()

        @event.listens_for(engine, 'begin')
        def _begin(conn):
            conn.exec_driver_sql('BEGIN IMMEDIATE')       # take the write lock at the start: serialises writers
    else:
        engine = create_engine(url, pool_size=db['pool_size'], max_overflow=db['max_overflow'])
    return engine


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _s(v) -> str | None:
    return None if v is None else str(v)[:64]


class Repository:
    def __init__(self, url: str | None = None, engine=None):
        self.engine = engine or make_engine(url)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    # ---------- versions ----------
    def register_versions(self, policy_version: str = 'v1') -> dict:
        s = config.load('settings')
        pol_path = config.CONFIG_DIR / f'policies_{policy_version}.yaml'
        out = {'policy_version': policy_version}
        with self.Session.begin() as session:
            if session.get(PolicyVersion, policy_version) is None:
                txt = pol_path.read_text(encoding='utf-8')
                session.add(PolicyVersion(version=policy_version, yaml_text=txt,
                                          sha256=hashlib.sha256(txt.encode()).hexdigest()))
                audit.append(session, 'policy_activated', {'version': policy_version, 'sha256': _sha256_file(pol_path)})
            for key, sub in (('model', 'models'), ('preprocess', 'encoders'), ('confidence', 'models')):
                version = s[key]['version']
                path = config.ROOT / s['paths'][sub] / f'{version}.joblib'
                out[f'{key}_version'] = version
                if path.exists() and session.get(ModelRegistry, version) is None:
                    metrics = config.ROOT / s['paths']['reports'] / 'dt_metrics.json'
                    session.add(ModelRegistry(version=version, artifact_path=str(path.relative_to(config.ROOT)),
                                              sha256=_sha256_file(path),
                                              metrics_json=metrics.read_text() if key == 'model' and metrics.exists()
                                              else None))
                    audit.append(session, 'model_registered', {'version': version, 'sha256': _sha256_file(path)})
        return out

    # ---------- lock pre-check (read only; the binding check is inside record_decision) ----------
    def lock_precheck(self, loan_id: str, applicant_id: str | None, collateral_id: str | None) -> lock.LockResult:
        keys = lock.lock_keys(applicant_id, collateral_id)
        with self.Session() as session:
            held = lock.held_by_other(session, keys, loan_id)
        return lock.LockResult(not held, keys, held)

    # ---------- the one write path for decisions ----------
    def record_decision(self, d: dict) -> dict:
        """Persist a decision atomically. Returns {decision, reason, decision_id, audit_log_id, lock, latency_ms}.
        An approval whose lock is held by another loan is downgraded to Human Review before it is stored."""
        t0 = time.perf_counter()
        app, ln = d['applicant'], d['loan']
        with self.Session.begin() as session:
            session.merge(Applicant(**app))
            loan = session.get(Loan, ln['loan_id'])
            if loan is None:
                loan = Loan(**ln)
                session.add(loan)
            else:
                for k, v in ln.items():
                    setattr(loan, k, v)
            session.flush()

            outcome, reason, lock_info = d['decision'], d['reason'], None
            if outcome == 'Approved':
                res = lock.acquire_for_approval(session, ln['loan_id'], ln['applicant_id'], ln.get('collateral_id'))
                lock_info = {'acquired': res.acquired, 'keys': res.keys, 'held_by': res.held_by}
                if not res.acquired:
                    outcome, reason = 'Human Review', res.reason + ' Original decision: ' + reason
            loan.status = STATUS[outcome]

            dec = Decision(loan_id=ln['loan_id'], batch_id=d.get('batch_id'), source=d['source'], outcome=outcome,
                           confidence=d.get('confidence'), reason=reason,
                           fired_rules_json=json.dumps(d.get('fired_rules', [])),
                           tree_path_json=json.dumps(d['tree_path'], default=str) if d.get('tree_path') else None,
                           model_prediction=d.get('model_prediction'), model_version=d.get('model_version'),
                           policy_version=d.get('policy_version'))
            session.add(dec)
            session.flush()
            for e in d.get('rule_evaluations', []):
                session.add(RuleResult(decision_id=dec.decision_id, rule_id=e['rule_id'], rule_type=e['type'],
                                       status=e['status'], fired=e['status'] == 'fired', value=_s(e.get('value')),
                                       threshold=_s(e.get('threshold'))))
            if outcome == 'Human Review':
                session.add(ReviewQueue(loan_id=ln['loan_id'], decision_id=dec.decision_id, reason=reason))
            row = audit.append(session, 'decision', {
                'decision_id': dec.decision_id, 'loan_id': ln['loan_id'], 'applicant_id': ln['applicant_id'],
                'source': d['source'], 'outcome': outcome, 'confidence': d.get('confidence'), 'reason': reason,
                'fired_rules': d.get('fired_rules', []), 'model_version': d.get('model_version'),
                'policy_version': d.get('policy_version'), 'lock': lock_info, 'batch_id': d.get('batch_id')})
            dec.audit_seq = row.seq
        return {'decision': outcome, 'reason': reason, 'decision_id': dec.decision_id, 'audit_log_id': row.seq,
                'lock': lock_info, 'latency_ms': (time.perf_counter() - t0) * 1000}

    # ---------- human review ----------
    def complete_review(self, review_id: int, officer: str, outcome: str, notes: str = '') -> dict:
        """Record the officer's decision as a separate HUMAN decision with its own audit event."""
        if outcome not in ('Approved', 'Rejected'):
            raise ValueError("officer outcome must be 'Approved' or 'Rejected'")
        with self.Session.begin() as session:
            rq = session.get(ReviewQueue, review_id)
            if rq is None or rq.status != 'OPEN':
                raise ValueError(f'review {review_id} is not open')
            loan = session.get(Loan, rq.loan_id)
            if outcome == 'Approved':
                res = lock.acquire_for_approval(session, loan.loan_id, loan.applicant_id, loan.collateral_id)
                if not res.acquired:
                    row = audit.append(session, 'human_review_blocked', {
                        'review_id': review_id, 'loan_id': loan.loan_id, 'officer': officer, 'reason': res.reason})
                    return {'ok': False, 'reason': res.reason, 'audit_log_id': row.seq}
            dec = Decision(loan_id=loan.loan_id, source='HUMAN', outcome=outcome, confidence=None,
                           reason=f'Officer {officer}: {notes}'.strip(), fired_rules_json='[]')
            session.add(dec)
            session.flush()
            rq.status, rq.officer_decision, rq.notes, rq.assigned_to, rq.closed_at = \
                'CLOSED', outcome, notes, officer, utcnow()
            loan.status = STATUS[outcome]
            row = audit.append(session, 'human_review_completed', {
                'review_id': review_id, 'decision_id': dec.decision_id, 'loan_id': loan.loan_id,
                'officer': officer, 'outcome': outcome, 'notes': notes,
                'model_decision_id': rq.decision_id})
            dec.audit_seq = row.seq
        return {'ok': True, 'decision_id': dec.decision_id, 'audit_log_id': row.seq}

    # ---------- reads ----------
    def verify_chain(self) -> audit.ChainStatus:
        with self.Session() as session:
            return audit.verify_chain(session)

    def list_reviews(self, status: str = 'OPEN', limit: int = 200) -> list[dict]:
        with self.Session() as session:
            q = (select(ReviewQueue, Decision, Loan).join(Decision, Decision.decision_id == ReviewQueue.decision_id)
                 .join(Loan, Loan.loan_id == ReviewQueue.loan_id).where(ReviewQueue.status == status)
                 .order_by(ReviewQueue.created_at.desc(), ReviewQueue.review_id.desc()).limit(limit))
            return [{'review_id': r.review_id, 'loan_id': r.loan_id, 'applicant_id': ln.applicant_id,
                     'loan_type': ln.loan_type, 'amount': ln.amount, 'reason': r.reason,
                     'model_recommendation': d.model_prediction, 'confidence': d.confidence,
                     'source': d.source, 'created_at': r.created_at, 'officer_decision': r.officer_decision,
                     'notes': r.notes} for r, d, ln in session.execute(q).all()]

    def decision_history(self, term: str, limit: int = 500) -> list[dict]:
        """Decisions whose loan id or applicant id equals / starts with term, oldest first."""
        term = (term or '').strip()
        with self.Session() as session:
            q = (select(Decision, Loan).join(Loan, Loan.loan_id == Decision.loan_id)
                 .where((Loan.loan_id.like(f'{term}%')) | (Loan.applicant_id.like(f'{term}%')))
                 .order_by(Decision.created_at, Decision.decision_id).limit(limit))
            return [{'decision_id': d.decision_id, 'loan_id': d.loan_id, 'applicant_id': ln.applicant_id,
                     'source': d.source, 'outcome': d.outcome, 'confidence': d.confidence, 'reason': d.reason,
                     'fired_rules': json.loads(d.fired_rules_json or '[]'), 'policy_version': d.policy_version,
                     'model_version': d.model_version, 'audit_seq': d.audit_seq, 'created_at': d.created_at,
                     'loan_status': ln.status} for d, ln in session.execute(q).all()]

    def audit_event(self, seq: int) -> dict | None:
        from cognilend.db.models import AuditLog
        with self.Session() as session:
            a = session.get(AuditLog, seq)
            return None if a is None else {'seq': a.seq, 'event_type': a.event_type,
                                           'payload': json.loads(a.payload_json), 'prev_hash': a.prev_hash,
                                           'hash': a.hash, 'created_at': a.created_at}

    def versions(self) -> dict:
        with self.Session() as session:
            pol = [{'version': p.version, 'sha256': p.sha256, 'activated_at': p.activated_at}
                   for p in session.execute(select(PolicyVersion)).scalars()]
            mod = [{'version': m.version, 'artifact_path': m.artifact_path, 'sha256': m.sha256,
                    'created_at': m.created_at} for m in session.execute(select(ModelRegistry)).scalars()]
        return {'policies': pol, 'models': mod}

    def fairness_runs(self) -> list[dict]:
        from cognilend.db.models import FairnessReport
        with self.Session() as session:
            q = (select(FairnessReport.run_id, FairnessReport.mode, func.max(FairnessReport.created_at))
                 .group_by(FairnessReport.run_id, FairnessReport.mode)
                 .order_by(func.max(FairnessReport.created_at).desc()))
            return [{'run_id': r, 'mode': m, 'created_at': t} for r, m, t in session.execute(q).all()]

    def fairness_rows(self, run_id: str) -> list[dict]:
        from cognilend.db.models import FairnessReport
        with self.Session() as session:
            q = select(FairnessReport).where(FairnessReport.run_id == run_id).order_by(FairnessReport.id)
            return [{'mode': f.mode, 'group': f.group_name, 'subgroup': f.subgroup, 'n': f.n,
                     'approval_rate': f.approval_rate, 'di': f.di_ratio, 'ci_low': f.ci_low, 'ci_high': f.ci_high,
                     'flagged': f.flagged, 'insufficient': f.insufficient, 'versions': f.versions_json,
                     'created_at': f.created_at} for f in session.execute(q).scalars()]

    def summary(self) -> dict:
        with self.Session() as session:
            by = session.execute(select(Decision.outcome, func.count()).group_by(Decision.outcome)).all()
            open_reviews = session.execute(select(func.count()).select_from(ReviewQueue)
                                           .where(ReviewQueue.status == 'OPEN')).scalar_one()
        return {'decisions': {o: n for o, n in by}, 'open_reviews': open_reviews}

    def count(self, model, **filters) -> int:
        with self.Session() as session:
            q = select(func.count()).select_from(model)
            for k, v in filters.items():
                q = q.where(getattr(model, k) == v)
            return session.execute(q).scalar_one()


class FallbackLog:
    """Append-only JSONL of decisions that could not be written to the database."""

    _lock = threading.Lock()

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or config.ROOT / config.load('settings')['paths']['fallback_log'])

    def write(self, record: dict, error: Exception) -> str:
        fid = str(uuid.uuid4())
        line = json.dumps({'fallback_id': fid, 'failed_at': datetime.now(timezone.utc).isoformat(),
                           'error': f'{type(error).__name__}: {error}', 'record': record}, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
                f.flush()
        return fid

    def pending(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding='utf-8').splitlines() if x.strip()]

    def replay(self, repo: Repository) -> dict:
        """Write pending records to the DB. Successes move to <file>.replayed; failures stay pending."""
        with self._lock:
            items = self.pending()
            done, failed = [], []
            for it in items:
                try:
                    res = repo.record_decision(it['record'])
                    done.append({**it, 'replayed_at': datetime.now(timezone.utc).isoformat(),
                                 'audit_log_id': res['audit_log_id']})
                except Exception as e:  # noqa: BLE001 - keep it pending
                    failed.append({**it, 'last_replay_error': f'{type(e).__name__}: {e}'})
            if done:
                with open(self.path.with_suffix('.replayed.jsonl'), 'a', encoding='utf-8') as f:
                    for it in done:
                        f.write(json.dumps(it, default=str) + '\n')
            self.path.write_text(''.join(json.dumps(it, default=str) + '\n' for it in failed), encoding='utf-8')
        return {'replayed': len(done), 'still_pending': len(failed)}
