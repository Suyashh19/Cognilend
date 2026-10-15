import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import common  # noqa: E402

common.setup('Audit Explorer')
left, right = st.columns([3, 1])
term = left.text_input('Loan ID or applicant ID (prefix search)', st.query_params.get('q', 'DEMO'))
with right:
    st.write('')
    if st.button('Verify chain', type='primary'):
        status = common.repo().verify_chain()
        st.session_state['chain'] = status
if 'chain' in st.session_state:
    status = st.session_state['chain']
    if status.ok:
        st.success(f'Audit chain OK: {status.checked} events verified.')
    else:
        st.error(f'Audit chain BROKEN at seq {status.first_broken_seq}: {status.problem}')

history = common.repo().decision_history(term) if term else []
st.caption(f'{len(history)} decisions')
if history:
    df = pd.DataFrame(history)
    st.dataframe(df[['decision_id', 'loan_id', 'applicant_id', 'source', 'outcome', 'confidence', 'fired_rules',
                     'policy_version', 'model_version', 'audit_seq', 'created_at']],
                 hide_index=True, width='stretch', height=300)
    pick = st.selectbox('Decision', df['decision_id'].tolist())
    row = df.set_index('decision_id').loc[pick]
    st.markdown(f'**Reason:** {row["reason"]}')
    event = common.repo().audit_event(int(row['audit_seq'])) if pd.notna(row['audit_seq']) else None
    if event:
        st.markdown(f'**Audit event #{event["seq"]}** `{event["event_type"]}` at {event["created_at"]}')
        st.code(f'prev_hash {event["prev_hash"]}\nhash      {event["hash"]}')
        st.json(event['payload'])
