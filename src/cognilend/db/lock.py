"""Lock layer blocking a second approval for the same applicant/collateral (FR-10, guide correction G1).

acquire_for_approval() runs INSIDE the transaction that records the approval, so check-and-acquire is atomic:
  - SQLite: every transaction starts with BEGIN IMMEDIATE (repository.make_engine), so writers are serialised.
  - PostgreSQL: the lock rows are read with SELECT ... FOR UPDATE, and lock_key is a primary key, so two
    concurrent inserts of the same key cannot both succeed (the loser gets IntegrityError -> treated as held).
If an active lock on the applicant or the collateral belongs to another loan, the approval is refused and the
caller downgrades the decision to Human Review with the returned reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from cognilend.db.models import LoanLock, utcnow


def lock_keys(applicant_id: str | None, collateral_id: str | None) -> list[str]:
    keys = []
    if applicant_id:
        keys.append(f'applicant:{applicant_id}')
    if collateral_id:
        keys.append(f'collateral:{collateral_id}')
    return keys


@dataclass
class LockResult:
    acquired: bool
    keys: list[str] = field(default_factory=list)
    held_by: dict = field(default_factory=dict)       # key -> loan_id holding it

    @property
    def reason(self) -> str:
        if self.acquired:
            return ''
        parts = [f'{k.split(":")[0]} {k.split(":", 1)[1]} already has an approved active loan {v}'
                 for k, v in self.held_by.items()]
        return 'Lock (FR-10): ' + '; '.join(parts) + '. Second approval blocked; sent to human review.'


def held_by_other(session: Session, keys: list[str], loan_id: str, for_update: bool = False) -> dict:
    if not keys:
        return {}
    q = select(LoanLock).where(LoanLock.lock_key.in_(keys))
    if for_update:
        q = q.with_for_update()
    return {r.lock_key: r.loan_id for r in session.execute(q).scalars()
            if r.released_at is None and r.loan_id != loan_id}


def acquire_for_approval(session: Session, loan_id: str, applicant_id: str | None,
                         collateral_id: str | None) -> LockResult:
    keys = lock_keys(applicant_id, collateral_id)
    held = held_by_other(session, keys, loan_id, for_update=True)
    if held:
        return LockResult(False, keys, held)
    now = utcnow()
    for k in keys:
        row = session.get(LoanLock, k)
        if row is None:
            session.add(LoanLock(lock_key=k, loan_id=loan_id, acquired_at=now, released_at=None))
        else:                                           # released earlier, or already ours
            row.loan_id, row.acquired_at, row.released_at = loan_id, now, None
    session.flush()                                     # PostgreSQL: duplicate key raises here
    return LockResult(True, keys)


def release(session: Session, loan_id: str) -> int:
    """Release every lock held by a loan (e.g. loan closed or cancelled). Returns how many were released."""
    rows = session.execute(select(LoanLock).where(LoanLock.loan_id == loan_id,
                                                  LoanLock.released_at.is_(None))).scalars().all()
    for r in rows:
        r.released_at = utcnow()
    return len(rows)
