"""CogniLend Streamlit app.  Start with:  streamlit run app/streamlit_app.py   (seed first: python scripts/seed_demo.py)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

import common  # noqa: E402

common.setup('CogniLend')
st.markdown('Hybrid rule-and-ML loan decisioning: **policy rules -> constrained decision tree -> audit database -> '
            'fairness audit**. Every outcome is Approved, Rejected or Human Review, with a confidence, a readable '
            'reason and an audit-log ID.')
try:
    s = common.repo().summary()
    cols = st.columns(4)
    for col, k in zip(cols, ('Approved', 'Rejected', 'Human Review')):
        col.metric(k, s['decisions'].get(k, 0))
    cols[3].metric('Open reviews', s['open_reviews'])
    status = common.repo().verify_chain()
    st.caption(f'Audit chain: {status} ({status.checked} events)')
except Exception as e:  # noqa: BLE001
    st.error(f'Database not reachable: {e}. Run `python scripts/seed_demo.py`.')
st.markdown("""
**Pages** (sidebar): New Application · Officer Review Queue · Audit Explorer · Model & Policy · Fairness Dashboard ·
Stress Twin (advisory only).

**Demo cases**: open *New Application* with `?demo=` one of `hard_reject`, `auto_approve`, `auto_reject`,
`soft_review`, `low_confidence`, `lock`, `malformed`.
""")
