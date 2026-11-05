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


def _prefill(new: dict, amount: str):
    """'Re-apply': copy the application with the suggested amount into the form. Nothing is submitted."""
    import common
    skipped = common.prefill_form(new)
    st.session_state['cl_notice'] = (
        'ok', f'Form pre-filled with the suggested amount {amount}. Review the steps and press Submit application '
              'when ready — nothing has been submitted.' +
              (f' Not shown in the form (kept in the Raw JSON tab): {", ".join(skipped)}.' if skipped else ''))


def _compare_html(req: float, x: float, fmt) -> str:
    sug = max(0.0, min(100.0, x / req * 100)) if req else 0
    return ('<div class="cl-compare" role="img" aria-label="Requested versus suggested amount">'
            f'<div class="cl-compare-row"><span class="lbl">Requested</span><span class="bar"><span class="req" '
            f'style="width:100%"></span></span><span class="val">{fmt(req)}</span></div>'
            f'<div class="cl-compare-row"><span class="lbl">Suggested</span><span class="bar"><span class="sug" '
            f'style="width:{sug:.1f}%"></span></span><span class="val">{fmt(x)}</span></div></div>')


def _show(res: dict, application: dict | None):
    from ui import components as ui
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
        with st.container(key='cl-max-result-none'):
            st.info(f'**No lower amount can be approved**\n\n{why[:1].upper()}{why[1:]}', icon=':material/block:')
        return
    x, req = res['max_amount'], res['requested_amount']
    with st.container(border=True, key='cl-max-result'):
        top, side = st.columns([3, 2], gap='large')
        with top:
            st.html(f'<div class="cl-eyebrow">Maximum approvable amount · suggestion</div>'
                    f'<div class="cl-amount" aria-label="Suggested amount">{ui.esc(fmt(x))}</div>'
                    f'{_compare_html(req, x, fmt)}')
        with side:
            st.html(f'<div class="cl-tile-label">Binding limit</div>'
                    f'<div style="margin:4px 0 8px 0">{ui.status_badge_html("primary", res["binding_limit"])}</div>'
                    f'<div class="cl-tile-help">The rule or model limit that stops a higher amount. Only the loan '
                    f'amount was changed; every other detail is the same.</div>')
        st.success(f'**Can be approved up to {fmt(x)}**  \n{res["explanation"]}')
        c1, c2, c3, c4 = st.columns(4)
        c1.metric('Requested', fmt(req), border=True)
        c2.metric('Reduction', fmt(req - x), f'-{(req - x) / req:.0%}', delta_color='off', border=True)
        c3.metric(f'EMI at {fmt(x)} ({res["tenure_months"]:.0f} months)', fmt(res['emi_at_max']), border=True)
        c4.metric('Confidence at max', f'{res["confidence_at_max"]:.2f}', border=True)
        st.caption(f'Deciding limit: **{res["binding_limit"]}** · model {res["model_version"]} · '
                   f'policy {res["policy_version"]} · {res["candidates_checked"]} amounts checked in '
                   f'{res["runtime_ms"]:.0f} ms')
        st.caption('Suggestion only, not an approval. Submit a new application with this amount to get a decision.')
        if application is not None:
            with st.expander(f'Re-apply with {fmt(x)}', icon=':material/replay:'):
                st.caption('Same details with the new amount. Paste it into the "Raw JSON" tab and submit it yourself; '
                           'nothing is submitted automatically.')
                new = {k: v for k, v in application.items() if k != 'Loan_ID'} | {'Loan_Amount': int(x)}
                st.code(json.dumps(new, indent=1, default=str), language='json')
                st.button(f'Fill the form with {fmt(x)}', key=f'reapply::{json.dumps(new, sort_keys=True, default=str)}',
                          on_click=_prefill, args=(new, fmt(x)), icon=':material/edit_note:',
                          help='Copies these details into the application form and the Raw JSON tab. You submit it '
                               'yourself.')


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
    with st.container(key='cl-max-panel'):
        clicked = st.button('See maximum approvable amount', key=f'{key}::button', type='secondary',
                            icon=':material/currency_rupee:',
                            help='Finds the highest loan amount that would be approved with every other detail '
                                 'unchanged. Advisory only.')
    if clicked:
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
