import json
import re
import threading

import numpy as np
import pytest
from sqlalchemy import select, text

from cognilend import config
from cognilend.db import audit, lock
from cognilend.db.models import AppendOnlyError, AuditLog, Decision, Loan, ReviewQueue, RuleResult
from cognilend.db.repository import FallbackLog, Repository
from cognilend.pipeline import DecisionPipeline

GOOD = dict(Age=35, Gender='Female', Marital_Status='Married', Dependents=1, Employment_Type='Salaried',
            Work_Experience=10, Monthly_Income=150000, Existing_EMI=0, CIBIL_Score=800, Loan_Type='Home',
            Loan_Amount=3_000_000, Loan_Tenure=240, Collateral_Value=5_000_000, Property_Area='Urban')


@pytest.fixture
def repo(tmp_path):
    r = Repository(f'sqlite:///{(tmp_path / "t.db").as_posix()}')
    yield r
    r.engine.dispose()


@pytest.fixture
def pipe(repo, tmp_path):
    return DecisionPipeline(repo=repo, fallback=FallbackLog(tmp_path / 'fallback.jsonl'))


def _events(repo, n=6):
    with repo.Session.begin() as s:
        for i in range(n):
            audit.append(s, 'test', {'i': i, 'note': f'event {i}'})


# ---------- hash chain ----------
def test_chain_verifies_and_links(repo):
    _events(repo)
    status = repo.verify_chain()
    assert status.ok and status.checked == 6 and str(status) == 'OK'
    with repo.Session() as s:
        rows = s.execute(select(AuditLog).order_by(AuditLog.seq)).scalars().all()
    assert rows[0].prev_hash == audit.GENESIS
    assert all(b.prev_hash == a.hash for a, b in zip(rows, rows[1:]))


def _drop_triggers(repo):
    with repo.engine.begin() as c:
        c.exec_driver_sql('DROP TRIGGER audit_log_no_update')
        c.exec_driver_sql('DROP TRIGGER audit_log_no_delete')


@pytest.mark.parametrize('column,value', [('payload_json', '{"i":3,"note":"edited"}'), ('event_type', 'forged'),
                                          ('created_at', '2020-01-01T00:00:00.000000+00:00')])
def test_tampering_one_row_is_reported_at_that_row(repo, column, value):
    _events(repo)
    _drop_triggers(repo)                    # simulate someone with direct database access
    with repo.engine.begin() as c:
        c.execute(text(f'UPDATE audit_log SET {column} = :v WHERE seq = 4'), {'v': value})
    status = repo.verify_chain()
    assert not status.ok and status.first_broken_seq == 4


def test_rewriting_a_hash_breaks_the_next_link(repo):
    _events(repo)
    _drop_triggers(repo)
    with repo.engine.begin() as c:
        c.execute(text("UPDATE audit_log SET payload_json = '{}' WHERE seq = 2"))
        row = c.execute(text('SELECT prev_hash, event_type, created_at FROM audit_log WHERE seq = 2')).one()
        forged = audit.compute_hash(row.prev_hash, 2, row.event_type, row.created_at, {})
        c.execute(text('UPDATE audit_log SET hash = :h WHERE seq = 2'), {'h': forged})
    status = repo.verify_chain()
    assert status.first_broken_seq == 3 and 'prev_hash' in status.problem


def test_deleted_row_is_reported_as_gap(repo):
    _events(repo)
    _drop_triggers(repo)
    with repo.engine.begin() as c:
        c.exec_driver_sql('DELETE FROM audit_log WHERE seq = 3')
    status = repo.verify_chain()
    assert status.first_broken_seq == 3 and 'gap' in status.problem


def test_database_trigger_blocks_update_and_delete(repo):
    _events(repo, 2)
    for sql in ("UPDATE audit_log SET payload_json = '{}' WHERE seq = 1", 'DELETE FROM audit_log WHERE seq = 1'):
        with pytest.raises(Exception, match='append-only'):
            with repo.engine.begin() as c:
                c.exec_driver_sql(sql)
    assert repo.verify_chain().ok


def test_orm_guard_blocks_update_and_delete(repo):
    _events(repo, 2)
    with pytest.raises(AppendOnlyError):
        with repo.Session.begin() as s:
            s.get(AuditLog, 1).payload_json = '{}'
    with pytest.raises(AppendOnlyError):
        with repo.Session.begin() as s:
            s.delete(s.get(AuditLog, 2))
    assert repo.verify_chain().ok


# ---------- decisions are fully persisted ----------
def test_decision_persists_everything_in_one_transaction(pipe, repo):
    d = pipe.decide({**GOOD, 'Loan_ID': 'L1', 'Applicant_ID': 'A1'})
    assert d['persisted'] and d['audit_log_id'] and d['decision'] == 'Approved'
    with repo.Session() as s:
        dec = s.get(Decision, d['decision_id'])
        assert dec.audit_seq == d['audit_log_id'] and json.loads(dec.tree_path_json)
        assert s.execute(select(RuleResult).where(RuleResult.decision_id == dec.decision_id)).scalars().all()
        payload = json.loads(s.get(AuditLog, d['audit_log_id']).payload_json)
        assert payload['decision_id'] == dec.decision_id and payload['outcome'] == 'Approved'
        assert s.get(Loan, 'L1').status == 'APPROVED'
    assert repo.verify_chain().ok


def test_versions_registered(repo, pipe):
    assert pipe.versions['policy_version'] == 'v1' and pipe.versions['model_version'] == 'dt_v1'
    with repo.engine.connect() as c:
        assert c.exec_driver_sql('SELECT COUNT(*) FROM policy_versions').scalar() == 1
        assert c.exec_driver_sql('SELECT COUNT(*) FROM model_registry').scalar() == 3


# ---------- FR-10 lock ----------
def test_second_approval_same_collateral_goes_to_review(pipe):
    a = pipe.decide({**GOOD, 'Loan_ID': 'L1', 'Applicant_ID': 'A1', 'Collateral_ID': 'PROP-9'})
    b = pipe.decide({**GOOD, 'Loan_ID': 'L2', 'Applicant_ID': 'A2', 'Collateral_ID': 'PROP-9'})
    assert a['decision'] == 'Approved' and b['decision'] == 'Human Review' and 'PROP-9' in b['reason']


def test_second_approval_same_applicant_goes_to_review(pipe):
    pipe.decide({**GOOD, 'Loan_ID': 'L1', 'Applicant_ID': 'A1'})
    b = pipe.decide({**GOOD, 'Loan_ID': 'L2', 'Applicant_ID': 'A1'})
    assert b['decision'] == 'Human Review' and 'applicant A1' in b['reason']


def test_released_lock_allows_new_approval(pipe, repo):
    pipe.decide({**GOOD, 'Loan_ID': 'L1', 'Applicant_ID': 'A1', 'Collateral_ID': 'P1'})
    with repo.Session.begin() as s:
        assert lock.release(s, 'L1') == 2
    assert pipe.decide({**GOOD, 'Loan_ID': 'L2', 'Applicant_ID': 'A1', 'Collateral_ID': 'P1'})['decision'] == 'Approved'


def test_50_concurrent_approvals_same_collateral_exactly_one(pipe, repo):
    pipe.explainer                                  # load artefacts before the race
    n = 50
    barrier = threading.Barrier(n)
    results, errors = [None] * n, []

    def worker(i):
        try:
            barrier.wait()
            results[i] = pipe.decide({**GOOD, 'Loan_ID': f'C{i:03d}', 'Applicant_ID': f'APP{i:03d}',
                                      'Collateral_ID': 'FLAT-42'})
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    outcomes = [r['decision'] for r in results]
    assert outcomes.count('Approved') == 1 and outcomes.count('Human Review') == n - 1
    assert all(r['persisted'] for r in results)
    with repo.Session() as s:
        approved = s.execute(select(Loan).where(Loan.status == 'APPROVED')).scalars().all()
        assert len(approved) == 1
    assert repo.verify_chain().ok
    lat = np.array([r['lock_latency_ms'] for r in results])
    report = {'threads': n, 'approved': 1, 'review': n - 1, 'p50_ms': float(np.percentile(lat, 50)),
              'p95_ms': float(np.percentile(lat, 95)), 'max_ms': float(lat.max()),
              'note': 'time inside record_decision (wait for BEGIN IMMEDIATE + lock check + writes + commit)'}
    out = config.ROOT / config.load('settings')['paths']['reports'] / 'lock_latency.json'
    out.write_text(json.dumps(report, indent=2))
    print('lock latency:', report)


# ---------- DB failure ----------
class _BrokenRepo(Repository):
    def record_decision(self, d):
        raise RuntimeError('disk I/O error (injected)')


def test_db_failure_returns_decision_and_writes_fallback(tmp_path):
    broken = _BrokenRepo(f'sqlite:///{(tmp_path / "b.db").as_posix()}')
    fb = FallbackLog(tmp_path / 'fallback.jsonl')
    p = DecisionPipeline(repo=broken, fallback=fb)
    apps = [{**GOOD, 'Loan_ID': f'F{i}'} for i in range(5)] + [{**GOOD, 'Loan_ID': 'F9', 'CIBIL_Score': 600}, None]
    outs = [p.decide(a) for a in apps]
    assert all(o['decision'] in ('Approved', 'Rejected', 'Human Review') for o in outs)
    assert all(not o['persisted'] and o['fallback_id'] for o in outs)
    # an approval whose lock cannot be checked is not released as an approval
    assert outs[0]['decision'] == 'Human Review' and 'could not be verified' in outs[0]['reason']
    assert outs[5]['decision'] == 'Rejected'
    pending = fb.pending()
    assert len(pending) == len(apps) and {x['fallback_id'] for x in pending} == {o['fallback_id'] for o in outs}

    good_repo = Repository(f'sqlite:///{(tmp_path / "ok.db").as_posix()}')
    res = fb.replay(good_repo)
    assert res == {'replayed': len(apps), 'still_pending': 0} and fb.pending() == []
    assert good_repo.count(Decision) == len(apps) and good_repo.verify_chain().ok
    broken.engine.dispose()
    good_repo.engine.dispose()


def test_replay_keeps_failures_pending(tmp_path):
    fb = FallbackLog(tmp_path / 'fallback.jsonl')
    broken = _BrokenRepo(f'sqlite:///{(tmp_path / "b.db").as_posix()}')
    DecisionPipeline(repo=broken, fallback=fb).decide({**GOOD, 'Loan_ID': 'X1'})
    assert fb.replay(broken) == {'replayed': 0, 'still_pending': 1} and len(fb.pending()) == 1
    broken.engine.dispose()


# ---------- human review ----------
def test_complete_review_records_human_decision_with_audit_event(pipe, repo):
    d = pipe.decide({**GOOD, 'Loan_ID': 'R1', 'Applicant_ID': 'H1', 'CIBIL_Score': -1})
    assert d['decision'] == 'Human Review'
    with repo.Session() as s:
        rq = s.execute(select(ReviewQueue).where(ReviewQueue.loan_id == 'R1')).scalar_one()
    res = pipe.complete_review(rq.review_id, 'officer-7', 'Approved', 'salary slips verified')
    assert res['ok']
    with repo.Session() as s:
        dec = s.get(Decision, res['decision_id'])
        assert dec.source == 'HUMAN' and dec.outcome == 'Approved' and dec.audit_seq == res['audit_log_id']
        assert s.get(AuditLog, res['audit_log_id']).event_type == 'human_review_completed'
        assert s.get(ReviewQueue, rq.review_id).status == 'CLOSED' and s.get(Loan, 'R1').status == 'APPROVED'
    with pytest.raises(ValueError):
        pipe.complete_review(rq.review_id, 'officer-7', 'Approved')        # already closed
    assert repo.verify_chain().ok


def test_officer_cannot_approve_second_loan_on_locked_collateral(pipe, repo):
    pipe.decide({**GOOD, 'Loan_ID': 'K1', 'Applicant_ID': 'K1A', 'Collateral_ID': 'CAR-1'})
    d = pipe.decide({**GOOD, 'Loan_ID': 'K2', 'Applicant_ID': 'K2A', 'Collateral_ID': 'CAR-1'})
    assert d['decision'] == 'Human Review'
    with repo.Session() as s:
        rq = s.execute(select(ReviewQueue).where(ReviewQueue.loan_id == 'K2')).scalar_one()
    res = pipe.complete_review(rq.review_id, 'officer-7', 'Approved')
    assert not res['ok'] and 'CAR-1' in res['reason']
    assert pipe.complete_review(rq.review_id, 'officer-7', 'Rejected', 'collateral already pledged')['ok']


# ---------- SQL examples ----------
def test_every_audit_query_runs(pipe, repo):
    d = pipe.decide({**GOOD, 'Loan_ID': 'Q1', 'Applicant_ID': 'QA'})
    pipe.decide({**GOOD, 'Loan_ID': 'Q2', 'Applicant_ID': 'QB', 'CIBIL_Score': 600}, batch_id='qb')
    sql = (config.ROOT / 'docs' / 'audit_queries.sql').read_text(encoding='utf-8')
    statements = [s.strip() for s in re.sub(r'--[^\n]*', '', sql).split(';') if s.strip()]
    assert len(statements) == 11
    params = {'applicant_id': 'QA', 'loan_id': 'Q1', 'batch_id': 'qb', 'applications_in': 1}
    with repo.engine.connect() as c:
        results = [c.execute(text(s), {k: v for k, v in params.items() if f':{k}' in s}).fetchall()
                   for s in statements]
    assert results[0][0].loan_id == 'Q1'                       # Q1 decisions for applicant
    assert results[1] and results[1][0].rule_id == 'R04'       # Q2 rejections by rule
    assert results[2][0].coverage == 1.0                       # Q3 coverage
    assert results[3] == []                                    # Q4 no undecided loans
    assert results[4][0].hash                                  # Q5 trail with hash
