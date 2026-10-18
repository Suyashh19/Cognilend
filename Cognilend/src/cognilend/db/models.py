"""SQLAlchemy models: applicants, loans, decisions, rule results, policies, models, audit log, review queue,
fairness reports and loan locks. Portable types only (SQLite in development, PostgreSQL-compatible).

audit_log is append-only: UPDATE and DELETE are blocked by database triggers (SQLite and PostgreSQL DDL below)
and by an ORM guard (before_update / before_delete raise).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (DDL, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
                        event)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Applicant(Base):
    __tablename__ = 'applicants'
    applicant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name_hash: Mapped[str | None] = mapped_column(String(64))
    dob: Mapped[datetime | None] = mapped_column(DateTime)
    age: Mapped[int | None] = mapped_column(Integer)
    gender: Mapped[str | None] = mapped_column(String(16))           # protected: audit only
    marital_status: Mapped[str | None] = mapped_column(String(16))   # protected: audit only
    dependents: Mapped[int | None] = mapped_column(Integer)
    employment_type: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Loan(Base):
    __tablename__ = 'loans'
    loan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    applicant_id: Mapped[str] = mapped_column(ForeignKey('applicants.applicant_id'), index=True)
    collateral_id: Mapped[str | None] = mapped_column(String(64), index=True)
    loan_type: Mapped[str | None] = mapped_column(String(16))
    amount: Mapped[float | None] = mapped_column(Float)
    tenure_months: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default='PENDING')    # PENDING|APPROVED|REJECTED|IN_REVIEW|CLOSED
    application_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Decision(Base):
    __tablename__ = 'decisions'
    decision_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loan_id: Mapped[str] = mapped_column(ForeignKey('loans.loan_id'), index=True)
    batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(8))                        # RULE | MODEL | HUMAN
    outcome: Mapped[str] = mapped_column(String(16))                      # Approved | Rejected | Human Review
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    fired_rules_json: Mapped[str] = mapped_column(Text, default='[]')
    tree_path_json: Mapped[str | None] = mapped_column(Text)
    model_prediction: Mapped[str | None] = mapped_column(String(16))
    model_version: Mapped[str | None] = mapped_column(String(32))
    policy_version: Mapped[str | None] = mapped_column(String(32))
    audit_seq: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RuleResult(Base):
    __tablename__ = 'rule_results'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey('decisions.decision_id'), index=True)
    rule_id: Mapped[str] = mapped_column(String(16), index=True)
    rule_type: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))     # fired | passed | exempt | not_applicable | not_evaluated
    fired: Mapped[bool] = mapped_column(Boolean)
    value: Mapped[str | None] = mapped_column(String(64))
    threshold: Mapped[str | None] = mapped_column(String(64))


class PolicyVersion(Base):
    __tablename__ = 'policy_versions'
    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    yaml_text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    activated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ModelRegistry(Base):
    __tablename__ = 'model_registry'
    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    artifact_path: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    metrics_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = 'audit_log'
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    event_type: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[str] = mapped_column(String(32))    # ISO text: part of the hashed record, must round-trip exactly


class ReviewQueue(Base):
    __tablename__ = 'review_queue'
    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    loan_id: Mapped[str] = mapped_column(ForeignKey('loans.loan_id'), index=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey('decisions.decision_id'))
    reason: Mapped[str] = mapped_column(Text)
    assigned_to: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default='OPEN')      # OPEN | CLOSED
    officer_decision: Mapped[str | None] = mapped_column(String(16))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)


class FairnessReport(Base):
    __tablename__ = 'fairness_reports'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(16))                         # rules_only | model_only | pipeline | ...
    group_name: Mapped[str] = mapped_column(String(32))                   # "group" is an SQL keyword
    subgroup: Mapped[str] = mapped_column(String(64))
    n: Mapped[int] = mapped_column(Integer)
    approval_rate: Mapped[float | None] = mapped_column(Float)
    di_ratio: Mapped[float | None] = mapped_column(Float)
    ci_low: Mapped[float | None] = mapped_column(Float)
    ci_high: Mapped[float | None] = mapped_column(Float)
    flagged: Mapped[bool] = mapped_column(Boolean)
    insufficient: Mapped[bool] = mapped_column(Boolean)
    versions_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LoanLock(Base):
    __tablename__ = 'loan_locks'
    lock_key: Mapped[str] = mapped_column(String(96), primary_key=True)   # applicant:<id> | collateral:<id>
    loan_id: Mapped[str] = mapped_column(ForeignKey('loans.loan_id'))
    acquired_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime)


# ---------- append-only enforcement ----------
_SQLITE_TRIGGERS = [
    "CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;",
    "CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;",
]
_PG_TRIGGER = [
    "CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$ "
    "BEGIN RAISE EXCEPTION 'audit_log is append-only'; END; $$ LANGUAGE plpgsql;",
    "CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log "
    "FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();",
]
for _sql in _SQLITE_TRIGGERS:
    event.listen(AuditLog.__table__, 'after_create', DDL(_sql).execute_if(dialect='sqlite'))
for _sql in _PG_TRIGGER:
    event.listen(AuditLog.__table__, 'after_create', DDL(_sql).execute_if(dialect='postgresql'))


class AppendOnlyError(RuntimeError):
    pass


@event.listens_for(AuditLog, 'before_update')
def _no_update(mapper, connection, target):
    raise AppendOnlyError('audit_log is append-only: UPDATE refused')


@event.listens_for(AuditLog, 'before_delete')
def _no_delete(mapper, connection, target):
    raise AppendOnlyError('audit_log is append-only: DELETE refused')
