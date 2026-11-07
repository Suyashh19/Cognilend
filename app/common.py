"""Shared UI helpers. Presentation only: every decision, query and computation is a call into src/cognilend."""
from __future__ import annotations

import base64
import io
import json
from datetime import datetime, timezone

import streamlit as st

from cognilend.pipeline import DecisionPipeline
from ui import components as ui
from ui import format as fmt
from ui import theme

# Markdown colour names of the outcome headline (kept from the original card). The colour actually shown follows
# the outcome through the design system (green Approved, red Rejected, amber Human Review), see styles.css.
OUTCOME_COLOR = {'Approved': 'blue', 'Rejected': 'orange', 'Human Review': 'violet'}
OUTCOME_ICON = {'Approved': ':material/check_circle:', 'Rejected': ':material/cancel:',
                'Human Review': ':material/person_search:'}

SUBTITLES = {
    'CogniLend': 'Explainable, fair loan decisions: policy rules first, an interpretable model second, every '
                 'decision audited.',
    'New Application': 'Enter the applicant\'s details step by step, review the numbers, then submit for a decision.',
    'Officer Review Queue': 'Cases the system routed to a loan officer. Review the explanation and record a '
                            'Human Review decision with a note.',
    'Audit Explorer': 'Search past decisions, follow an applicant\'s history and verify the tamper-evident audit chain.',
    'Model & Policy': 'The policy rules and the constrained decision tree in force, with their measured performance.',
    'Fairness Dashboard': 'Disparate impact of the decisions across applicant subgroups, against the 0.80 threshold.',
    'Stress Twin (advisory)': 'A Monte Carlo cash-flow stress test of the loan. Advisory only: it never changes a '
                              'decision.',
    'Model Comparison': 'How the decision tree compares with ensemble models trained on the same data.',
    'Style guide': 'Every design-system component, for review.',
}

PROJECT = {'college': 'Walchand College of Engineering, Sangli', 'programme': 'TY AIML Mini Project · AY 2026-27',
           'initiative': 'Apni Leap Initiative', 'guide': 'Dr. V. N. Waghmare',
           'groups': 'G10 Core ML · G12 Rules + DBMS · G15 Data collection/creation + Preprocessing + Fairness'}


@st.cache_resource
def pipeline() -> DecisionPipeline:
    return DecisionPipeline()


def repo():
    return pipeline().repo


# ---------------------------------------------------------------------------------------------------------
# app shell
# ---------------------------------------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def versions_in_force() -> dict:
    """Latest registered policy and model version, as listed on the Model & Policy page (repo().versions())."""
    try:
        v = repo().versions()
    except Exception:  # noqa: BLE001 - the header must render even without a database
        return {'policy': None, 'model': None}

    def latest(rows, key):
        rows = [r for r in rows if r.get('version')]
        return max(rows, key=lambda r: str(r.get(key) or ''))['version'] if rows else None
    models = [m for m in v.get('models', []) if str(m.get('version', '')).startswith('dt_')] or v.get('models', [])
    return {'policy': latest(v.get('policies', []), 'activated_at'), 'model': latest(models, 'created_at')}


def _logo_img(size: int = 40) -> str:
    b64 = base64.b64encode(theme.logo_svg().encode('utf-8')).decode('ascii')
    return f'<img src="data:image/svg+xml;base64,{b64}" width="{size}" height="{size}" alt="">'


def appbar() -> None:
    v = versions_in_force()
    pol = f'Policy {v["policy"]}' if v['policy'] else 'Policy —'
    mod = f'Model {v["model"]}' if v['model'] else 'Model —'
    st.html(f'<div class="cl-appbar" role="banner"><div class="cl-brand">{_logo_img()}<div>'
            f'<div class="cl-brand-name">CogniLend</div><div class="cl-brand-tag">Explainable, fair loan decisioning'
            f'</div></div></div><div class="cl-appbar-meta" aria-label="Versions in force">'
            f'<span class="cl-pill" title="Policy rule set in force">⚖ {ui.esc(pol)}</span>'
            f'<span class="cl-pill" title="Decision model in force">⌥ {ui.esc(mod)}</span></div></div>')


NAV = [  # (section, label, page file relative to app/, icon). Same URLs as before: /New_Application, ...
    ('Apply', 'Home', 'views/home.py', ':material/home:'),
    ('Apply', 'New Application', 'views/new_application.py', ':material/edit_document:'),
    ('Operations', 'Review Queue', 'views/review_queue.py', ':material/person_search:'),
    ('Operations', 'Audit Explorer', 'views/audit_explorer.py', ':material/fact_check:'),
    ('Governance', 'Model & Policy', 'views/model_and_policy.py', ':material/account_tree:'),
    ('Governance', 'Fairness', 'views/fairness.py', ':material/balance:'),
    ('Governance', 'Model Comparison', 'views/model_comparison.py', ':material/leaderboard:'),
    ('Advisory', 'Stress Twin', 'views/stress_twin.py', ':material/monitoring:'),
]


def sidebar_nav() -> None:
    """Sidebar navigation with sections and icons; the current page is highlighted by st.page_link.

    Rendered by every page (not only by st.navigation) because a deep link opened as the very first request
    after the server starts is served in Streamlit's legacy pages/ mode, where st.navigation has not run yet."""
    import os
    items = list(NAV)
    if os.environ.get('COGNILEND_UI_DEBUG') == '1':
        items.append(('Developer', 'Style guide', 'views/style_guide.py', ':material/palette:'))
    section = None
    for sec, label, path, icon in items:
        candidates = [path] + (['streamlit_app.py'] if path == 'views/home.py' else [])
        for target in candidates:
            try:
                if sec != section:
                    st.sidebar.html(f'<div class="cl-nav-section">{ui.esc(sec)}</div>')
                    section = sec
                st.sidebar.page_link(target, label=label, icon=icon, width='stretch')
                break
            except Exception:  # noqa: BLE001 - page not registered in this mode (or a page run on its own)
                continue


def sidebar_footer() -> None:
    p = PROJECT
    st.sidebar.html(f'<div class="cl-side-foot"><strong>{ui.esc(p["college"])}</strong><br>{ui.esc(p["programme"])}'
                    f'<br>Guide: {ui.esc(p["guide"])}<br>{ui.esc(p["groups"])}</div>')


def footer() -> None:
    p = PROJECT
    st.html(f'<footer class="cl-footer"><strong>CogniLend</strong> · {ui.esc(p["programme"])} · '
            f'{ui.esc(p["college"])} · {ui.esc(p["initiative"])}<br>Guide: <strong>{ui.esc(p["guide"])}</strong>'
            f' · Groups: {ui.esc(p["groups"])}<br>Decisions are explainable and audited; suggestions and the stress '
            f'twin are advisory only.</footer>')


def setup(title: str, subtitle: str | None = None):
    st.set_page_config(page_title=f'CogniLend - {title}', page_icon=str(theme.ASSETS / 'logo.svg'), layout='wide')
    theme.inject()
    try:
        st.logo(str(theme.ASSETS / 'logo.svg'), size='large')
    except Exception:  # noqa: BLE001 - logo is decoration only
        pass
    sidebar_nav()
    sidebar_footer()
    appbar()
    ui.page_header(title, subtitle if subtitle is not None else SUBTITLES.get(title))


# ---------------------------------------------------------------------------------------------------------
# decision result
# ---------------------------------------------------------------------------------------------------------
@st.cache_data(show_spinner=False, max_entries=64)
def tree_png(nodes: tuple, leaf, highlight: bool, figsize=(13, 5.5)) -> bytes:
    """The existing tree figure (cognilend.ml.tree_plot.draw_tree), rendered once per path to PNG bytes."""
    import matplotlib.pyplot as plt

    from cognilend.ml.tree_plot import draw_tree
    fig = draw_tree(pipeline().explainer, set(nodes) if highlight else None, leaf if highlight else None,
                    figsize=figsize)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=130, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def _value_text(step: dict) -> str:
    """'FOIR 0.32 ≤ 0.45' from a tree-path step (display formatting of the step's own numbers)."""
    from cognilend.ml.explain import FORMATS, LABELS
    f = step.get('feature')
    label = LABELS.get(f, f)
    op = '≤' if step.get('direction') == '<=' else '>'
    money = {'total_income', 'existing_emi', 'loan_amount'}

    def show(x):
        if x is None:
            return '—'
        if f in money:
            return fmt.rupee(x)
        try:
            return FORMATS[f].format(x)
        except (KeyError, ValueError, TypeError):
            return f'{x:.3g}' if isinstance(x, float) else str(x)
    if f not in LABELS:
        return step.get('text', '')
    return f'{label} {show(step.get("applicant_value"))} {op} {show(step.get("threshold"))}'


def plain_summary(d: dict) -> str:
    """One plain-language sentence for the outcome, from the decision's own fields (no new logic)."""
    dec, src = d.get('decision'), d.get('source')
    if d.get('invalid_fields'):
        return ('The application could not be assessed because some details are missing or invalid. Correct the '
                'fields listed below and submit again.')
    if dec == 'Approved':
        return 'The application meets every policy rule and the model is confident it should be approved.'
    if dec == 'Rejected' and src == 'RULE':
        return 'A mandatory policy rule is not met, so the application is declined. The model was not consulted.'
    if dec == 'Rejected':
        return 'The application passes the policy rules, but the model is confident it should be declined.'
    if dec == 'Human Review':
        if src == 'MODEL':
            return ('The model is not confident enough to decide on its own, so a loan officer will review the '
                    'application.')
        return 'A rule asks for a person to check this application, so it goes to a loan officer for Human Review.'
    return 'See the reason below.'


def summary_html(d: dict) -> str:
    """Self-contained HTML summary of the result already on screen (for 'Download summary')."""
    k = ui.kind_of(d.get('decision'))
    colour = {'approve': '#136238', 'reject': '#A1251F', 'review': '#8A4206'}.get(k, '#13213C')
    ci = d.get('confidence_ci')
    conf = d.get('confidence')
    rows = [('Decision', d.get('decision')), ('Decided by', d.get('source')),
            ('Confidence', f'{conf:.2f}' if conf is not None else '—'),
            ('90% credible interval', f'{ci[0]:.2f} – {ci[1]:.2f}' if ci else 'rule decision'),
            ('Audit-log ID', d.get('audit_log_id') if d.get('audit_log_id') is not None else 'not stored'),
            ('Loan ID', d.get('loan_id')), ('Applicant ID', d.get('applicant_id')),
            ('Policy version', d.get('policy_version')), ('Model version', d.get('model_version') or 'not consulted'),
            ('Leaf support', d.get('leaf_support') or '—')]
    evals = d.get('rule_evaluations') or []
    rule_rows = ''.join(f'<tr><td>{ui.esc(e["rule_id"])}</td><td>{ui.esc(e["type"])}</td><td>{ui.esc(e["name"])}</td>'
                        f'<td>{ui.esc(e["status"].replace("_", " "))}</td></tr>' for e in evals)
    path = ''.join(f'<li>{ui.esc(s.get("text"))}</li>' for s in (d.get('tree_path') or []))
    now = datetime.now(timezone.utc)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CogniLend decision {ui.esc(d.get('loan_id'))}</title>
<style>body{{font-family:"Segoe UI",Arial,sans-serif;color:#13213C;max-width:820px;margin:32px auto;padding:0 16px}}
h1{{font-size:22px;margin:0}}.out{{font-size:28px;font-weight:800;color:{colour};margin:12px 0}}
table{{border-collapse:collapse;width:100%;margin:12px 0}}td,th{{border:1px solid #D5DCE6;padding:6px 8px;text-align:left;font-size:14px}}
th{{background:#EEF1F5}}.reason{{background:#E8F0FB;border:1px solid #B5CBEA;padding:10px 12px;border-radius:8px}}
.muted{{color:#4A5568;font-size:12px}}</style></head><body>
<h1>CogniLend — decision summary</h1><div class="muted">Generated {fmt.datetime_in(now)} from the result shown in the app.</div>
<div class="out">{ui.esc(d.get('decision'))}</div><p>{ui.esc(plain_summary(d))}</p>
<h2>Reason</h2><div class="reason">{ui.esc(d.get('reason'))}</div>
<h2>Details</h2><table>{''.join(f'<tr><th>{ui.esc(a)}</th><td>{ui.esc(b)}</td></tr>' for a, b in rows)}</table>
<h2>Policy rules</h2><table><tr><th>Rule</th><th>Type</th><th>Name</th><th>Status</th></tr>{rule_rows or '<tr><td colspan=4>Rules not evaluated (invalid input)</td></tr>'}</table>
<h2>Decision-tree path</h2>{f'<ol>{path}</ol>' if path else '<p>Model not consulted.</p>'}
<p class="muted">Confidence is the estimated approval probability, not a guarantee of repayment. Walchand College of Engineering, Sangli — CogniLend.</p>
</body></html>"""


def new_application_link() -> None:
    """'Start a new application': in-app link that clears the result and the form (?new=1)."""
    try:
        st.page_link('views/new_application.py', label='Start a new application', icon=':material/add:',
                     query_params={'new': '1'}, width='stretch')
    except Exception:  # noqa: BLE001 - page registry unavailable (page run on its own, e.g. headless tests)
        st.html('<a class="cl-copy" style="display:inline-block;text-decoration:none" href="New_Application?new=1" '
                'target="_self">＋ Start a new application</a>')


def _rules_html(evals: list[dict]) -> str:
    order = {'fired': 0, 'passed': 1}
    chips = []
    for e in sorted(evals, key=lambda e: (order.get(e['status'], 2), e['rule_id'])):
        passed = True if e['status'] == 'passed' else False if e['status'] == 'fired' else None
        chips.append(ui.rule_chip_html(e['rule_id'], passed, e['name'], e['type']))
    return f'<div role="list" aria-label="Policy rules">{"".join(chips)}</div>'


def decision_card(d: dict):
    """Outcome, confidence + credible interval, reason, rules, tree path and audit id for one decision."""
    import pandas as pd
    kind = ui.kind_of(d['decision'])
    colour = OUTCOME_COLOR.get(d['decision'], 'gray')
    with st.container(border=True, key=f'cl-decision-{kind}'):
        head, actions = st.columns([5, 2], vertical_alignment='center')
        with head:
            ico, txt = st.columns([1, 9], vertical_alignment='center', gap='small')
            ico.html(f'<span class="cl-outcome-ico {kind}" aria-hidden="true">{ui.KIND_ICON.get(kind, "•")}</span>')
            with txt:
                with st.container(key=f'cl-outcome-{kind}'):
                    st.markdown(f'## :{colour}[{d["decision"]}]')
                st.html(f'<div class="cl-outcome-sub">{ui.esc(plain_summary(d))}</div>')
        with actions:
            st.download_button('Download summary', summary_html(d), file_name=f'cognilend_{d.get("loan_id")}.html',
                               mime='text/html', icon=':material/download:', key=f'dl::{d.get("loan_id")}::'
                               f'{d.get("audit_log_id")}', width='stretch', on_click='ignore')
            new_application_link()

        c1, c2, c3, c4 = st.columns(4)
        conf = d.get('confidence')
        c1.metric('Confidence', f'{conf:.2f}' if conf is not None else '-', border=True,
                  help='Estimated approval probability. This is not a guarantee of repayment.')
        ci = d.get('confidence_ci')
        c2.metric('90% credible interval', f'{ci[0]:.2f} - {ci[1]:.2f}' if ci else 'rule decision', border=True,
                  help='Bayesian uncertainty range around the model estimate. Rule-only decisions have no model interval.')
        c3.metric('Audit-log ID', d['audit_log_id'] if d.get('audit_log_id') is not None else 'not stored',
                  border=True, help='Sequence number of this decision in the hash-chained audit log.')
        c4.metric('Decided by', d['source'], border=True,
                  help='RULE: a policy rule decided. MODEL: the decision tree decided.')
        m1, m2 = st.columns([3, 2], vertical_alignment='center')
        with m1:
            if conf is not None and ci:
                ui.confidence_meter(conf, ci, 'Model confidence')
        with m2:
            if d.get('audit_log_id') is not None:
                ui.copy_button(str(d['audit_log_id']), 'Copy audit ID', 'Copy the audit-log ID')

        if d.get('fallback_id'):
            st.warning(f'Database unavailable: decision written to the fallback log ({d["fallback_id"]}) for replay.')
        if d.get('invalid_fields'):
            st.error('Invalid input in: ' + ', '.join(d['invalid_fields']))

        st.markdown('#### Why this decision')
        st.caption('The explanation below shows the policy or model evidence used for this result.')
        st.info(d['reason'], icon=':material/lightbulb:')

        evals = d.get('rule_evaluations') or []
        st.markdown('**Policy rules**')
        if not evals:
            st.markdown(':red[Rules not evaluated: the input failed contract validation.]')
        else:
            st.html(_rules_html(evals))

        st.markdown('**Decision-tree path**')
        if d.get('tree_path'):
            steps = [_value_text(s) for s in d['tree_path']]
            pred = d.get('model_prediction')
            end = f'Model: {pred}' + (f' → {d["decision"]}' if pred and pred != d['decision'] else '')
            st.html(ui.trail_html(steps, end, ui.kind_of(d['decision'])))
        else:
            st.caption('Model not consulted (HARD rule or invalid input; FR-6).')

        st.caption(f'Loan {d["loan_id"]} · applicant {d["applicant_id"]} · policy {d["policy_version"]} · '
                   f'model {d.get("model_version") or "not consulted"} · leaf support {d.get("leaf_support") or "-"}')

        if d.get('tree_path'):
            with st.expander('Decision tree (this applicant\'s path highlighted)', icon=':material/account_tree:'):
                nodes = tuple(sorted({s['node'] for s in d['tree_path']}))
                st.image(tree_png(nodes, d.get('leaf'), True), width='stretch')
                st.html(ui.reason_list_html([s['text'] for s in d['tree_path']]))
        with st.expander('Raw values', icon=':material/data_object:'):
            if evals:
                raw = pd.DataFrame(evals)[['rule_id', 'type', 'name', 'status', 'value', 'threshold']]
                raw[['value', 'threshold']] = raw[['value', 'threshold']].map(lambda v: '' if v is None else str(v))
                st.dataframe(raw, hide_index=True, width='stretch')
            if d.get('tree_path'):
                st.dataframe(pd.DataFrame(d['tree_path'])[['feature', 'direction', 'threshold', 'applicant_value',
                                                           'imputed', 'contribution']],
                             hide_index=True, width='stretch')
            st.json({k: v for k, v in d.items() if k not in ('rule_evaluations', 'tree_path')}, expanded=False)
        with st.expander('Model and policy version', icon=':material/verified:'):
            st.html(ui.kv_html([('Policy version', d.get('policy_version')),
                                ('Model version', d.get('model_version') or 'not consulted'),
                                ('Model recommendation', d.get('model_prediction') or '—'),
                                ('Tree leaf', d.get('leaf') if d.get('leaf') is not None else '—'),
                                ('Leaf support (training cases)', d.get('leaf_support') or '—'),
                                ('Decision ID', d.get('decision_id') if d.get('decision_id') is not None else '—'),
                                ('Stored in database', 'yes' if d.get('persisted') else 'no')]))


# ---------------------------------------------------------------------------------------------------------
# application form state (shared by the New Application page and the max-amount "Re-apply" action)
# ---------------------------------------------------------------------------------------------------------
FORM_KEYS = {'Loan_ID': 'f_loan_id', 'Applicant_ID': 'f_applicant_id', 'Collateral_ID': 'f_collateral_id',
             'Age': 'f_age', 'Gender': 'f_gender', 'Marital_Status': 'f_marital', 'Dependents': 'f_dependents',
             'Employment_Type': 'f_employment', 'Work_Experience': 'f_experience', 'Monthly_Income': 'f_income',
             'Coapplicant_Income': 'f_coapp', 'Existing_EMI': 'f_emi', 'Property_Area': 'f_area',
             'Loan_Type': 'f_loan_type', 'Loan_Amount': 'f_amount', 'Loan_Tenure': 'f_tenure',
             'Collateral_Value': 'f_collateral'}
# Defaults of the original form (unchanged)
FORM_DEFAULTS = {'f_loan_id': '', 'f_applicant_id': '', 'f_collateral_id': '', 'f_age': 35, 'f_gender': '',
                 'f_marital': '', 'f_dependents': 1, 'f_employment': None, 'f_experience': 10, 'f_income': 150_000,
                 'f_coapp': 0, 'f_emi': 0, 'f_ntc': False, 'f_cibil': 780, 'f_area': None, 'f_loan_type': None,
                 'f_amount': 3_000_000, 'f_tenure': 240, 'f_collateral': 5_000_000}


def form_bounds() -> dict:
    """Widget bounds of the original form, read from the data contract (unchanged)."""
    from cognilend.data import contract
    F = contract.FIELDS
    return {'f_age': (int(F['Age'].min), int(F['Age'].max)), 'f_experience': (0, int(F['Work_Experience'].max)),
            'f_income': (int(F['Monthly_Income'].min), int(F['Monthly_Income'].max)),
            'f_coapp': (int(F['Coapplicant_Income'].min), int(F['Coapplicant_Income'].max)),
            'f_emi': (int(F['Existing_EMI'].min), int(F['Existing_EMI'].max)),
            'f_cibil': (int(F['CIBIL_Score'].min), int(F['CIBIL_Score'].max)),
            'f_amount': (int(F['Loan_Amount'].min), int(F['Loan_Amount'].max)),
            'f_tenure': (int(F['Loan_Tenure'].min), int(F['Loan_Tenure'].max)),
            'f_collateral': (int(F['Collateral_Value'].min), int(F['Collateral_Value'].max))}


def form_options() -> dict:
    from cognilend.data import contract
    F = contract.FIELDS
    return {'f_gender': ['', *F['Gender'].allowed], 'f_marital': ['', *F['Marital_Status'].allowed],
            'f_dependents': [0, 1, 2, 3], 'f_employment': list(F['Employment_Type'].allowed),
            'f_area': list(F['Property_Area'].allowed), 'f_loan_type': list(F['Loan_Type'].allowed)}


def prefill_form(app: dict) -> list[str]:
    """Copy an application into the form widgets (session state only; nothing is submitted). Returns the fields
    that could not be shown in the form (they stay in the Raw JSON tab, which always gets the full application)."""
    bounds, opts, skipped = form_bounds(), form_options(), []
    ss = st.session_state
    for field, key in FORM_KEYS.items():
        v = app.get(field)
        if key in ('f_loan_id', 'f_applicant_id', 'f_collateral_id'):
            ss[key] = v if isinstance(v, str) else ('' if v is None else str(v))
        elif key in opts:
            if v is None and '' in opts[key]:
                ss[key] = ''
            elif v in opts[key]:
                ss[key] = v
            else:
                skipped.append(field)
        else:
            lo, hi = bounds[key]
            if v is None and key in ('f_coapp', 'f_collateral'):
                ss[key] = 0
            elif isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer() and lo <= v <= hi:
                ss[key] = int(v)
            else:
                skipped.append(field)
    c = app.get('CIBIL_Score')
    if c == -1:
        ss['f_ntc'] = True
    elif isinstance(c, (int, float)) and not isinstance(c, bool) and float(c).is_integer() and \
            bounds['f_cibil'][0] <= c <= bounds['f_cibil'][1]:
        ss['f_ntc'], ss['f_cibil'] = False, int(c)
    else:
        skipped.append('CIBIL_Score')
    ss['json_raw'] = json.dumps(app, indent=1, default=str)
    return skipped


def reset_form() -> None:
    for k in list(FORM_DEFAULTS) + ['json_raw']:
        st.session_state.pop(k, None)
