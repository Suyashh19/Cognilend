"""CogniLend Streamlit app.  Start with:  streamlit run app/streamlit_app.py   (seed first: python scripts/seed_demo.py)

App shell: pages are registered here; the sidebar menu (sections, icons, current page highlighted) is drawn by
common.sidebar_nav() on every page. Every page keeps its
original URL, e.g. /New_Application?demo=lock). Set COGNILEND_UI_DEBUG=1 to also list the hidden Style guide page.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import streamlit as st  # noqa: E402

P = HERE / 'pages'
pages = {
    'Apply': [
        st.Page(HERE / 'views' / 'home.py', title='Home', icon=':material/home:', default=True),
        st.Page(P / '1_New_Application.py', title='New Application', icon=':material/edit_document:',
                url_path='New_Application'),
    ],
    'Operations': [
        st.Page(P / '2_Officer_Review_Queue.py', title='Review Queue', icon=':material/person_search:',
                url_path='Officer_Review_Queue'),
        st.Page(P / '3_Audit_Explorer.py', title='Audit Explorer', icon=':material/fact_check:',
                url_path='Audit_Explorer'),
    ],
    'Governance': [
        st.Page(P / '4_Model_and_Policy.py', title='Model & Policy', icon=':material/account_tree:',
                url_path='Model_and_Policy'),
        st.Page(P / '5_Fairness_Dashboard.py', title='Fairness', icon=':material/balance:',
                url_path='Fairness_Dashboard'),
        st.Page(P / '7_Model_Comparison.py', title='Model Comparison', icon=':material/leaderboard:',
                url_path='Model_Comparison'),
    ],
    'Advisory': [
        st.Page(P / '6_Stress_Twin.py', title='Stress Twin', icon=':material/monitoring:', url_path='Stress_Twin'),
    ],
}
if os.environ.get('COGNILEND_UI_DEBUG') == '1':
    pages['Developer'] = [st.Page(HERE / 'views' / 'style_guide.py', title='Style guide', icon=':material/palette:',
                                  url_path='Style_Guide')]

st.navigation(pages, position='hidden').run()   # the visible sidebar menu is common.sidebar_nav()
