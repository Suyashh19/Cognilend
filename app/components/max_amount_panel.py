"""'See maximum approvable amount' button shown under a Rejected decision (add-on, behind a feature flag).

Presentation only: the search is cognilend.addons.max_amount (read-only, advisory). The suggestion never
creates a decision; the applicant must submit a new application with the suggested amount.
"""
from __future__ import annotations

import json

import streamlit as st

from cognilend.addons import max_amount, suggestion_store


def _is_decision(obj) -> bool:
    return isinstance(obj, dict) and 'decision' in obj and 'audit_log_id' in obj


def _resolve(obj) -> tuple[dict | None, str | None]:
    """(application, loan_id) for either a raw application or a decision returned by pipeline.decide."""
    if not _is_decision(obj):
        return (obj if isinstance(obj, dict) else None), (obj or {}).get('Loan_ID')
    import common                                  # app/common.py: the app's cached pipeline and repository
    pipe = common.pipeline()
    engine = pipe.repo.engine if pipe.repo is not None else None
    return suggestion_store.application_for(obj, engine, pipe.fallback), obj.get('loan_id')


def _log(res: dict, loan_id: str | None):
    if not max_amount.settings().get('log_suggestions', True):
        return
    try:
        import common
        repo = common.pipeline().repo
        suggestion_store.log_suggestion(res, loan_id, repo.engine if repo is not None else None)
    except Exception:  # noqa: BLE001 - logging is best effort; the suggestion is shown regardless
        pass


def _show(res: dict, application: dict | None):
    fmt = max_amount.fmt_inr
    if res.get('error'):
        st.info(res['error'])
        return
    if not res.get('applicable'):
        st.info('The maximum approvable amount applies to rejected applications only; this application is '
                f'{res.get("original_decision", "not rejected")} when re-scored.')
        return
    if not res.get('possible'):
        why = res['explanation'].removeprefix('No lower amount can be approved: ')
        st.info(f'**No lower amount can be approved**\n\n{why[:1].upper()}{why[1:]}')
        return
    x, req = res['max_amount'], res['requested_amount']
    st.success(f'**Can be approved up to {fmt(x)}**  \n{res["explanation"]}')
    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Requested', fmt(req))
    c2.metric('Reduction', fmt(req - x), f'-{(req - x) / req:.0%}', delta_color='off')
    c3.metric(f'EMI at {fmt(x)} ({res["tenure_months"]:.0f} months)', fmt(res['emi_at_max']))
    c4.metric('Confidence at max', f'{res["confidence_at_max"]:.2f}')
    st.caption(f'Deciding limit: **{res["binding_limit"]}** · model {res["model_version"]} · '
               f'policy {res["policy_version"]} · {res["candidates_checked"]} amounts checked in '
               f'{res["runtime_ms"]:.0f} ms')
    st.caption('Suggestion only, not an approval. Submit a new application with this amount to get a decision.')
    if application is not None:
        with st.expander(f'Re-apply with {fmt(x)}'):
            st.caption('Same details with the new amount. Paste it into the "Raw JSON" tab and submit it yourself; '
                       'nothing is submitted automatically.')
            new = {k: v for k, v in application.items() if k != 'Loan_ID'} | {'Loan_Amount': int(x)}
            st.code(json.dumps(new, indent=1, default=str), language='json')


def render_max_amount_panel(application) -> None:
    """Button + result under a Rejected decision. `application` is the raw application dict, or the decision
    dict returned by pipeline.decide (its application is then read back, read-only). Renders nothing when the
    feature flag is off or the decision is not Rejected."""
    if not max_amount.enabled():
        return
    if _is_decision(application) and application.get('decision') != 'Rejected':
        return
    ident = (application.get('loan_id'), application.get('audit_log_id'), application.get('fallback_id')) \
        if _is_decision(application) else (application.get('Loan_ID'), json.dumps(application, sort_keys=True,
                                                                                   default=str))
    key = 'max_amount::' + '::'.join(str(i) for i in ident)
    if st.button('See maximum approvable amount', key=f'{key}::button'):
        if key not in st.session_state:
            with st.spinner('Searching for the highest amount that would be approved...'):
                app, loan_id = _resolve(application)
                if app is None:
                    st.session_state[key] = ({'error': 'The application details for this decision are not '
                                                       'available, so no amount can be suggested.'}, None)
                else:
                    res = max_amount.find_max_approvable_amount(app)
                    _log(res, loan_id)
                    st.session_state[key] = (res, app)
    if key in st.session_state:
        _show(*st.session_state[key])
