import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

import common  # noqa: E402
from cognilend import demo  # noqa: E402
from cognilend.data import contract  # noqa: E402
from cognilend.rules import engine  # noqa: E402
from ui import components as ui  # noqa: E402
from ui import format as fmt  # noqa: E402

common.setup('New Application')
st.caption('Submit an application to see the policy checks, model explanation, confidence, and audit record. '
           'Gender and marital status are collected for fairness auditing only; they are not model inputs.')
F = contract.FIELDS
B = common.form_bounds()
O = common.form_options()
ss = st.session_state

# ---- "Start a new application" link from a result: clear the result and the form, then drop the parameter ----
if st.query_params.get('new') == '1':
    for k in ('result', 'last_app', 'demo_done', 'cl_last_submit', 'cl_notice'):
        ss.pop(k, None)
    common.reset_form()
    del st.query_params['new']

for k, v in common.FORM_DEFAULTS.items():                   # original defaults, kept across steps and reruns
    ss.setdefault(k, v if v is not None else O[k][0])
ss.setdefault('json_raw', json.dumps(demo.clean(demo.CASES['malformed'][1][0]), indent=1))

name = st.query_params.get('demo')
if name in demo.CASES and ss.get('demo_done') != name:
    ss['result'] = demo.run_case(common.pipeline(), name)
    ss['demo_done'] = name
    shown = demo.clean(demo.CASES[name][1][-1])                # the application whose result is shown
    if name == 'malformed':
        ss['json_raw'] = json.dumps(shown, indent=1)
    else:
        common.prefill_form(shown)
if name in demo.CASES:
    st.caption(f'Demo case: **{demo.CASES[name][0]}** (expected: {demo.CASES[name][2]})')

DEMO_LABELS = {'hard_reject': 'HARD reject', 'auto_approve': 'Auto-approve', 'auto_reject': 'Auto-reject',
               'soft_review': 'SOFT review', 'low_confidence': 'Low confidence', 'lock': 'Lock (FR-10)',
               'malformed': 'Malformed input'}


def _load_demo():
    pick = ss.get('cl_demo_pick')
    if not pick:
        return
    app = demo.clean(demo.CASES[pick][1][-1])
    if pick == 'malformed':
        ss['json_raw'] = json.dumps(app, indent=1)
        ss['cl_notice'] = ('info', f'Demo "{DEMO_LABELS[pick]}" loaded into the Raw JSON tab (its values cannot be '
                                   'typed into the form). Open that tab and press Submit JSON.')
    else:
        skipped = common.prefill_form(app)
        extra = ' Its first application must already be approved (it is, in the seeded database).' \
            if pick == 'lock' else ''
        ss['cl_notice'] = ('ok', f'Demo applicant "{DEMO_LABELS[pick]}" loaded. Check the steps, then press '
                                 f'Submit application on step 5.{extra}' +
                           (f' Not shown in the form: {", ".join(skipped)}.' if skipped else ''))
    ss['cl_demo_pick'] = None


st.pills('Load a demo applicant', list(DEMO_LABELS), format_func=DEMO_LABELS.get, key='cl_demo_pick',
         on_change=_load_demo, help='Fills the form with one of the prepared demo cases (nothing is submitted).')
if ss.get('cl_notice'):
    kind, msg = ss['cl_notice']
    ui.note(msg, kind)


def build_app() -> dict:
    """Exactly the dict the original form sent: same keys, types and units; empty optional fields omitted."""
    app = {'Loan_ID': ss['f_loan_id'] or None, 'Applicant_ID': ss['f_applicant_id'] or None,
           'Collateral_ID': ss['f_collateral_id'] or None, 'Age': ss['f_age'], 'Gender': ss['f_gender'] or None,
           'Marital_Status': ss['f_marital'] or None, 'Dependents': ss['f_dependents'],
           'Employment_Type': ss['f_employment'], 'Work_Experience': ss['f_experience'],
           'Monthly_Income': ss['f_income'], 'Coapplicant_Income': ss['f_coapp'] or None,
           'Existing_EMI': ss['f_emi'], 'CIBIL_Score': -1 if ss['f_ntc'] else ss['f_cibil'],
           'Loan_Type': ss['f_loan_type'], 'Loan_Amount': ss['f_amount'], 'Loan_Tenure': ss['f_tenure'],
           'Collateral_Value': ss['f_collateral'] or None, 'Property_Area': ss['f_area']}
    return {k: v for k, v in app.items() if v is not None}


def submit(payload, last_app):
    """Decide once per click: a repeated identical submission within 5 s (double click) is ignored."""
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    prev = ss.get('cl_last_submit')
    if prev and prev[0] == digest and time.time() - prev[1] < 5 and 'result' in ss:
        st.toast('Already submitted — showing that result.', icon=':material/info:')
        return
    ss['cl_last_submit'] = (digest, time.time())
    with st.spinner('Checking the policy rules and the model…'):
        ss['last_app'] = last_app
        ss['result'] = common.pipeline().decide(payload)
    ss.pop('cl_notice', None)


@st.cache_data(show_spinner=False, max_entries=256)
def facts_for(app_json: str) -> dict:
    """The rule engine's own fact base for this application (read-only; nothing is stored)."""
    res = engine.evaluate(json.loads(app_json))
    return {'facts': res.get('facts') or {}, 'errors': res.get('input_errors') or []}


STEPS = ['Applicant', 'Employment & Income', 'Credit', 'Loan & Collateral', 'Review & Submit']
STEP_OF = {'Loan_ID': 1, 'Applicant_ID': 1, 'Age': 1, 'Gender': 1, 'Marital_Status': 1, 'Dependents': 1,
           'Employment_Type': 2, 'Work_Experience': 2, 'Monthly_Income': 2, 'Coapplicant_Income': 2,
           'Existing_EMI': 2, 'CIBIL_Score': 3, 'Loan_Type': 4, 'Loan_Amount': 4, 'Loan_Tenure': 4,
           'Collateral_Value': 4, 'Collateral_ID': 4, 'Property_Area': 4}


def field_errors(app: dict) -> dict:
    """Contract violations (cognilend.data.contract.validate, the backend's own check) grouped by field."""
    out = {}
    for msg in contract.validate(app):
        out.setdefault(msg.split(':')[0].strip(), []).append(msg)
    return out


def hint(errors: dict, *fields):
    msgs = [m for f in fields for m in errors.get(f, [])]
    if msgs:
        st.html(''.join(f'<div class="cl-field-hint" role="alert">✕ {ui.esc(m)}</div>' for m in msgs))


def next_hint(step: int):
    if step < len(STEPS):
        st.html(f'<div class="cl-tile-help" style="margin-top:8px">Next: <strong>{step + 1} · '
                f'{ui.esc(STEPS[step])}</strong> — choose it in the step bar above. Your answers are kept.</div>')


def rng(field: str, unit: str = '') -> str:
    f = F[field]
    lo = fmt.rupee(f.min) if unit == '₹' else f'{f.min:g}'
    hi = fmt.rupee(f.max) if unit == '₹' else f'{f.max:g}'
    return f'{lo}–{hi}'


app_now = build_app()
errs = field_errors(app_now)

form_tab, json_tab = st.tabs(['Application form', 'Raw JSON (any input, incl. malformed)'])
with form_tab:
    issues = {STEP_OF.get(f, 5) for f in errs}
    with st.container(key='cl-stepper-tabs'):
        t1, t2, t3, t4, t5 = st.tabs([f'{i} · {s}' for i, s in enumerate(STEPS, 1)])
    with t1:
        a, b = st.columns(2)
        a.text_input('Loan ID (optional)', key='f_loan_id', help='Leave blank and the system assigns one. Letters, '
                     'digits, - and _ only (up to 32).')
        b.text_input('Applicant ID, e.g. PAN (optional)', key='f_applicant_id',
                     help='Customer identifier such as PAN. Used for the fraud registry check and the one-loan lock.')
        hint(errs, 'Loan_ID', 'Applicant_ID')
        a, b, c, d = st.columns(4)
        a.number_input('Age (years)', min_value=B['f_age'][0], max_value=B['f_age'][1], key='f_age',
                       help=f'Applicant\'s age in completed years ({rng("Age")}).')
        b.selectbox('Gender (audit only, not used to decide)', O['f_gender'], key='f_gender',
                    help='Optional. Stored only for the fairness audit; never a model input.')
        c.selectbox('Marital status (audit only)', O['f_marital'], key='f_marital',
                    help='Optional. Stored only for the fairness audit; never a model input.')
        d.selectbox('Dependents', O['f_dependents'], key='f_dependents', format_func=lambda x: '3+' if x == 3 else str(x),
                    help='People who depend on the applicant financially (3 means 3 or more).')
        hint(errs, 'Age', 'Gender', 'Marital_Status', 'Dependents')
        next_hint(1)
    with t2:
        a, b = st.columns(2)
        a.selectbox('Employment type', O['f_employment'], key='f_employment',
                    help='Salaried; SEP = self-employed professional; SENP = self-employed non-professional.')
        a.number_input('Work experience / business vintage (years)', 0, B['f_experience'][1], key='f_experience',
                       help='Years in work (or years the business has run). Cannot start before age 18.')
        b.number_input('Monthly income (₹)', B['f_income'][0], B['f_income'][1], step=1000, key='f_income',
                       help=f'Take-home income per month in rupees ({rng("Monthly_Income", "₹")}).')
        b.number_input('Co-applicant income (₹/month, 0 = none)', B['f_coapp'][0], B['f_coapp'][1], step=1000,
                       key='f_coapp', help='Monthly income of an earning co-applicant. Enter 0 if there is none.')
        st.number_input('Existing EMIs (₹/month)', B['f_emi'][0], B['f_emi'][1], step=500, key='f_emi',
                        help='Total of the monthly instalments the applicant already pays on other loans.')
        hint(errs, 'Employment_Type', 'Work_Experience', 'Monthly_Income', 'Coapplicant_Income', 'Existing_EMI')
        next_hint(2)
    with t3:
        a, b = st.columns(2)
        a.checkbox('New to credit (no CIBIL score)', key='f_ntc',
                   help='Tick if the applicant has never taken credit. The score is then sent as -1.')
        b.number_input('CIBIL score', B['f_cibil'][0], B['f_cibil'][1], key='f_cibil', disabled=ss['f_ntc'],
                       help=f'Credit score from the bureau, {rng("CIBIL_Score")}. If the applicant has never taken '
                            'credit, tick "New to credit" instead (sent as -1).')
        hint(errs, 'CIBIL_Score')
        next_hint(3)
    with t4:
        a, b, c = st.columns(3)
        a.selectbox('Loan type', O['f_loan_type'], key='f_loan_type',
                    help='Home and Vehicle loans are secured by the property / vehicle.')
        b.number_input('Loan amount (₹)', B['f_amount'][0], B['f_amount'][1], step=10000, key='f_amount',
                       help=f'Amount requested in rupees ({rng("Loan_Amount", "₹")}).')
        c.number_input('Tenure (months)', B['f_tenure'][0], B['f_tenure'][1], key='f_tenure',
                       help=f'Repayment period in months ({rng("Loan_Tenure")}); 240 months = 20 years.')
        a, b, c = st.columns(3)
        a.number_input('Collateral value (₹, 0 = unsecured)', B['f_collateral'][0], B['f_collateral'][1],
                       step=10000, key='f_collateral', help='Market value of the property / vehicle. 0 = unsecured.')
        b.text_input('Collateral ID (optional, secured loans)', key='f_collateral_id',
                     help='Property or vehicle registration number. Used to stop the same asset backing two loans.')
        c.selectbox('Property area', O['f_area'], key='f_area', help='Not a model input (possible geographic proxy).')
        hint(errs, 'Loan_Type', 'Loan_Amount', 'Loan_Tenure', 'Collateral_Value', 'Collateral_ID', 'Property_Area')
        next_hint(4)
    with t5:
        ui.step_indicator(5, 5, STEPS, issues)
        left, right = st.columns([3, 2], gap='large')
        with left:
            st.html('<h4 style="margin:0 0 6px 0">Check the details</h4>')
            gender = app_now.get('Gender') or 'not given'
            dep = app_now['Dependents']
            rows = [('Applicant', f'Age {app_now["Age"]} · {dep if dep < 3 else "3+"} dependent{"" if dep == 1 else "s"}'
                                  f' · gender {gender} · {app_now.get("Marital_Status") or "marital status not given"}'),
                    ('IDs', f'Loan {app_now.get("Loan_ID", "auto")} · applicant {app_now.get("Applicant_ID", "auto")}'),
                    ('Employment', f'{app_now["Employment_Type"]} · {app_now["Work_Experience"]} years'),
                    ('Income', f'{fmt.rupee(app_now["Monthly_Income"])}/month + co-applicant '
                               f'{fmt.rupee(app_now.get("Coapplicant_Income", 0))}/month'),
                    ('Existing EMIs', f'{fmt.rupee(app_now["Existing_EMI"])}/month'),
                    ('Credit', 'New to credit (sent as -1)' if app_now['CIBIL_Score'] == -1
                     else f'CIBIL {app_now["CIBIL_Score"]}'),
                    ('Loan', f'{app_now["Loan_Type"]} · {fmt.rupee(app_now["Loan_Amount"])} over '
                             f'{app_now["Loan_Tenure"]} months'),
                    ('Collateral', f'{fmt.rupee(app_now.get("Collateral_Value"), missing="none (unsecured)")}'
                                   f'{" · " + app_now["Collateral_ID"] if app_now.get("Collateral_ID") else ""}'),
                    ('Property area', app_now['Property_Area'])]
            st.html(ui.kv_html(rows))
            if errs:
                ui.note('The backend will reject this input as invalid. You can still submit it to see how '
                        'it is handled.', 'warn', 'Fix before submitting',
                        [m for ms in errs.values() for m in ms])
        with right:
            st.html('<h4 style="margin:0 0 6px 0">Live preview</h4>')
            pv = facts_for(json.dumps(app_now, sort_keys=True, default=str))
            f = pv['facts']
            if not f:
                ui.note('Preview appears when every field is valid.', 'info')
            else:
                ltv = f.get('ltv')
                ui.tiles([
                    ('Proposed EMI', f'{fmt.rupee(f.get("proposed_emi"))}/mo',
                     f'at the indicative {fmt.pct(f.get("interest_rate"), 2)} rate', 'primary'),
                    ('FOIR', fmt.pct(f.get('foir')), f'limit {fmt.pct(f.get("foir_limit"), 0)} for this income',
                     'reject' if (f.get('foir') or 0) > (f.get('foir_limit') or 1) else 'approve'),
                    ('LTV', fmt.pct(ltv) if ltv is not None else 'unsecured',
                     f'RBI cap {fmt.pct(f.get("ltv_cap"), 0)}' if f.get('ltv_cap') is not None else 'no LTV cap applies',
                     'reject' if ltv is not None and f.get('ltv_cap') is not None and ltv > f['ltv_cap'] else None),
                    ('Age at maturity', fmt.years(f.get('age_at_maturity')), 'age when the last EMI is paid', None),
                ], min_width=150)
                st.html('<div class="cl-tile-help">From the rule engine\'s fact base (read-only). The decision '
                        'itself is made only when you submit.</div>')
        if st.button('Submit application', type='primary', icon=':material/send:', key='cl_submit'):
            submit(app_now, app_now)

with json_tab:
    st.html('<div class="cl-tile-help">Any JSON is accepted, including invalid values, so the graceful rejection '
            'of malformed input can be shown. Field names and units are those of the data contract.</div>')
    st.text_area('Application JSON', key='json_raw', height=220)
    if st.button('Submit JSON', icon=':material/data_object:'):
        try:
            payload = json.loads(ss['json_raw'])
        except ValueError as e:
            payload = None
            st.error(f'Not valid JSON: {e}')
        if payload is not None:
            submit(payload, payload if isinstance(payload, dict) else None)

if 'result' in ss:
    st.divider()
    common.decision_card(ss['result'])
    from components.max_amount_panel import render_max_amount_panel  # noqa: E402
    render_max_amount_panel(ss['result'])

    from cognilend.ml import compare  # noqa: E402

    @st.cache_data(show_spinner=False, max_entries=64)
    def _advise(app_json: str):
        return compare.advise(common.pipeline().explainer, json.loads(app_json))

    if ss['result'].get('model_version') and ss.get('last_app') and compare.available():
        with st.expander('Other models (advisory only, not used for the decision)'):
            try:
                st.dataframe(_advise(json.dumps(ss['last_app'], sort_keys=True, default=str)),
                             hide_index=True, width='stretch')
                st.caption('The decision above is made by the decision tree because only its rule path is a readable, '
                           'auditable reason. These predictions are not stored in the audit log.')
            except Exception as e:  # noqa: BLE001 - advisory panel must never break the decision page
                st.caption(f'Advisory models unavailable: {e}')
common.footer()
