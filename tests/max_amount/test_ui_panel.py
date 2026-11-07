"""F4: the 'See maximum approvable amount' button under a Rejected decision.

The one-time side-by-side checks against the pre-feature page (Approved / Review and flag-off screens unchanged)
were removed in v2; their results are recorded in evidence/max_amount/ and the code is in release v1.0-legacy."""
import json

import pytest
from streamlit.testing.v1 import AppTest

from conftest import ROOT
from cognilend import demo
from cognilend.max_amount import suggestion_store

PAGE = ROOT / 'app' / 'views' / 'new_application.py'
LABEL = 'See maximum approvable amount'
FOIR_JSON = demo.clean({**demo.BASE, 'Monthly_Income': 60000, 'Loan_Amount': 6_000_000, 'Collateral_Value': 9_000_000})


@pytest.fixture
def flag(tmp_path, monkeypatch):
    def set_flag(on: bool):
        p = tmp_path / 'features.yaml'
        p.write_text(f'max_amount_suggestion: {{enabled: {str(on).lower()}}}\n', encoding='utf-8')
        monkeypatch.setenv('COGNILEND_FEATURES_YAML', str(p))
    return set_flag


def _elements(at) -> list:
    """Everything visible, in order; the audit-log id changes on every submission and is masked."""
    out = []
    for kind in ('markdown', 'caption', 'info', 'error', 'warning', 'success', 'metric', 'button', 'code',
                 'expander'):
        for e in getattr(at, kind):
            if kind == 'metric':
                out.append((kind, e.label, '<id>' if e.label == 'Audit-log ID' else e.value))
            elif kind in ('button', 'expander'):
                out.append((kind, e.label))
            else:
                out.append((kind, e.value))
    return out


def _run_demo(page, name):
    at = AppTest.from_file(str(page), default_timeout=180)
    at.query_params['demo'] = name
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _panel_button(at):
    return [b for b in at.button if b.label == LABEL]


@pytest.mark.parametrize('name', ['auto_reject', 'hard_reject', 'malformed'])
def test_flag_off_hides_the_button(name, flag):
    flag(False)
    assert not _panel_button(_run_demo(PAGE, name))


@pytest.mark.parametrize('name, expect', [('auto_reject', 'No lower amount can be approved'),
                                          ('hard_reject', 'R01')])
def test_button_below_rejected_and_result_persists(name, expect, flag):
    flag(True)
    at = _run_demo(PAGE, name)
    before = _elements(at)
    assert len(_panel_button(at)) == 1 and not at.success and len(at.info) == 1     # only the decision reason
    _panel_button(at)[0].click().run()
    assert not at.exception
    assert any(expect in i.value for i in at.info) and any('No lower amount' in i.value for i in at.info)
    at.run()                                                                         # rerun: no recompute, still shown
    assert any('No lower amount' in i.value for i in at.info)
    after = _elements(at)
    assert all(e in after for e in before)                                           # decision card untouched
    assert sum('No lower amount' in str(e) for e in after) == 1


def _submit_json(at, app: dict):
    at.text_area[0].input(json.dumps(app))
    next(b for b in at.button if b.label == 'Submit JSON').click().run()
    assert not at.exception, [e.value for e in at.exception]


def test_possible_case_shows_amount_emi_note_and_reapply(flag):
    flag(True)
    at = AppTest.from_file(str(PAGE), default_timeout=180).run()
    submitted = {**FOIR_JSON, 'Loan_ID': 'UI-FOIR-1', 'Applicant_ID': 'UI-A1'}
    _submit_json(at, submitted)
    assert any(':orange[Rejected]' in m.value for m in at.markdown)
    _panel_button(at)[0].click().run()
    assert not at.exception
    ok = ' '.join(s.value for s in at.success)
    assert 'Can be approved up to ₹' in ok and ',' in ok
    labels = [m.label for m in at.metric]
    assert 'Requested' in labels and 'Reduction' in labels and any(lb.startswith('EMI at ₹') for lb in labels)
    assert any('Suggestion only, not an approval' in c.value for c in at.caption)
    assert any(e.label.startswith('Re-apply with ₹') for e in at.expander)
    reapply = json.loads(at.code[0].value)
    assert 'Loan_ID' not in reapply and reapply['Loan_Amount'] < FOIR_JSON['Loan_Amount']
    assert {k: v for k, v in reapply.items() if k != 'Loan_Amount'} == {k: v for k, v in submitted.items()
                                                                        if k not in ('Loan_Amount', 'Loan_ID')}
    assert any(':orange[Rejected]' in m.value for m in at.markdown)                 # nothing auto-submitted


def test_db_errors_do_not_hide_the_suggestion(flag, monkeypatch):
    flag(True)

    def boom(*a, **k):
        raise RuntimeError('injected DB error')
    monkeypatch.setattr(suggestion_store, 'log_suggestion', boom)
    at = AppTest.from_file(str(PAGE), default_timeout=180).run()
    _submit_json(at, {**FOIR_JSON, 'Loan_ID': 'UI-FOIR-2', 'Applicant_ID': 'UI-A2'})
    _panel_button(at)[0].click().run()
    assert not at.exception
    assert any('Can be approved up to ₹' in s.value for s in at.success)
