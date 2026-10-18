"""Best-effort log of max-amount suggestions in a SEPARATE table, plus read-only lookup of a decided application.

The table amount_suggestions has its own MetaData (not models.Base), so the core schema, models.py and every
existing table are untouched; it is created with an additive CREATE TABLE IF NOT EXISTS. Nothing here writes
to applicants, loans, decisions, rule_results, review_queue, audit_log or any other existing table.

log_suggestion() never raises: if the write fails the suggestion is still shown and nothing else is affected.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, MetaData, String, Table, text

metadata = MetaData()
amount_suggestions = Table(
    'amount_suggestions', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('loan_id_ref', String(64), index=True),          # plain reference, no FK into the core schema
    Column('requested_amount', Float),
    Column('max_amount', Float),
    Column('possible', Boolean),
    Column('binding_limit', String(32)),
    Column('model_version', String(32)),
    Column('policy_version', String(32)),
    Column('created_at', DateTime),
)


def ensure_table(engine) -> None:
    """Additive, idempotent: CREATE TABLE IF NOT EXISTS amount_suggestions (and its index)."""
    metadata.create_all(engine, checkfirst=True)


def log_suggestion(result: dict, loan_id_ref: str | None, engine) -> int | None:
    """Store one suggestion. Returns the new row id, or None when logging is skipped or fails (never raises)."""
    if engine is None or not result or not result.get('applicable'):
        return None
    try:
        ensure_table(engine)
        row = {'loan_id_ref': (str(loan_id_ref)[:64] if loan_id_ref else None),
               'requested_amount': result.get('requested_amount'), 'max_amount': result.get('max_amount'),
               'possible': bool(result.get('possible')), 'binding_limit': result.get('binding_limit'),
               'model_version': result.get('model_version'), 'policy_version': result.get('policy_version'),
               'created_at': datetime.now(timezone.utc)}
        with engine.begin() as conn:
            return int(conn.execute(amount_suggestions.insert().values(**row)).inserted_primary_key[0])
    except Exception:  # noqa: BLE001 - best effort by design
        return None


def application_for(decision: dict, engine=None, fallback=None) -> dict | None:
    """The application behind a decision returned by pipeline.decide, read-only: the fallback-log record when
    the DB write failed, else loans.application_json for its loan_id. None when it cannot be found."""
    try:
        fid = decision.get('fallback_id')
        if fid and fallback is not None:
            for item in fallback.pending():
                if item.get('fallback_id') == fid:
                    return json.loads(item['record']['loan']['application_json'])
        if engine is not None and decision.get('loan_id'):
            with engine.connect() as conn:
                raw = conn.execute(text('SELECT application_json FROM loans WHERE loan_id = :id'),
                                   {'id': decision['loan_id']}).scalar_one_or_none()
            if raw:
                app = json.loads(raw)
                return app if isinstance(app, dict) else None
    except Exception:  # noqa: BLE001 - lookup failure just means "unavailable"
        return None
    return None
