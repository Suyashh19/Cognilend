"""F2: maximum approvable amount search."""
import ast
from pathlib import Path

import pytest

from cognilend import demo
from cognilend.addons import max_amount as M
from cognilend.addons.dry_run import decisions_without_saving, evaluate_without_saving

B = demo.BASE
FOIR_CASE = demo.clean({**B, 'Monthly_Income': 60000, 'Loan_Amount': 6_000_000, 'Collateral_Value': 9_000_000})
LTV_CASE = demo.clean({**B, 'Loan_Amount': 4_900_000, 'Collateral_Value': 5_000_000, 'Monthly_Income': 400000})


@pytest.fixture(scope='module')
def rejected(test_set_apps):
    dec = decisions_without_saving(test_set_apps)
    return [a for a, d in zip(test_set_apps, dec) if d == 'Rejected']


@pytest.fixture(scope='module')
def eval_df(rejected):
    """Every REJECTED test-split application, each suggestion confirmed by the NORMAL persisting pipeline
    against a throwaway database."""
    from max_amount_eval import evaluate
    return evaluate(rejected)


@pytest.mark.parametrize('rule, change', [
    ('R01', {'Age': 20, 'Work_Experience': 1}),
    ('R02', {'Applicant_ID': 'FRAUD0001'}),
    ('R03', {'Age': 60}),
    ('R04', {'CIBIL_Score': 600}),
    ('R07', {'Monthly_Income': 12000, 'Loan_Amount': 200000, 'Loan_Type': 'Personal', 'Loan_Tenure': 36}),
])
def test_amount_independent_rejection_is_not_possible(rule, change):
    app = demo.clean({**B, **change})
    assert rule in evaluate_without_saving(app)['fired_rules']
    r = M.find_max_approvable_amount(app)
    assert r['applicable'] and r['possible'] is False
    assert r['blocking_rule'] == rule and r['binding_limit'] == f'RULE:{rule}' and rule in r['explanation']
    assert r['candidates_checked'] == 0                 # no search


def test_invalid_input_is_not_possible():
    r = M.find_max_approvable_amount(demo.clean(demo.CASES['malformed'][1][0]))
    assert r['possible'] is False and r['binding_limit'] == 'RULE:INPUT'


def test_rule_dependency_comes_from_the_fact_graph():
    dep = M.amount_dependent_rules()
    assert {k for k, v in dep.items() if v} == {'R05', 'R06', 'S03'}
    assert {'proposed_emi', 'foir', 'ltv', 'loan_to_income', 'ltv_cap'} <= M.amount_dependent_facts()
    assert 'age_at_maturity' not in M.amount_dependent_facts()


def test_foir_case():
    assert evaluate_without_saving(FOIR_CASE)['fired_rules'] == ['R05']
    r = M.find_max_approvable_amount(FOIR_CASE)
    assert r['possible'] and r['max_amount'] < FOIR_CASE['Loan_Amount']
    at = evaluate_without_saving({**FOIR_CASE, 'Loan_Amount': r['max_amount']})
    assert at['decision'] == 'Approved' and at['facts']['foir'] <= at['facts']['foir_limit']
    nxt = evaluate_without_saving({**FOIR_CASE, 'Loan_Amount': r['max_amount'] + 10000})
    assert nxt['decision'] != 'Approved'
    # +1 step is blocked by FOIR (R05 / S03 borderline) or by another limit, which is named
    blocked_by_foir = bool({'R05', 'S03'} & set(nxt['fired_rules']))
    assert blocked_by_foir == (r['binding_limit'] == 'FOIR')
    assert r['binding_limit'] in ('FOIR', 'LTV', 'MODEL') or r['binding_limit'].startswith('RULE:')


def test_foir_binding_cases_satisfy_foir(rejected, eval_df):
    """Test-set cases capped by FOIR: FOIR holds at the maximum and +1 step fires R05 or S03."""
    by_id = {a.get('Loan_ID'): a for a in rejected}
    foir = eval_df[eval_df['binding_limit'] == 'FOIR']
    assert len(foir) > 0
    for _, row in foir.iterrows():
        if row['possible'] is not True:
            continue
        app = by_id[row['loan_id']]
        at = evaluate_without_saving({**app, 'Loan_Amount': int(row['max_amount'])})
        assert at['facts']['foir'] <= at['facts']['foir_limit']
        nxt = evaluate_without_saving({**app, 'Loan_Amount': min(int(row['max_amount']) + 10000, row['requested'])})
        assert {'R05', 'S03'} & set(nxt['fired_rules'])


def test_ltv_case():
    assert evaluate_without_saving(LTV_CASE)['fired_rules'] == ['R06']
    r = M.find_max_approvable_amount(LTV_CASE)
    assert r['possible'] and r['binding_limit'] == 'LTV'
    cap = evaluate_without_saving({**LTV_CASE, 'Loan_Amount': r['max_amount']})['facts']['ltv_cap']
    assert r['max_amount'] <= cap * LTV_CASE['Collateral_Value']
    assert r['max_amount'] == 4_000_000                  # 80% of 50 lakh (30-75 lakh slab)


def test_model_rejection_searches():
    r = M.find_max_approvable_amount(demo.clean(demo.CASES['auto_reject'][1][0]))
    assert r['applicable'] and r['candidates_checked'] > 0 and r['binding_limit'] == 'MODEL'


@pytest.mark.parametrize('name', ['auto_approve', 'soft_review', 'low_confidence'])
def test_approved_or_review_not_applicable(name):
    app = demo.clean(demo.CASES[name][1][-1])
    r = M.find_max_approvable_amount(app)
    assert r == {'applicable': False, 'original_decision': evaluate_without_saving(app)['decision']}


def test_every_suggestion_is_approved_by_the_normal_pipeline(eval_df):
    pos = eval_df[eval_df['possible'] == True]  # noqa: E712
    assert len(pos) > 0
    rate = (pos['pipeline_decision_at_max'] == 'Approved').mean()
    print(f'\nrejected={len(eval_df)} possible={len(pos)} confirmed={rate:.1%}')
    assert rate == 1.0, pos[pos['pipeline_decision_at_max'] != 'Approved']
    assert (pos['max_amount'] < pos['requested']).all() and (pos['max_amount'] % 10000 == 0).all()


def test_runtime_under_one_second(eval_df):
    p50, p95 = eval_df['runtime_ms'].quantile([0.5, 0.95])
    print(f'\nruntime p50={p50:.0f} ms p95={p95:.0f} ms')
    assert p95 < 1000


def test_breakpoints_are_exhaustive(rejected, eval_df, monkeypatch):
    """Breakpoint-only candidates find the same maximum as a brute-force full step grid (non-monotonic tree)."""
    ids = set(eval_df.loc[eval_df['candidates_checked'] > 0, 'loan_id'])
    searched = [a for a in rejected if a.get('Loan_ID') in ids][:25]
    sample = searched + [FOIR_CASE, LTV_CASE]
    fast = [M.find_max_approvable_amount(a)['max_amount'] for a in sample]
    orig = M.settings
    monkeypatch.setattr(M, 'settings', lambda path=None: {**orig(path), 'max_grid_points': 10 ** 6})
    brute = [M.find_max_approvable_amount(a)['max_amount'] for a in sample]
    assert fast == brute


def test_protected_attributes_never_read():
    src = Path(M.__file__).read_text(encoding='utf-8') + Path(M.__file__).with_name('dry_run.py').read_text(
        encoding='utf-8')
    names = {n.value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not names & {'Gender', 'Marital_Status', 'gender', 'marital_status', 'age_band'}
    strip = lambda r: {k: v for k, v in r.items() if k != 'runtime_ms'}  # noqa: E731
    r1 = strip(M.find_max_approvable_amount(FOIR_CASE))
    r2 = strip(M.find_max_approvable_amount({**FOIR_CASE, 'Gender': 'Male', 'Marital_Status': 'Single'}))
    r3 = strip(M.find_max_approvable_amount({k: v for k, v in FOIR_CASE.items()
                                             if k not in ('Gender', 'Marital_Status')}))
    assert r1 == r2 == r3


def test_fmt_inr():
    assert M.fmt_inr(2790000) == '₹27,90,000'
    assert M.fmt_inr(500) == '₹500' and M.fmt_inr(100000) == '₹1,00,000' and M.fmt_inr(12345678) == '₹1,23,45,678'


def test_flag_reader(tmp_path):
    p = tmp_path / 'f.yaml'
    p.write_text('max_amount_suggestion: {enabled: false}\n', encoding='utf-8')
    assert M.enabled(p) is False
    assert M.enabled(tmp_path / 'missing.yaml') is False
    assert M.enabled() is True                            # shipped config
