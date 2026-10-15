"""Monte Carlo cash-flow stress test of a borrower over the loan's first year (advisory only).

Each month, on day `income_day` (+ any delay) the income arrives, essentials are spent evenly through the month, and
all EMIs leave on `emi_due_day`. The balance is checked at the EMI due date and at month end. Shocks per path:
  income_drop    income x (1 - d), d ~ U(0.2, 0.5), for k ~ {1,2,3} consecutive months
  expense_spike  one extra outlay of m x essentials, m ~ U(1, 2), in one month
  payment_delay  income arrives 5-15 days late in one month
  combined       all three on the same path
Metrics (pure functions below, unit-tested):
  min cash balance, shortfall probability, max shortfall, months in deficit, recovery time, stressed FOIR,
  buffer coverage (months), resilience score 0-100.  Bands and weights: config/stress_twin.yaml (illustrative).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from cognilend import config


def cfg() -> dict:
    return config.load('stress_twin')


def emi(amount: float, annual_rate: float, tenure_months: int) -> float:
    r = annual_rate / 12
    if r == 0:
        return amount / tenure_months
    g = (1 + r) ** tenure_months
    return amount * r * g / (g - 1)


@dataclass
class StressInputs:
    income_mean: float | None            # net monthly income, INR
    income_cv: float | None              # sigma / mu of monthly income
    income_day: int | None               # day of month income is credited (1-28)
    essentials: float | None             # essential monthly expenses, INR
    existing_emi: float = 0.0
    loan_amount: float | None = None
    annual_rate: float | None = None
    tenure_months: int | None = None
    proposed_emi: float | None = None    # given directly, or computed from amount / rate / tenure
    emi_due_day: int = 5
    savings: float = 0.0                 # liquid savings at the start
    extra: dict = field(default_factory=dict)

    def missing(self) -> list[str]:
        need = ['income_mean', 'income_cv', 'income_day', 'essentials']
        out = [k for k in need if getattr(self, k) is None]
        if self.proposed_emi is None and None in (self.loan_amount, self.annual_rate, self.tenure_months):
            out.append('proposed_emi (or loan_amount + annual_rate + tenure_months)')
        return out

    def total_emi(self) -> float:
        p = self.proposed_emi if self.proposed_emi is not None else emi(self.loan_amount, self.annual_rate,
                                                                         self.tenure_months)
        return float(self.existing_emi + p)


# --------------------------------------------------------------------------------------
# Metric formulas (pure, unit-tested)
# --------------------------------------------------------------------------------------
def min_cash_balance(checkpoints: np.ndarray) -> np.ndarray:
    """Per path: lowest balance over all checkpoints. checkpoints shape (paths, points)."""
    return np.asarray(checkpoints, dtype=float).min(axis=1)


def shortfall_probability(path_minima: np.ndarray) -> float:
    """Share of paths whose balance ever goes below zero."""
    return float((np.asarray(path_minima) < 0).mean())


def max_shortfall(path_minima: np.ndarray) -> float:
    """Largest deficit (positive INR) over all paths; 0 if no path goes negative."""
    return float(max(0.0, -np.min(path_minima)))


def months_in_deficit(month_end: np.ndarray) -> np.ndarray:
    """Per path: number of months ending with a negative balance."""
    return (np.asarray(month_end) < 0).sum(axis=1)


def recovery_time(month_end: np.ndarray) -> np.ndarray:
    """Per path: months from the first deficit month to the first later month back at >= 0.
    0 if the path never goes negative; horizon - first_deficit if it never recovers (censored)."""
    me = np.asarray(month_end)
    out = np.zeros(me.shape[0])
    horizon = me.shape[1]
    for i, row in enumerate(me):
        neg = np.flatnonzero(row < 0)
        if not len(neg):
            continue
        first = neg[0]
        back = np.flatnonzero(row[first:] >= 0)
        out[i] = back[0] if len(back) else horizon - first
    return out


def stressed_foir(total_emi: float, incomes: np.ndarray) -> np.ndarray:
    """Per path: EMIs / lowest monthly income received on that path (inf if income hits zero)."""
    low = np.asarray(incomes, dtype=float).min(axis=1)
    with np.errstate(divide='ignore'):
        return np.where(low > 0, total_emi / low, np.inf)


def buffer_coverage(savings: float, essentials: float, total_emi: float) -> float:
    """Months of essentials + EMIs that liquid savings cover."""
    outflow = essentials + total_emi
    return float(savings / outflow) if outflow > 0 else float('inf')


def resilience_score(p_shortfall: float, buffer_months: float, foir: float, c: dict | None = None) -> float:
    """0-100: weighted (1 - shortfall prob), buffer (full credit at N months) and FOIR headroom (1 - FOIR)."""
    c = c or cfg()
    w = c['resilience_weights']
    buffer_part = min(max(buffer_months, 0.0) / c['buffer_full_credit_months'], 1.0)
    foir_part = 0.0 if not np.isfinite(foir) else min(max(1.0 - foir, 0.0), 1.0)
    score = 100 * (w['no_shortfall'] * (1 - p_shortfall) + w['buffer'] * buffer_part + w['foir'] * foir_part)
    return float(round(min(max(score, 0.0), 100.0), 1))


def band(p_shortfall: float | None, c: dict | None = None) -> str:
    c = c or cfg()
    if p_shortfall is None:
        return 'Insufficient data - suggest review'
    if p_shortfall < c['bands']['resilient_below']:
        return 'Resilient'
    if p_shortfall < c['bands']['vulnerable_below']:
        return 'Vulnerable - consider alternative terms'
    return 'High stress - suggest review'


# --------------------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------------------
def _paths(inp: StressInputs, scenario: str, rng: np.random.Generator, c: dict):
    n, H, D = c['n_paths'], c['horizon_months'], c['days_in_month']
    s = c['shocks']
    income = inp.income_mean * np.clip(1 + inp.income_cv * rng.standard_normal((n, H)), 0, None)
    extra_out = np.zeros((n, H))
    arrival = np.full((n, H), float(inp.income_day))
    if scenario in ('income_drop', 'combined'):
        frac = rng.uniform(*s['income_drop']['fraction'], n)
        k = rng.integers(s['income_drop']['months'][0], s['income_drop']['months'][1] + 1, n)
        start = rng.integers(0, H, n)
        for i in range(n):
            income[i, start[i]:start[i] + k[i]] *= 1 - frac[i]
    if scenario in ('expense_spike', 'combined'):
        m = rng.uniform(*s['expense_spike']['multiple_of_essentials'], n)
        month = rng.integers(0, H, n)
        extra_out[np.arange(n), month] = m * inp.essentials
    if scenario in ('payment_delay', 'combined'):
        delay = rng.integers(s['payment_delay']['days'][0], s['payment_delay']['days'][1] + 1, n)
        month = rng.integers(0, H, n)
        arrival[np.arange(n), month] += delay
    total_emi = inp.total_emi()
    bal = np.full(n, float(inp.savings))
    due_pts, end_pts = np.zeros((n, H)), np.zeros((n, H))
    for t in range(H):
        income_by_due = np.where(arrival[:, t] <= inp.emi_due_day, income[:, t], 0.0)
        spent_by_due = inp.essentials * inp.emi_due_day / D
        due_pts[:, t] = bal + income_by_due - spent_by_due - total_emi
        # income delayed beyond month end still arrives this month (simplification: within the 30-day cycle)
        bal = bal + income[:, t] - inp.essentials - extra_out[:, t] - total_emi
        end_pts[:, t] = bal
    return income, np.hstack([due_pts, end_pts]), end_pts


def simulate(inp: StressInputs, scenarios=None, seed: int | None = None) -> dict:
    c = cfg()
    seed = c['seed'] if seed is None else seed
    missing = inp.missing()
    if missing:
        return {'band': band(None, c), 'missing': missing, 'scenarios': {}, 'resilience': None,
                'illustrative': True}
    total_emi = inp.total_emi()
    out = {}
    for j, sc in enumerate(scenarios or c['scenarios']):
        rng = np.random.default_rng(seed + j)
        incomes, checkpoints, month_end = _paths(inp, sc, rng, c)
        mins = min_cash_balance(checkpoints)
        deficit = months_in_deficit(month_end)
        rec = recovery_time(month_end)
        sf = stressed_foir(total_emi, incomes)
        had = deficit > 0
        out[sc] = {'min_cash_balance_p05': float(np.percentile(mins, 5)),
                   'min_cash_balance_median': float(np.median(mins)),
                   'shortfall_probability': shortfall_probability(mins), 'max_shortfall': max_shortfall(mins),
                   'months_in_deficit_mean': float(deficit.mean()),
                   'recovery_time_mean': float(rec[had].mean()) if had.any() else 0.0,
                   'stressed_foir_median': float(np.median(sf[np.isfinite(sf)])) if np.isfinite(sf).any()
                   else float('inf')}
    head = out.get(c['headline_scenario']) or next(iter(out.values()))
    buf = buffer_coverage(inp.savings, inp.essentials, total_emi)
    score = resilience_score(head['shortfall_probability'], buf, head['stressed_foir_median'], c)
    return {'band': band(head['shortfall_probability'], c), 'missing': [], 'scenarios': out,
            'buffer_coverage_months': buf, 'total_emi': total_emi, 'resilience': score,
            'headline': c['headline_scenario'], 'illustrative': True}


def alternatives(inp: StressInputs, seed: int | None = None) -> list[dict]:
    """Headline shortfall probability under alternative terms (needs amount / rate / tenure for the first two)."""
    c = cfg()['alternatives']
    head = cfg()['headline_scenario']
    variants = []
    if None not in (inp.loan_amount, inp.annual_rate, inp.tenure_months):
        variants.append((f'loan amount x {c["lower_amount_factor"]}',
                         replace(inp, loan_amount=inp.loan_amount * c['lower_amount_factor'], proposed_emi=None)))
        variants.append((f'tenure + {c["longer_tenure_extra_months"]} months',
                         replace(inp, tenure_months=inp.tenure_months + c['longer_tenure_extra_months'],
                                 proposed_emi=None)))
    if inp.income_day is not None:
        variants.append((f'EMI due day = income day + {c["due_day_after_income_days"]}',
                         replace(inp, emi_due_day=min(inp.income_day + c['due_day_after_income_days'], 28))))
    rows = []
    for name, v in variants:
        r = simulate(v, scenarios=[head], seed=seed)
        rows.append({'alternative': name, 'total_emi': v.total_emi(),
                     'shortfall_probability': r['scenarios'][head]['shortfall_probability'], 'band': r['band']})
    return rows
