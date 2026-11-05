"""Reusable UI pieces. Presentation only: no decision logic, no formulas. Every value shown is passed in by the
caller, who got it from a backend call.

Two kinds of helper:
  *_html(...)   return an HTML string (render with st.html, or combine several into one block);
  the others    render directly.
Helpers that render through st.html add no markdown / metric / alert elements, so they can be used on screens
whose element list is compared against the baseline (tests/addons/test_ui_panel.py) without changing it.
"""
from __future__ import annotations

import html
import json
from contextlib import contextmanager

import streamlit as st

from ui import format as fmt

OUTCOME_KIND = {'approved': 'approve', 'approve': 'approve', 'rejected': 'reject', 'reject': 'reject',
                'human review': 'review', 'review': 'review', 'in_review': 'review', 'open': 'review', 'primary': 'primary'}
KIND_ICON = {'approve': '✓', 'reject': '✕', 'review': '⚑', 'neutral': '•', 'primary': 'i'}
KIND_WORD = {'approve': 'Approved', 'reject': 'Rejected', 'review': 'Human Review'}


def esc(x) -> str:
    return html.escape('' if x is None else str(x))


def kind_of(outcome) -> str:
    return OUTCOME_KIND.get(str(outcome or '').strip().lower(), 'neutral')


# ---------------------------------------------------------------------------------------------------------
# headers, cards, layout
# ---------------------------------------------------------------------------------------------------------
def page_header(title: str, subtitle: str | None = None, eyebrow: str | None = None) -> None:
    eb = f'<div class="cl-eyebrow">{esc(eyebrow)}</div>' if eyebrow else ''
    sub = f'<p>{esc(subtitle)}</p>' if subtitle else ''
    st.html(f'<header class="cl-page-header">{eb}<h1>{esc(title)}</h1>{sub}</header>')


@contextmanager
def card(key: str | None = None, border: bool = True):
    """A bordered, padded container (Streamlit container, so any element can go inside)."""
    with st.container(border=border, key=key) as c:
        yield c


def card_html(title: str, body: str, kind: str | None = None) -> str:
    cls = f' {kind}' if kind else ''
    return f'<div class="cl-card{cls}"><h4>{esc(title)}</h4><p>{body}</p></div>'


# ---------------------------------------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------------------------------------
def status_badge_html(outcome, label: str | None = None) -> str:
    """Colour + icon + text, never colour alone."""
    k = kind_of(outcome)
    text = label or KIND_WORD.get(k) or str(outcome or '—')
    return (f'<span class="cl-badge {k}"><span class="cl-ico" aria-hidden="true">{KIND_ICON[k]}</span>'
            f'{esc(text)}</span>')


def status_badge(outcome, label: str | None = None) -> None:
    st.html(status_badge_html(outcome, label))


def rule_chip_html(rule_id: str, passed: bool | None, label: str | None = None, rule_type: str | None = None) -> str:
    """passed True -> ✓ green, False -> ✕ red (HARD) / ⚑ amber (SOFT), None -> – grey (not applicable)."""
    if passed is True:
        cls, ico, word = 'pass', '✓', 'passed'
    elif passed is False:
        soft = (rule_type or '').upper() == 'SOFT'
        cls, ico, word = ('warn', '⚑', 'fired') if soft else ('fail', '✕', 'fired')
    else:
        cls, ico, word = '', '–', 'not applied'
    text = f'{rule_id} {label}' if label else rule_id
    return (f'<span class="cl-chip {cls}" title="{esc(text)}: {word}"><span aria-hidden="true">{ico}</span>'
            f'{esc(text)}<span class="cl-sr-only"> {word}</span></span>')


def rule_chip(rule_id: str, passed: bool | None, label: str | None = None, rule_type: str | None = None) -> None:
    st.html(rule_chip_html(rule_id, passed, label, rule_type))


# ---------------------------------------------------------------------------------------------------------
# numbers
# ---------------------------------------------------------------------------------------------------------
def rupee(amount) -> str:
    return fmt.rupee(amount)


def metric_tile(label: str, value, help: str | None = None, border: bool = True) -> None:  # noqa: A002
    """A KPI tile (st.metric with a border)."""
    st.metric(label, value, help=help, border=border)


def tile_html(label: str, value, help: str | None = None, kind: str | None = None) -> str:  # noqa: A002
    cls = f' {kind}' if kind else ''
    h = f'<div class="cl-tile-help">{esc(help)}</div>' if help else ''
    return (f'<div class="cl-tile{cls}"><div class="cl-tile-label">{esc(label)}</div>'
            f'<div class="cl-tile-value">{esc(value)}</div>{h}</div>')


def tiles(items: list[tuple], min_width: int = 180) -> None:
    """Row of html tiles: items are (label, value[, help[, kind]])."""
    body = ''.join(tile_html(*it) for it in items)
    st.html(f'<div class="cl-grid" style="grid-template-columns:repeat(auto-fit,minmax({min_width}px,1fr))">'
            f'{body}</div>')


def confidence_meter_html(value: float | None, interval: list | tuple | None = None,
                          label: str = 'Confidence') -> str:
    """Bar 0..1 with the value and (optionally) the credible interval band. Display of given numbers only."""
    if value is None:
        return ''
    v = max(0.0, min(1.0, float(value)))
    ci = ''
    ci_text = ''
    if interval:
        lo, hi = max(0.0, float(interval[0])), min(1.0, float(interval[1]))
        ci = f'<div class="cl-meter-ci" style="left:{lo * 100:.1f}%;width:{max(hi - lo, 0) * 100:.1f}%"></div>'
        ci_text = f' · 90% interval {lo:.2f}–{hi:.2f}'
    return (f'<div class="cl-meter" role="img" aria-label="{esc(label)} {v:.2f}{esc(ci_text)}">'
            f'<div class="cl-meter-head"><span>{esc(label)} {v:.2f}{esc(ci_text)}</span></div>'
            f'<div class="cl-meter-track">{ci}<div class="cl-meter-fill" style="width:{v * 100:.1f}%;opacity:.85">'
            f'</div><div class="cl-meter-mark" style="left:calc({v * 100:.1f}% - 1px)"></div></div>'
            f'<div class="cl-meter-scale"><span>0</span><span>0.5</span><span>1</span></div></div>')


def confidence_meter(value: float | None, interval=None, label: str = 'Confidence') -> None:
    if value is not None:
        st.html(confidence_meter_html(value, interval, label))


# ---------------------------------------------------------------------------------------------------------
# explanations
# ---------------------------------------------------------------------------------------------------------
def reason_list(reasons: list[str] | str) -> None:
    """Reasons as a readable bullet list (markdown)."""
    items = [reasons] if isinstance(reasons, str) else list(reasons or [])
    if items:
        st.markdown('\n'.join(f'- {r}' for r in items))


def reason_list_html(reasons: list[str] | str) -> str:
    items = [reasons] if isinstance(reasons, str) else list(reasons or [])
    return '<ul>' + ''.join(f'<li>{esc(r)}</li>' for r in items) + '</ul>' if items else ''


def trail_html(steps: list[str], end: str | None = None, end_kind: str | None = None) -> str:
    """Step-by-step path: 'FOIR 0.32 ≤ 0.45 ✓ → CIBIL 742 > 698 ✓ → Approved'."""
    parts = [f'<span class="cl-step">{esc(s)} <span class="cl-ok" aria-label="condition met">✓</span></span>'
             for s in steps]
    if end:
        k = end_kind or 'neutral'
        parts.append(f'<span class="cl-step end {k}"><span aria-hidden="true">{KIND_ICON.get(k, "•")}</span>'
                     f'{esc(end)}</span>')
    arrow = '<span class="cl-arrow" aria-hidden="true">→</span>'
    return f'<div class="cl-trail" role="list">{arrow.join(parts)}</div>'


def kv_html(rows: list[tuple]) -> str:
    return '<dl class="cl-kv">' + ''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k, v in rows) + '</dl>'


# ---------------------------------------------------------------------------------------------------------
# states and messages
# ---------------------------------------------------------------------------------------------------------
def empty_state(message: str, icon: str = '○', hint: str | None = None) -> None:
    h = f'<div style="margin-top:4px;font-size:.85rem">{esc(hint)}</div>' if hint else ''
    st.html(f'<div class="cl-empty" role="status"><span class="cl-ico" aria-hidden="true">{esc(icon)}</span>'
            f'<strong>{esc(message)}</strong>{h}</div>')


def message_html(message: str, kind: str = 'info', title: str | None = None, items: list[str] | None = None) -> str:
    ico = {'error': '✕', 'warn': '!', 'ok': '✓', 'info': 'i'}[kind]
    role = 'alert' if kind == 'error' else 'status'
    t = f'<strong>{esc(title)}</strong><br>' if title else ''
    lst = reason_list_html(items) if items else ''
    return (f'<div class="cl-msg {kind}" role="{role}"><span class="cl-ico" aria-hidden="true">{ico}</span>'
            f'<div>{t}{esc(message)}{lst}</div></div>')


def error_box(message: str, title: str | None = 'Something went wrong') -> None:
    """Friendly error panel (role=alert)."""
    st.html(message_html(message, 'error', title))


def note(message: str, kind: str = 'info', title: str | None = None, items: list[str] | None = None) -> None:
    st.html(message_html(message, kind, title, items))


def step_indicator_html(current: int, total: int, labels: list[str] | None = None,
                        issues: set[int] | None = None) -> str:
    """Numbered steps 1..total; `current` is 1-based. Steps with issues get a red number."""
    labels = labels or [f'Step {i}' for i in range(1, total + 1)]
    issues = issues or set()
    lis = []
    for i in range(1, total + 1):
        state = 'current' if i == current else ('done' if i < current else '')
        if i in issues:
            state += ' issue'
        cur = ' aria-current="step"' if i == current else ''
        mark = '!' if i in issues else ('✓' if i < current else str(i))
        lis.append(f'<li class="{state.strip()}"{cur}><span class="n" aria-hidden="true">{mark}</span>'
                   f'{esc(labels[i - 1])}</li>')
    return f'<ol class="cl-stepper" aria-label="Application steps">{"".join(lis)}</ol>'


def step_indicator(current: int, total: int, labels: list[str] | None = None, issues: set[int] | None = None):
    st.html(step_indicator_html(current, total, labels, issues))


def copy_button(text: str, label: str = 'Copy', aria: str = 'Copy to clipboard') -> None:
    """Inline copy-to-clipboard button for a short value (e.g. the audit-log ID)."""
    payload = json.dumps(str(text))
    st.html(f'<div class="cl-audit"><code>{esc(text)}</code><button type="button" class="cl-copy" '
            f'aria-label="{esc(aria)}" onclick=\'(function(b){{var t={esc(payload)};'
            f'function done(){{b.textContent="Copied ✓";setTimeout(function(){{b.textContent="{esc(label)}"}},1500)}}'
            f'if(navigator.clipboard&&window.isSecureContext){{navigator.clipboard.writeText(t).then(done)}}'
            f'else{{var a=document.createElement("textarea");a.value=t;document.body.appendChild(a);a.select();'
            f'document.execCommand("copy");a.remove();done()}}}})(this)\'>{esc(label)}</button></div>',
            unsafe_allow_javascript=True)
