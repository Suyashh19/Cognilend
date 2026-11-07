import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import common  # noqa: E402
from ui import components as ui  # noqa: E402
from ui import format as fmt  # noqa: E402

common.setup('Officer Review Queue')
reviews = common.repo().list_reviews('OPEN')
st.caption(f'{len(reviews)} open cases (newest first). Deciding here records a separate HUMAN decision with its '
           'own audit event; an approval still has to pass the FR-10 lock.')


def reason_tag(reason: str) -> str:
    """Short filter label for a review reason (text matching for display/filtering only)."""
    r = reason or ''
    m = re.match(r'\s*([RS]\d{2})\b', r)
    if m:
        return m.group(1) + ' ' + {'S01': 'new to credit', 'S02': 'experience', 'S03': 'borderline FOIR',
                                   'S04': 'missing information'}.get(m.group(1), 'rule')
    if 'Lock (FR-10)' in r:
        return 'Lock (FR-10)'
    if r.startswith('Low model confidence'):
        return 'Low model confidence'
    if 'Decision store unavailable' in r:
        return 'DB unavailable'
    return 'Other'


if not reviews:
    ui.empty_state('No open reviews.', '✓', 'Every case the system routed to a person has been decided.')
else:
    df = pd.DataFrame(reviews)
    df['why'] = df['reason'].map(reason_tag)
    df['created'] = pd.to_datetime(df['created_at'], errors='coerce')

    st.html('<h3 style="margin:4px 0 6px 0">Queue</h3>')
    f1, f2 = st.columns([3, 2])
    tags = sorted(df['why'].unique())
    picked = f1.multiselect('Filter by reason', tags, placeholder='All reasons',
                            help='Why the system routed the case to a person.')
    days = df['created'].dropna().dt.date
    date_range = None
    if len(days):
        lo, hi = days.min(), days.max()
        date_range = f2.date_input('Filter by date received', (lo, hi), min_value=lo, max_value=hi,
                                   format='DD/MM/YYYY', help='Cases received between these dates (UTC).')
    view = df
    if picked:
        view = view[view['why'].isin(picked)]
    if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        d0, d1 = date_range
        view = view[view['created'].dt.date.between(d0, d1) | view['created'].isna()]

    if view.empty:
        ui.empty_state('No cases match these filters.', '○', 'Clear the reason or date filter to see every case.')
        view = df
    shown = view.assign(amount_inr=view['amount'].map(fmt.rupee), received=view['created'].map(fmt.datetime_in))
    st.dataframe(shown[['review_id', 'loan_id', 'applicant_id', 'loan_type', 'amount_inr', 'why',
                        'model_recommendation', 'confidence', 'source', 'received', 'reason']],
                 hide_index=True, width='stretch', height=320,
                 column_config={'review_id': st.column_config.NumberColumn('Case', format='#%d'),
                                'loan_id': 'Loan ID', 'applicant_id': 'Applicant', 'loan_type': 'Type',
                                'amount_inr': 'Amount', 'why': 'Why here',
                                'model_recommendation': 'Model says',
                                'confidence': st.column_config.ProgressColumn('Confidence', min_value=0.0,
                                                                              max_value=1.0, format='%.2f'),
                                'source': 'Routed by', 'received': 'Received', 'reason': 'Full reason'})

    ids = view['review_id'].tolist()
    left, right = st.columns([3, 2], gap='large')
    with left:
        pick = st.selectbox('Case', ids, format_func=lambda i: f'#{i} - {df.set_index("review_id").loc[i, "loan_id"]}',
                            help='Choose the case to review.')
        case = df.set_index('review_id').loc[pick]
        with st.container(border=True, key='cl-case-detail'):
            st.html(f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
                    f'{ui.status_badge_html("Human Review")}<strong>Case #{int(pick)} · {ui.esc(case["loan_id"])}</strong>'
                    f'</div>')
            st.markdown(f'**Why it is here:** {case["reason"]}')
            ui.tiles([('Loan', f'{case["loan_type"] or "—"} · {fmt.rupee(case["amount"])}'),
                      ('Model recommendation', case['model_recommendation'] or '—', None,
                       ui.kind_of(case['model_recommendation'])),
                      ('Confidence', fmt.number(case['confidence'])),
                      ('Received', fmt.datetime_in(case['created_at']))], min_width=140)
            with st.expander('Full decision explanation', icon=':material/description:'):
                hist = [h for h in common.repo().decision_history(case['loan_id']) if h['loan_id'] == case['loan_id']]
                if not hist:
                    ui.empty_state('No stored decision found for this loan.')
                for h in hist:
                    st.html(f'<div style="margin:6px 0">{ui.status_badge_html(h["outcome"])} '
                            f'<span class="cl-tile-help">{ui.esc(h["source"])} · {fmt.datetime_in(h["created_at"])} · '
                            f'audit #{ui.esc(h["audit_seq"])}</span></div>')
                    st.html(ui.kv_html([('Reason', h['reason']),
                                        ('Fired rules', ', '.join(h['fired_rules']) or 'none'),
                                        ('Confidence', fmt.number(h['confidence'])),
                                        ('Policy / model', f'{h["policy_version"]} / {h["model_version"] or "not consulted"}')]))
                    ev = common.repo().audit_event(int(h['audit_seq'])) if h.get('audit_seq') is not None else None
                    if ev:
                        st.json(ev['payload'], expanded=False)
    with right:
        with st.container(border=True, key='cl-officer-form'):
            st.html('<h4 style="margin:0 0 4px 0">Record a Human Review decision</h4>'
                    '<div class="cl-tile-help">A note is required. Approvals are re-checked against the FR-10 '
                    'lock.</div>')
            with st.form('officer'):
                officer = st.text_input('Officer ID', 'officer-1')
                outcome = st.radio('Decision', ['Approved', 'Rejected'], horizontal=True,
                                   captions=['Lend as applied', 'Decline the application'])
                notes = st.text_area('Note (required)', '', placeholder='e.g. Salary slips and bank statements verified.')
                go = st.form_submit_button('Record decision', type='primary', icon=':material/gavel:')
            if go:
                if not notes.strip():
                    st.error('A note is required.')
                else:
                    with st.spinner('Recording the decision…'):
                        res = common.pipeline().complete_review(int(pick), officer, outcome, notes)
                    if res['ok']:
                        st.success(f'Recorded HUMAN decision {res["decision_id"]} (audit-log ID {res["audit_log_id"]}).')
                    else:
                        st.error(f'Not approved: {res["reason"]} (audit-log ID {res["audit_log_id"]})')

closed = common.repo().list_reviews('CLOSED', limit=20)
if closed:
    st.subheader('Recently closed')
    st.dataframe(pd.DataFrame(closed)[['review_id', 'loan_id', 'officer_decision', 'notes']], hide_index=True,
                 width='stretch', column_config={'review_id': st.column_config.NumberColumn('Case', format='#%d'),
                                                 'loan_id': 'Loan ID', 'officer_decision': 'Officer decision',
                                                 'notes': 'Note'})
common.footer()
