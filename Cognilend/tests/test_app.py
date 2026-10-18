"""Headless UI tests (streamlit.testing.v1.AppTest) against the seeded project database."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from cognilend import demo

APP = Path(__file__).resolve().parents[1] / 'app'
PAGES = sorted((APP / 'pages').glob('*.py'))


def _text(at) -> str:
    parts = [m.value for m in at.markdown] + [m.value for m in at.caption] + [m.value for m in at.info] \
        + [m.value for m in at.error] + [m.value for m in at.warning] + [m.value for m in at.success]
    parts += [f'{m.label} {m.value}' for m in at.metric]
    return '\n'.join(str(p) for p in parts)


@pytest.mark.parametrize('page', [APP / 'streamlit_app.py', *PAGES], ids=lambda p: p.stem)
def test_every_page_renders_without_exception(page):
    at = AppTest.from_file(str(page), default_timeout=180).run()
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize('name', list(demo.CASES))
def test_demo_case_shows_expected_decision_card(name):
    title, _, expected, source = demo.CASES[name]
    at = AppTest.from_file(str(APP / 'pages' / '1_New_Application.py'), default_timeout=180)
    at.query_params['demo'] = name
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    text = _text(at)
    assert f':{"blue" if expected == "Approved" else "orange" if expected == "Rejected" else "violet"}[{expected}]' \
        in text
    assert f'Decided by {source}' in text and 'Audit-log ID' in text
    if name == 'hard_reject':
        assert 'R01' in text and 'Model not consulted' in text
    if name == 'lock':
        assert 'Lock (FR-10)' in text
    if name == 'malformed':
        assert 'invalid input' in text and 'Age' in text
    if name in ('auto_approve', 'auto_reject', 'low_confidence', 'soft_review'):
        assert '90% credible interval' in text and 'CIBIL' in text


def test_officer_review_records_human_decision():
    at = AppTest.from_file(str(APP / 'pages' / '2_Officer_Review_Queue.py'), default_timeout=180).run()
    assert not at.exception
    at.text_area[0].input('documents verified in UI test')
    at.radio[0].set_value('Rejected')
    at.button[0].click().run()
    assert not at.exception
    assert any('Recorded HUMAN decision' in s.value for s in at.success), [s.value for s in at.error]


def test_audit_explorer_verify_chain_button():
    at = AppTest.from_file(str(APP / 'pages' / '3_Audit_Explorer.py'), default_timeout=180).run()
    at.button[0].click().run()
    assert not at.exception
    assert any('Audit chain OK' in s.value for s in at.success)
