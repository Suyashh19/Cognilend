"""Home: how CogniLend decides, quick links and live summary tiles (data from repo().summary() and verify_chain())."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

import common  # noqa: E402
from cognilend import demo  # noqa: E402
from ui import components as ui  # noqa: E402

common.setup('CogniLend')
st.markdown('Hybrid rule-and-ML loan decisioning: **policy rules -> constrained decision tree -> audit database -> '
            'fairness audit**. Every outcome is Approved, Rejected or Human Review, with a confidence, a readable '
            'reason and an audit-log ID.')

st.html('<div class="cl-flow" role="list" aria-label="How CogniLend decides">'
        '<div class="cl-flow-step" role="listitem"><span class="num">1</span><h4>Policy rules</h4>'
        '<p>Forward-chaining checks on age, CIBIL, FOIR, LTV and more. A HARD rule rejects at once; a SOFT rule '
        'asks for Human Review.</p></div>'
        '<div class="cl-flow-step" role="listitem"><span class="num">2</span><h4>Decision tree</h4>'
        '<p>A small, readable tree (depth ≤ 4) scores the rest, with a Bayesian confidence. Low confidence goes '
        'to a person.</p></div>'
        '<div class="cl-flow-step" role="listitem"><span class="num">3</span><h4>Audit log</h4>'
        '<p>Every decision, reason and version is stored in a hash-chained, tamper-evident log.</p></div>'
        '<div class="cl-flow-step" role="listitem"><span class="num">4</span><h4>Fairness</h4>'
        '<p>Approval rates are compared across gender, age band and dependents against the 0.80 rule.</p></div>'
        '</div><div class="cl-outcomes" aria-label="Possible outcomes">'
        f'{ui.status_badge_html("Approved")}{ui.status_badge_html("Rejected")}{ui.status_badge_html("Human Review")}'
        '</div>')

st.html('<h3 style="margin:18px 0 6px 0">Decisions so far</h3>')
try:
    s = common.repo().summary()
    cols = st.columns(4)
    for col, k in zip(cols, ('Approved', 'Rejected', 'Human Review')):
        col.metric(k, s['decisions'].get(k, 0), border=True)
    cols[3].metric('Open reviews', s['open_reviews'], border=True, help='Cases waiting in the Review Queue.')
    status = common.repo().verify_chain()
    ui.note(f'Audit chain: {status} ({status.checked} events)', 'ok' if status.ok else 'error',
            'Tamper-evident log verified' if status.ok else 'Audit chain problem — open the Audit Explorer')
except Exception as e:  # noqa: BLE001
    st.error(f'Database not reachable: {e}. Run `python scripts/seed_demo.py`.')

st.html('<h3 style="margin:18px 0 6px 0">Get started</h3>')
a, b, c = st.columns(3)
with a:
    with st.container(border=True):
        st.page_link('views/new_application.py', label='New Application', icon=':material/edit_document:')
        st.caption('Enter an application step by step and get an explained decision.')
with b:
    with st.container(border=True):
        st.page_link('views/review_queue.py', label='Review Queue', icon=':material/person_search:')
        st.caption('Cases waiting for a loan officer\'s Human Review decision.')
with c:
    with st.container(border=True):
        st.page_link('views/audit_explorer.py', label='Audit Explorer', icon=':material/fact_check:')
        st.caption('Search decisions and verify the audit chain.')

st.html('<h3 style="margin:18px 0 6px 0">Demo cases</h3><p style="margin:0 0 8px 0;color:var(--cl-muted)">'
        'Each link opens New Application with a prepared applicant and shows its decision.</p>')
cols = st.columns(2)
for i, (name, (title, _, expected, _src)) in enumerate(demo.CASES.items()):
    with cols[i % 2]:
        st.page_link('views/new_application.py', label=title, query_params={'demo': name},
                     icon={'Approved': ':material/check_circle:', 'Rejected': ':material/cancel:'}.get(
                         expected, ':material/person_search:'))
st.markdown("""
**Pages** (sidebar): New Application · Officer Review Queue · Audit Explorer · Model & Policy · Fairness Dashboard ·
Stress Twin (advisory only).

**Demo cases**: open *New Application* with `?demo=` one of `hard_reject`, `auto_approve`, `auto_reject`,
`soft_review`, `low_confidence`, `lock`, `malformed`.
""")
common.footer()
