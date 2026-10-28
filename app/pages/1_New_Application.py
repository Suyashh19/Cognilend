import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

import common  # noqa: E402
from cognilend import demo  # noqa: E402
from cognilend.data import contract  # noqa: E402

common.setup('New Application')
F = contract.FIELDS

name = st.query_params.get('demo')
if name in demo.CASES and st.session_state.get('demo_done') != name:
    st.session_state['result'] = demo.run_case(common.pipeline(), name)
    st.session_state['demo_done'] = name
if name in demo.CASES:
    st.caption(f'Demo case: **{demo.CASES[name][0]}** (expected: {demo.CASES[name][2]})')

form_tab, json_tab = st.tabs(['Application form', 'Raw JSON (any input, incl. malformed)'])
with form_tab:
    with st.form('application'):
        a, b, c = st.columns(3)
        loan_id = a.text_input('Loan ID (optional)')
        applicant_id = b.text_input('Applicant ID, e.g. PAN (optional)')
        collateral_id = c.text_input('Collateral ID (optional, secured loans)')
        a, b, c, d = st.columns(4)
        age = a.number_input('Age (years)', min_value=int(F['Age'].min), max_value=int(F['Age'].max), value=35)
        gender = b.selectbox('Gender (audit only, not used to decide)', ['', *F['Gender'].allowed])
        marital = c.selectbox('Marital status (audit only)', ['', *F['Marital_Status'].allowed])
        dependents = d.selectbox('Dependents', [0, 1, 2, 3], index=1, format_func=lambda x: '3+' if x == 3 else str(x))
        a, b, c, d = st.columns(4)
        employment = a.selectbox('Employment type', F['Employment_Type'].allowed)
        experience = b.number_input('Work experience / business vintage (years)', 0, int(F['Work_Experience'].max), 10)
        income = c.number_input('Monthly income (₹)', 1, 100_000_000, 150_000, step=1000)
        coapp = d.number_input('Co-applicant income (₹/month, 0 = none)', 0, 100_000_000, 0, step=1000)
        a, b, c, d = st.columns(4)
        emi = a.number_input('Existing EMIs (₹/month)', 0, 100_000_000, 0, step=500)
        ntc = b.checkbox('New to credit (no CIBIL score)')
        cibil = c.number_input('CIBIL score', 300, 900, 780, disabled=ntc)
        area = d.selectbox('Property area', F['Property_Area'].allowed)
        a, b, c = st.columns(3)
        loan_type = a.selectbox('Loan type', F['Loan_Type'].allowed)
        amount = b.number_input('Loan amount (₹)', int(F['Loan_Amount'].min), 1_000_000_000, 3_000_000, step=10000)
        tenure = c.number_input('Tenure (months)', int(F['Loan_Tenure'].min), int(F['Loan_Tenure'].max), 240)
        collateral = st.number_input('Collateral value (₹, 0 = unsecured)', 0, 10_000_000_000, 5_000_000, step=10000)
        submitted = st.form_submit_button('Submit application', type='primary')
    if submitted:
        app = {'Loan_ID': loan_id or None, 'Applicant_ID': applicant_id or None, 'Collateral_ID': collateral_id or None,
               'Age': age, 'Gender': gender or None, 'Marital_Status': marital or None, 'Dependents': dependents,
               'Employment_Type': employment, 'Work_Experience': experience, 'Monthly_Income': income,
               'Coapplicant_Income': coapp or None, 'Existing_EMI': emi, 'CIBIL_Score': -1 if ntc else cibil,
               'Loan_Type': loan_type, 'Loan_Amount': amount, 'Loan_Tenure': tenure,
               'Collateral_Value': collateral or None, 'Property_Area': area}
        st.session_state['last_app'] = {k: v for k, v in app.items() if v is not None}
        st.session_state['result'] = common.pipeline().decide(st.session_state['last_app'])

with json_tab:
    raw = st.text_area('Application JSON', value=json.dumps(demo.clean(demo.CASES['malformed'][1][0]), indent=1),
                       height=220)
    if st.button('Submit JSON'):
        try:
            payload = json.loads(raw)
        except ValueError as e:
            payload = None
            st.error(f'Not valid JSON: {e}')
        if payload is not None:
            st.session_state['last_app'] = payload if isinstance(payload, dict) else None
            st.session_state['result'] = common.pipeline().decide(payload)

if 'result' in st.session_state:
    st.divider()
    common.decision_card(st.session_state['result'])
    from components.max_amount_panel import render_max_amount_panel  # noqa: E402
    render_max_amount_panel(st.session_state['result'])

    from cognilend.ml import compare  # noqa: E402
    if st.session_state['result'].get('model_version') and st.session_state.get('last_app') and compare.available():
        with st.expander('Other models (advisory only, not used for the decision)'):
            try:
                st.dataframe(compare.advise(common.pipeline().explainer, st.session_state['last_app']),
                             hide_index=True, width='stretch')
                st.caption('The decision above is made by the decision tree because only its rule path is a readable, '
                           'auditable reason. These predictions are not stored in the audit log.')
            except Exception as e:  # noqa: BLE001 - advisory panel must never break the decision page
                st.caption(f'Advisory models unavailable: {e}')
