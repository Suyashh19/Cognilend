"""Shared UI helpers. Presentation only: every decision, query and computation is a call into src/cognilend."""
from __future__ import annotations

import streamlit as st

from cognilend.pipeline import DecisionPipeline

OUTCOME_COLOR = {'Approved': 'blue', 'Rejected': 'orange', 'Human Review': 'violet'}


@st.cache_resource
def pipeline() -> DecisionPipeline:
    return DecisionPipeline()


def repo():
    return pipeline().repo


def setup(title: str):
    st.set_page_config(page_title=f'CogniLend - {title}', layout='wide')
    st.title(title)


def rule_line(e: dict) -> str:
    """One rule evaluation as coloured text: red = HARD fired, orange = SOFT fired, green = passed."""
    def fmt(x):
        if isinstance(x, float):
            return f'{x:,.0f}' if abs(x) >= 1000 else f'{x:.4g}'
        return str(x)
    v = '' if e.get('value') is None else f' (value {fmt(e["value"])}, threshold {fmt(e.get("threshold"))})'
    if e['status'] == 'fired':
        colour = 'red' if e['type'] == 'HARD' else 'orange'
        return f':{colour}[**✗ {e["rule_id"]} {e["name"]}: fired ({e["type"]})**]{v}'
    if e['status'] == 'passed':
        return f':green[✓ {e["rule_id"]} {e["name"]}: passed]{v}'
    return f':gray[– {e["rule_id"]} {e["name"]}: {e["status"].replace("_", " ")}]'


def decision_card(d: dict):
    """Outcome, confidence + credible interval, reason, rules, tree path and audit id for one decision."""
    from cognilend.ml.tree_plot import draw_tree
    colour = OUTCOME_COLOR.get(d['decision'], 'gray')
    st.markdown(f'## :{colour}[{d["decision"]}]')
    c1, c2, c3, c4 = st.columns(4)
    conf = d.get('confidence')
    c1.metric('Confidence', f'{conf:.2f}' if conf is not None else '-')
    ci = d.get('confidence_ci')
    c2.metric('90% credible interval', f'{ci[0]:.2f} - {ci[1]:.2f}' if ci else 'rule decision')
    c3.metric('Audit-log ID', d['audit_log_id'] if d.get('audit_log_id') is not None else 'not stored')
    c4.metric('Decided by', d['source'])
    st.markdown('**Reason**')
    st.info(d['reason'])
    st.caption(f'Loan {d["loan_id"]} · applicant {d["applicant_id"]} · policy {d["policy_version"]} · '
               f'model {d.get("model_version") or "not consulted"} · leaf support {d.get("leaf_support") or "-"}')
    if d.get('fallback_id'):
        st.warning(f'Database unavailable: decision written to the fallback log ({d["fallback_id"]}) for replay.')
    if d.get('invalid_fields'):
        st.error('Invalid input in: ' + ', '.join(d['invalid_fields']))
    left, right = st.columns([1, 2])
    with left:
        st.markdown('**Policy rules**')
        evals = d.get('rule_evaluations') or []
        if not evals:
            st.markdown(':red[Rules not evaluated: the input failed contract validation.]')
        for e in evals:
            st.markdown(rule_line(e))
    with right:
        st.markdown('**Decision tree** (this applicant\'s path in bold)')
        if d.get('tree_path'):
            nodes = {s['node'] for s in d['tree_path']}
            st.pyplot(draw_tree(pipeline().explainer, nodes, d.get('leaf'), figsize=(13, 5.5)))
            st.markdown('\n'.join(f'- {s["text"]}' for s in d['tree_path']))
        else:
            st.markdown(':gray[Model not consulted (HARD rule or invalid input; FR-6).]')
