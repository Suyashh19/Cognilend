"""F3: suggestions go to a separate table only; core tables and the audit chain are untouched."""
import pytest
from sqlalchemy import create_engine, func, inspect, select, text

from cognilend import demo
from cognilend.addons import suggestion_store as S
from cognilend.addons.max_amount import find_max_approvable_amount
from cognilend.db.models import Base
from cognilend.db.repository import Repository
from cognilend.pipeline import DecisionPipeline

B = demo.BASE
APPS = [demo.clean({**B, 'Loan_ID': 'SUG-FOIR', 'Applicant_ID': 'SUG-A1', 'Monthly_Income': 60000,
                    'Loan_Amount': 6_000_000, 'Collateral_Value': 9_000_000}),
        demo.clean({**B, 'Loan_ID': 'SUG-LTV', 'Applicant_ID': 'SUG-A2', 'Loan_Amount': 4_900_000,
                    'Collateral_Value': 5_000_000, 'Monthly_Income': 400000}),
        demo.clean({**B, 'Loan_ID': 'SUG-CIBIL', 'Applicant_ID': 'SUG-A3', 'CIBIL_Score': 600}),
        demo.clean({**demo.CASES['auto_reject'][1][0], 'Loan_ID': 'SUG-MODEL', 'Applicant_ID': 'SUG-A4'})]


@pytest.fixture
def repo(tmp_path):
    r = Repository(f'sqlite:///{(tmp_path / "s.db").as_posix()}')
    yield r
    r.engine.dispose()


def _core_counts(repo) -> dict:
    with repo.Session() as s:
        return {n: s.execute(select(func.count()).select_from(t)).scalar_one() for n, t in Base.metadata.tables.items()}


def test_separate_table_core_counts_and_chain_unchanged(repo):
    pipe = DecisionPipeline(repo=repo)
    decisions = [pipe.decide(a) for a in APPS]
    assert all(d['decision'] == 'Rejected' and d['persisted'] for d in decisions)
    before = _core_counts(repo)
    ids = []
    for d in decisions:
        app = S.application_for(d, repo.engine)
        assert app == next(a for a in APPS if a['Loan_ID'] == d['loan_id'])     # read back exactly
        ids.append(S.log_suggestion(find_max_approvable_amount(app), d['loan_id'], repo.engine))
    assert all(isinstance(i, int) for i in ids)
    assert _core_counts(repo) == before
    assert repo.verify_chain().ok
    with repo.engine.connect() as c:
        rows = c.execute(text('SELECT loan_id_ref, possible, binding_limit FROM amount_suggestions ORDER BY id')).all()
    assert [r[0] for r in rows] == [a['Loan_ID'] for a in APPS]
    assert [bool(r[1]) for r in rows] == [True, True, False, False]
    assert 'amount_suggestions' not in Base.metadata.tables                      # core schema untouched


def test_dropped_table_is_recreated_and_db_errors_never_raise(repo, tmp_path):
    res = find_max_approvable_amount(APPS[0])
    assert S.log_suggestion(res, 'X', repo.engine) == 1
    with repo.engine.begin() as c:
        c.execute(text('DROP TABLE amount_suggestions'))
    assert S.log_suggestion(res, 'X', repo.engine) == 1                           # additive create-if-not-exists
    broken = create_engine(f'sqlite:///{(tmp_path / "missing" / "dir" / "x.db").as_posix()}')
    assert S.log_suggestion(res, 'X', broken) is None
    assert S.log_suggestion(res, 'X', None) is None
    assert S.application_for({'loan_id': 'X'}, broken) is None
    assert repo.verify_chain().ok


def test_existing_repository_opens_a_db_that_has_the_extra_table(repo):
    S.ensure_table(repo.engine)
    again = Repository(engine=repo.engine)
    assert 'amount_suggestions' in inspect(repo.engine).get_table_names()
    assert again.verify_chain().ok


def test_not_applicable_is_not_logged(repo):
    assert S.log_suggestion({'applicable': False}, 'X', repo.engine) is None
