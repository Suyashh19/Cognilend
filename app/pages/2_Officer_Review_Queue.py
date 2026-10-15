import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import common  # noqa: E402

common.setup('Officer Review Queue')
reviews = common.repo().list_reviews('OPEN')
st.caption(f'{len(reviews)} open cases (newest first). Deciding here records a separate HUMAN decision with its '
           'own audit event; an approval still has to pass the FR-10 lock.')
if not reviews:
    st.success('No open reviews.')
else:
    df = pd.DataFrame(reviews)
    st.dataframe(df[['review_id', 'loan_id', 'applicant_id', 'loan_type', 'amount', 'model_recommendation',
                     'confidence', 'source', 'reason']], hide_index=True, width='stretch', height=320)
    ids = [r['review_id'] for r in reviews]
    pick = st.selectbox('Case', ids, format_func=lambda i: f'#{i} - {df.set_index("review_id").loc[i, "loan_id"]}')
    case = df.set_index('review_id').loc[pick]
    st.markdown(f'**Why it is here:** {case["reason"]}')
    with st.form('officer'):
        officer = st.text_input('Officer ID', 'officer-1')
        outcome = st.radio('Decision', ['Approved', 'Rejected'], horizontal=True)
        notes = st.text_area('Note (required)', '')
        go = st.form_submit_button('Record decision', type='primary')
    if go:
        if not notes.strip():
            st.error('A note is required.')
        else:
            res = common.pipeline().complete_review(int(pick), officer, outcome, notes)
            if res['ok']:
                st.success(f'Recorded HUMAN decision {res["decision_id"]} (audit-log ID {res["audit_log_id"]}).')
            else:
                st.error(f'Not approved: {res["reason"]} (audit-log ID {res["audit_log_id"]})')

closed = common.repo().list_reviews('CLOSED', limit=20)
if closed:
    st.subheader('Recently closed')
    st.dataframe(pd.DataFrame(closed)[['review_id', 'loan_id', 'officer_decision', 'notes']], hide_index=True,
                 width='stretch')
