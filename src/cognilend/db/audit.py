"""Append-only, hash-chained audit log (FR-4).

    hash = sha256(prev_hash + canonical_json(record)),  record = {seq, event_type, created_at, payload}

Hashing the whole record (not only the payload) means a change to the event type, the timestamp or the sequence
number is detected too. The first row chains from GENESIS (64 zeros). verify_chain() walks the log in seq order
and reports the first row whose sequence, back-link or hash does not match.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from cognilend.db.models import AuditLog

GENESIS = '0' * 64


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)


def compute_hash(prev_hash: str, seq: int, event_type: str, created_at: str, payload: dict) -> str:
    record = {'seq': seq, 'event_type': event_type, 'created_at': created_at, 'payload': payload}
    return hashlib.sha256((prev_hash + canonical_json(record)).encode('utf-8')).hexdigest()


def append(session: Session, event_type: str, payload: dict) -> AuditLog:
    """Append one event inside the caller's transaction. The caller's transaction must hold the write lock
    (SQLite: BEGIN IMMEDIATE; PostgreSQL: the table lock taken here)."""
    if session.get_bind().dialect.name == 'postgresql':
        session.execute(text('LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE'))
    last = session.execute(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1)).scalar_one_or_none()
    seq = 1 if last is None else last.seq + 1
    prev = GENESIS if last is None else last.hash
    created = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    payload = json.loads(canonical_json(payload))          # normalise types so verification sees the same JSON
    row = AuditLog(seq=seq, event_type=event_type, payload_json=canonical_json(payload), prev_hash=prev,
                   hash=compute_hash(prev, seq, event_type, created, payload), created_at=created)
    session.add(row)
    session.flush()
    return row


@dataclass
class ChainStatus:
    ok: bool
    checked: int
    first_broken_seq: int | None = None
    problem: str | None = None

    def __str__(self):
        return 'OK' if self.ok else f'BROKEN at seq {self.first_broken_seq}: {self.problem}'


def verify_chain(session: Session) -> ChainStatus:
    prev_hash, expected_seq, n = GENESIS, 1, 0
    for row in session.execute(select(AuditLog).order_by(AuditLog.seq)).scalars():
        n += 1
        if row.seq != expected_seq:
            return ChainStatus(False, n, expected_seq, f'sequence gap: expected {expected_seq}, found {row.seq}')
        if row.prev_hash != prev_hash:
            return ChainStatus(False, n, row.seq, 'prev_hash does not match the previous row')
        try:
            payload = json.loads(row.payload_json)
        except ValueError:
            return ChainStatus(False, n, row.seq, 'payload is not valid JSON')
        if compute_hash(prev_hash, row.seq, row.event_type, row.created_at, payload) != row.hash:
            return ChainStatus(False, n, row.seq, 'hash does not match the row contents')
        prev_hash, expected_seq = row.hash, expected_seq + 1
    return ChainStatus(True, n)
