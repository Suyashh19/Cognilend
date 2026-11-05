"""Hidden style guide (listed in the navigation only when COGNILEND_UI_DEBUG=1; also reachable at /Style_Guide then).
Shows every design-system component with sample values. No backend calls."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

import common  # noqa: E402
from ui import components as ui  # noqa: E402
from ui import format as fmt  # noqa: E402
from ui import theme  # noqa: E402

common.setup('Style guide')
st.caption(f'Active theme: {theme.mode()}. Switch light / dark from the app menu (⋮ → Settings).')

st.subheader('Colour tokens')
t = theme.TOKENS[theme.mode()]
st.html('<div class="cl-grid">' + ''.join(
    f'<div class="cl-swatch"><span style="background:{v}"></span>{ui.esc(k)}<br>{ui.esc(v)}</div>'
    for k, v in t.items() if v.startswith('#')) + '</div>')

st.subheader('Status badges (icon + text, never colour alone)')
st.html('<div class="cl-outcomes">' + ui.status_badge_html('Approved') + ui.status_badge_html('Rejected')
        + ui.status_badge_html('Human Review') + ui.status_badge_html('neutral', 'Neutral')
        + ui.status_badge_html('primary', 'Primary') + '</div>')

st.subheader('Rule chips')
st.html(ui.rule_chip_html('R01', True, 'Minimum age') + ui.rule_chip_html('R04', False, 'Minimum bureau score', 'HARD')
        + ui.rule_chip_html('S01', False, 'New to credit', 'SOFT') + ui.rule_chip_html('R06', None, 'RBI LTV cap'))

st.subheader('Metric tiles')
a, b, c = st.columns(3)
with a:
    ui.metric_tile('Confidence', '0.91', 'Estimated approval probability.')
with b:
    ui.metric_tile('Audit-log ID', '1042')
with c:
    ui.metric_tile('Decided by', 'MODEL')
ui.tiles([('Proposed EMI', fmt.rupee(28_955) + '/mo', 'at 9.50%', 'primary'), ('FOIR', '19.3%', 'limit 55%', 'approve'),
          ('LTV', '60.0%', 'cap 80%', None), ('Age at maturity', '55.0 years', None, 'review')])

st.subheader('Confidence meter')
ui.confidence_meter(0.86, (0.81, 0.90), 'Model confidence')

st.subheader('Tree path trail')
st.html(ui.trail_html(['FOIR 0.32 ≤ 0.45', 'CIBIL 742 > 698'], 'Approved', 'approve'))

st.subheader('Step indicator')
ui.step_indicator(3, 5, ['Applicant', 'Employment & Income', 'Credit', 'Loan & Collateral', 'Review & Submit'], {4})

st.subheader('Messages')
ui.note('Demo applicant loaded.', 'ok')
ui.note('The preview appears when every field is valid.', 'info')
ui.note('Check these fields.', 'warn', 'Before you submit', ['Work_Experience: 30 years is impossible at age 35'])
ui.error_box('The database could not be reached. Run python scripts/seed_demo.py.')
ui.empty_state('No applications yet.', '○', 'Submit one from New Application.')

st.subheader('Copy button')
ui.copy_button('1042', 'Copy audit ID')

st.subheader('Formatting')
st.html(ui.kv_html([('rupee(2790000)', fmt.rupee(2_790_000)), ('rupee(150000)', fmt.rupee(150_000)),
                    ('rupee_short(12500000)', fmt.rupee_short(12_500_000)), ('pct(0.3214)', fmt.pct(0.3214)),
                    ('date_in(2026-11-05)', fmt.date_in('2026-11-05')),
                    ('datetime_in(2026-11-05T14:03)', fmt.datetime_in('2026-11-05T14:03:00'))]))

st.subheader('Card')
with ui.card():
    st.markdown('Any Streamlit content can go in a card.')
common.footer()
