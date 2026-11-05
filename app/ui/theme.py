"""Design tokens + CSS injection. Presentation only.

inject() is called once per script run (by common.setup). It writes the colour tokens for the active theme
(light or dark, from st.context.theme) as CSS custom properties, then app/assets/styles.css, which only uses them.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).resolve().parents[1] / 'assets'

SPACING = {'--cl-s1': '4px', '--cl-s2': '8px', '--cl-s3': '12px', '--cl-s4': '16px', '--cl-s5': '32px',
           '--cl-radius': '10px', '--cl-radius-lg': '14px'}

# Every text/background pair used for text is checked for WCAG AA (>= 4.5:1) by docs/ui/scripts/contrast.py.
TOKENS = {
    'light': {
        'bg': '#F5F7FA', 'surface': '#FFFFFF', 'text': '#13213C', 'muted': '#4A5568', 'muted-ink': '#3D4757',
        'border': '#D5DCE6', 'border-strong': '#A8B3C2', 'neutral-soft': '#EEF1F5',
        'primary': '#1D4F91', 'primary-ink': '#1D4F91', 'primary-soft': '#E8F0FB', 'primary-soft-2': '#C9DAF2',
        'primary-line': '#B5CBEA', 'on-primary': '#FFFFFF', 'focus': '#2563EB',
        'approve': '#1E7B45', 'approve-ink': '#136238', 'approve-soft': '#E7F6EC', 'approve-line': '#A7D8B8',
        'reject': '#C0322B', 'reject-ink': '#A1251F', 'reject-soft': '#FDECEA', 'reject-line': '#F2B8B3',
        'review': '#B45309', 'review-ink': '#8A4206', 'review-soft': '#FEF4E2', 'review-line': '#F0C47A',
        'shadow': '0 1px 2px rgba(16, 24, 40, .06), 0 1px 3px rgba(16, 24, 40, .05)',
    },
    'dark': {
        'bg': '#0E1525', 'surface': '#151E31', 'text': '#E6EBF3', 'muted': '#A9B4C6', 'muted-ink': '#C3CCDA',
        'border': '#2A3650', 'border-strong': '#44516C', 'neutral-soft': '#1D2840',
        'primary': '#5B9BFF', 'primary-ink': '#8DB8FF', 'primary-soft': '#1A2B4A', 'primary-soft-2': '#24406E',
        'primary-line': '#2F4C7F', 'on-primary': '#0B1220', 'focus': '#8DB8FF',
        'approve': '#34C77B', 'approve-ink': '#6EE7A7', 'approve-soft': '#10301F', 'approve-line': '#1F5C3B',
        'reject': '#F06A5F', 'reject-ink': '#FF9C93', 'reject-soft': '#3A1715', 'reject-line': '#6E2A25',
        'review': '#F5A524', 'review-ink': '#FFC768', 'review-soft': '#3A2A0E', 'review-line': '#6E4E14',
        'shadow': '0 1px 2px rgba(0, 0, 0, .4)',
    },
}


def mode() -> str:
    """'light' or 'dark' for the theme the browser is showing (falls back to light, e.g. in headless tests)."""
    try:
        t = st.context.theme.type
    except Exception:  # noqa: BLE001 - older runtimes / bare mode
        t = None
    return 'dark' if t == 'dark' else 'light'


def colour(name: str) -> str:
    return TOKENS[mode()][name]


@lru_cache(maxsize=1)
def _css() -> str:
    return (ASSETS / 'styles.css').read_text(encoding='utf-8')


@lru_cache(maxsize=1)
def logo_svg() -> str:
    return (ASSETS / 'logo.svg').read_text(encoding='utf-8')


def _vars(m: str) -> str:
    items = {**SPACING, **{f'--cl-{k}': v for k, v in TOKENS[m].items()}}
    return ':root{' + ';'.join(f'{k}:{v}' for k, v in items.items()) + '}'


def inject() -> None:
    # Style-only st.html blocks are not attached to the page in this Streamlit version, so the stylesheet goes in
    # through markdown (the documented unsafe_allow_html route). It renders nothing visible.
    st.markdown('<style>' + _vars(mode()) + ' ' + _css() + '</style>', unsafe_allow_html=True)
