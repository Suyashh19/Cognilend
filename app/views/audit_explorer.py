import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import common  # noqa: E402
from ui import components as ui  # noqa: E402
from ui import format as fmt  # noqa: E402

common.setup('Audit Explorer')

# ---- chain verification: the most important action on this page ----
with st.container(border=True, key='cl-chain-box'):
    v1, v2 = st.columns([3, 1], vertical_alignment='center')
    v1.html('<h4 style="margin:0">Tamper-evident audit chain</h4><div class="cl-tile-help">Every decision is an '
            'event whose hash includes the previous event\'s hash. Verifying recomputes every hash; any edited, '
            'deleted or re-ordered record breaks the chain.</div>')
    with v2:
        if st.button('Verify chain', type='primary', icon=':material/verified_user:', width='stretch'):
            with st.spinner('Recomputing every hash…'):
                status = common.repo().verify_chain()
            st.session_state['chain'] = status
    if 'chain' in st.session_state:
        status = st.session_state['chain']
        if status.ok:
            st.success(f'Audit chain OK: {status.checked} events verified.', icon=':material/verified:')
        else:
            st.error(f'Audit chain BROKEN at seq {status.first_broken_seq}: {status.problem}', icon=':material/gpp_bad:')
            bad = common.repo().audit_event(int(status.first_broken_seq)) if status.first_broken_seq else None
            if bad:
                with st.expander(f'Broken record #{bad["seq"]}', expanded=True, icon=':material/report:'):
                    st.code(f'prev_hash {bad["prev_hash"]}\nhash      {bad["hash"]}')
                    st.json(bad['payload'])

# ---- search ----
left, right = st.columns([3, 1], vertical_alignment='bottom')
term = left.text_input('Loan ID or applicant ID (prefix search)', st.query_params.get('q', 'DEMO'),
                       help='Matches loan IDs and applicant IDs that start with this text, e.g. DEMO or LN2025.')
history = common.repo().decision_history(term) if term else []
right.html(f'<div class="cl-tile"><div class="cl-tile-label">Matches</div><div class="cl-tile-value">'
           f'{len(history)}</div></div>')
st.caption(f'{len(history)} decisions')

if not term:
    ui.empty_state('Type a loan ID or applicant ID to search.', '⌕')
elif not history:
    ui.empty_state(f'No decisions found for "{term}".', '○', 'Search is a prefix match on loan ID and applicant ID.')
else:
    df = pd.DataFrame(history)
    tab_timeline, tab_table = st.tabs(['Timeline by applicant', 'All matching decisions'])
    with tab_timeline:
        applicants = list(dict.fromkeys(df['applicant_id']))
        who = st.selectbox('Applicant', applicants, help='Decision history of one applicant, oldest first.')
        rows = df[df['applicant_id'] == who]
        items = []
        for r in rows.itertuples():
            k = ui.kind_of(r.outcome)
            items.append(f'<li class="{k}"><div class="when">{fmt.datetime_in(r.created_at)} · audit #'
                         f'{ui.esc("" if pd.isna(r.audit_seq) else int(r.audit_seq))}</div>'
                         f'<div class="what">{ui.status_badge_html(r.outcome)} '
                         f'<strong>{ui.esc(r.loan_id)}</strong> · decided by {ui.esc(r.source)}'
                         f'{" · confidence " + fmt.number(r.confidence) if pd.notna(r.confidence) else ""}</div>'
                         f'<div class="cl-tile-help">{ui.esc(r.reason)}</div></li>')
        st.html(f'<ol class="cl-timeline" aria-label="Decision history">{"".join(items)}</ol>')
    with tab_table:
        st.dataframe(df[['decision_id', 'loan_id', 'applicant_id', 'source', 'outcome', 'confidence', 'fired_rules',
                         'policy_version', 'model_version', 'audit_seq', 'created_at']],
                     hide_index=True, width='stretch', height=300,
                     column_config={'created_at': st.column_config.DatetimeColumn('created_at (UTC)',
                                                                                  format='DD MMM YYYY, HH:mm')})

    st.html('<h3 style="margin:14px 0 4px 0">Decision detail</h3>')
    pick = st.selectbox('Decision', df['decision_id'].tolist(),
                        format_func=lambda i: f'#{i} · {df.set_index("decision_id").loc[i, "loan_id"]} · '
                                              f'{df.set_index("decision_id").loc[i, "outcome"]}')
    row = df.set_index('decision_id').loc[pick]
    with st.container(border=True, key='cl-audit-detail'):
        st.html(f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
                f'{ui.status_badge_html(row["outcome"])}<strong>{ui.esc(row["loan_id"])}</strong>'
                f'<span class="cl-tile-help">{ui.esc(row["source"])} · {fmt.datetime_in(row["created_at"])}</span></div>')
        st.markdown(f'**Reason:** {row["reason"]}')
        event = common.repo().audit_event(int(row['audit_seq'])) if pd.notna(row['audit_seq']) else None
        if event:
            st.markdown(f'**Audit event #{event["seq"]}** `{event["event_type"]}` at {event["created_at"]}')
            st.code(f'prev_hash {event["prev_hash"]}\nhash      {event["hash"]}')
            with st.expander('Event payload (as stored)', icon=':material/data_object:'):
                st.json(event['payload'])
        else:
            ui.note('This decision has no audit event.', 'warn')
common.footer()
