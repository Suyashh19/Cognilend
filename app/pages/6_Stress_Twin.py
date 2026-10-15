import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import common  # noqa: E402
from cognilend.stress_twin.simulator import StressInputs, alternatives, cfg, simulate  # noqa: E402

common.setup('Stress Twin (advisory)')
c = cfg()
st.warning('Advisory panel only: it never changes the Approved / Rejected / Human Review decision. All thresholds, '
           'shock sizes and the resilience formula are **illustrative, to be calibrated**.')

with st.form('stress_form'):
    a, b, d, e = st.columns(4)
    income = a.number_input('Monthly income mean (₹)', 0, 10_000_000, 80_000, step=1000)
    cv = b.number_input('Income variability CV (σ/μ)', 0.0, 2.0, 0.15, step=0.05)
    income_day = d.number_input('Income credit day', 1, 28, 1)
    essentials = e.number_input('Essential expenses (₹/month)', 0, 10_000_000, 35_000, step=1000)
    a, b, d, e = st.columns(4)
    existing = a.number_input('Existing EMIs (₹/month)', 0, 10_000_000, 5_000, step=500)
    amount = b.number_input('Proposed loan amount (₹)', 0, 1_000_000_000, 1_500_000, step=10000)
    rate = d.number_input('Annual interest rate', 0.0, 0.5, 0.105, step=0.005, format='%.3f')
    tenure = e.number_input('Tenure (months)', 1, 360, 60)
    a, b = st.columns(2)
    due = a.number_input('EMI due day', 1, 28, 5)
    savings = b.number_input('Liquid savings (₹)', 0, 1_000_000_000, 60_000, step=5000)
    go = st.form_submit_button('Run stress test', type='primary')

if go or 'stress' not in st.session_state:
    inp = StressInputs(income_mean=income, income_cv=cv, income_day=income_day, essentials=essentials,
                       existing_emi=existing, loan_amount=amount, annual_rate=rate, tenure_months=tenure,
                       emi_due_day=due, savings=savings)
    st.session_state['stress'] = (simulate(inp), alternatives(inp))
res, alts = st.session_state['stress']

st.subheader(f'{res["band"]}  ·  resilience {res["resilience"]} / 100 (illustrative)')
st.caption(f'{c["n_paths"]} Monte Carlo paths per scenario, {c["horizon_months"]}-month horizon, seed {c["seed"]}. '
           f'Bands on the {c["headline_scenario"]} scenario: < {c["bands"]["resilient_below"]:.0%} Resilient, '
           f'< {c["bands"]["vulnerable_below"]:.0%} Vulnerable, otherwise suggest review (illustrative, to be '
           'calibrated).')
if res['missing']:
    st.error('Insufficient data: ' + ', '.join(res['missing']))
else:
    m1, m2, m3 = st.columns(3)
    m1.metric('Total EMI after loan', f'₹{res["total_emi"]:,.0f}')
    m2.metric('Buffer coverage', f'{res["buffer_coverage_months"]:.1f} months')
    m3.metric('Headline shortfall probability', f'{res["scenarios"][res["headline"]]["shortfall_probability"]:.1%}')
    table = pd.DataFrame(res['scenarios']).T
    table.columns = ['min balance p5 (₹)', 'min balance median (₹)', 'shortfall probability', 'max shortfall (₹)',
                     'months in deficit (mean)', 'recovery time (months)', 'stressed FOIR (median)']
    st.dataframe(table.style.format('{:,.2f}'), width='stretch')
    if res['band'] != 'Resilient':
        st.markdown('**Alternative terms** (headline scenario)')
        st.dataframe(pd.DataFrame(alts), hide_index=True, width='stretch')
