"""Display formatting only (Indian rupee grouping, percentages, dates). Never used to build backend inputs:
values sent to the pipeline are always the raw widget values."""
from __future__ import annotations

import math
from datetime import date, datetime, timezone

MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def indian_group(n: int) -> str:
    """2790000 -> '27,90,000' (lakh / crore grouping)."""
    sign, s = ('-' if n < 0 else ''), str(abs(int(n)))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return sign + ','.join([*groups, tail])


def rupee(amount, decimals: int = 0, missing: str = '—') -> str:
    """₹ with Indian grouping: 2790000 -> '₹27,90,000'."""
    v = _num(amount)
    if v is None:
        return missing
    if decimals:
        whole, frac = f'{abs(v):.{decimals}f}'.split('.')
        return f'{"-" if v < 0 else ""}₹{indian_group(int(whole))}.{frac}'
    n = int(round(v))
    return f'-₹{indian_group(-n)}' if n < 0 else f'₹{indian_group(n)}'


def rupee_short(amount, missing: str = '—') -> str:
    """Compact amount for tight spaces: ₹27.9 L, ₹1.25 Cr."""
    v = _num(amount)
    if v is None:
        return missing
    a = abs(v)
    if a >= 1e7:
        return f'₹{v / 1e7:.2f} Cr'
    if a >= 1e5:
        return f'₹{v / 1e5:.1f} L'
    return rupee(v)


def pct(x, decimals: int = 1, missing: str = '—') -> str:
    """0.3214 -> '32.1%'."""
    v = _num(x)
    return missing if v is None else f'{v * 100:.{decimals}f}%'


def number(x, decimals: int = 2, missing: str = '—') -> str:
    v = _num(x)
    return missing if v is None else f'{v:.{decimals}f}'


def _as_datetime(d) -> datetime | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d
    if isinstance(d, date):
        return datetime(d.year, d.month, d.day)
    try:
        return datetime.fromisoformat(str(d))
    except ValueError:
        return None


def date_in(d, missing: str = '—') -> str:
    """'05 Nov 2026'."""
    dt = _as_datetime(d)
    return missing if dt is None else f'{dt.day:02d} {MONTHS[dt.month - 1]} {dt.year}'


def datetime_in(d, missing: str = '—', utc_label: bool = True) -> str:
    """'05 Nov 2026, 14:03 UTC' (the database stores UTC timestamps)."""
    dt = _as_datetime(d)
    if dt is None:
        return missing
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return f'{date_in(dt)}, {dt:%H:%M}' + (' UTC' if utc_label else '')


def years(x, missing: str = '—') -> str:
    v = _num(x)
    return missing if v is None else f'{v:.1f} years'
