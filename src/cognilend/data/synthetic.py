"""Reproducible synthetic Indian loan-application generator (seed 42).

    python -m cognilend.data.synthetic            -> writes data/synthetic/loans_raw.csv

Three stages, all parameters in config/synthetic.yaml:
  1. simulate_applicants()  clean applicants with realistic dependencies (income by segment/area/experience, ...)
  2. latent_label()         label from a latent repayment-risk score + noise. Policy rules play NO part,
                            so the ML layer cannot just re-learn the rule engine (docs/data_decision.md)
  3. corrupt()              the documented data-quality defects, with exact counts where the spec gives one
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from cognilend import config

COLUMNS = ['Loan_ID', 'Age', 'Gender', 'Marital_Status', 'Dependents', 'Employment_Type', 'Work_Experience',
           'Monthly_Income', 'Coapplicant_Income', 'Existing_EMI', 'CIBIL_Score', 'Loan_Type', 'Loan_Amount',
           'Loan_Tenure', 'Collateral_Value', 'Property_Area', 'Loan_Status']
TEXT_CATEGORICALS = ['Gender', 'Marital_Status', 'Employment_Type', 'Loan_Type', 'Property_Area']


def _choice(rng, probs: dict, n: int) -> np.ndarray:
    return rng.choice(list(probs), size=n, p=list(probs.values()))


def _round(x, step):
    return np.round(np.asarray(x, dtype=float) / step) * step


def _z(x: np.ndarray) -> np.ndarray:
    return (x - x.mean()) / x.std()


# --------------------------------------------------------------------------------------
# 1. Clean applicants (canonical values, no defects)
# --------------------------------------------------------------------------------------
def simulate_applicants(rng: np.random.Generator, n: int, cfg: dict) -> pd.DataFrame:
    a, inc, cr, ln = cfg['applicant'], cfg['income'], cfg['credit'], cfg['loan']
    df = pd.DataFrame(index=range(n))

    df['Gender'] = _choice(rng, a['gender'], n)
    age = rng.normal(a['age']['mean'], a['age']['sd'], n)
    df['Age'] = np.clip(np.round(age), a['age']['min'], a['age']['max'])
    df['Employment_Type'] = _choice(rng, a['employment'], n)
    df['Property_Area'] = _choice(rng, a['area'], n)

    m = a['married_logistic']
    p_married = m['ceiling'] / (1 + np.exp(-(df['Age'] - m['midpoint_age']) / m['scale']))
    married = rng.random(n) < p_married
    ever_split = (~married) & (df['Age'] > 35) & (rng.random(n) < a['divorced_or_widowed_share'] / (1 - p_married))
    df['Marital_Status'] = np.where(married, 'Married',
                                    np.where(ever_split, rng.choice(['Divorced', 'Widowed'], n), 'Single'))
    dep_m = rng.choice(4, n, p=a['dependents_p']['married'])
    dep_o = rng.choice(4, n, p=a['dependents_p']['other'])
    df['Dependents'] = np.where(married, dep_m, dep_o)

    working_years = np.maximum(df['Age'] - a['experience_start_age'], 0)
    df['Work_Experience'] = np.round(working_years * rng.beta(2.0, 1.3, n))

    log_income = (inc['log_base'] + df['Employment_Type'].map(inc['employment_shift'])
                  + df['Property_Area'].map(inc['area_shift'])
                  + inc['per_year_experience'] * np.minimum(df['Work_Experience'], inc['experience_cap'])
                  + df['Gender'].map(inc['gender_gap']) + rng.normal(0, inc['sd'], n))
    df['Monthly_Income'] = _round(np.exp(log_income), inc['round_to'])

    has_coapp = rng.random(n) < np.where(married, inc['coapplicant_p']['married'], inc['coapplicant_p']['other'])
    coapp = df['Monthly_Income'] * rng.uniform(*inc['coapplicant_share'], n)
    df['Coapplicant_Income'] = np.where(has_coapp, _round(coapp, inc['round_to']), np.nan)
    has_loan = rng.random(n) < inc['existing_loan_p']
    emi = df['Monthly_Income'] * rng.uniform(*inc['existing_emi_share'], n)
    df['Existing_EMI'] = np.where(has_loan, _round(emi, inc['round_to']), 0.0)

    # Income stability: latent, not written to the file. Salaried > SEP > SENP, grows with experience.
    st = cfg['latent']['stability']
    df['_stability'] = np.clip(df['Employment_Type'].map(st) + st['per_year_experience'] * df['Work_Experience']
                               + rng.normal(0, st['sd'], n), 0, 1)

    c, ntc = cr['cibil'], cr['ntc_p']
    cibil = rng.normal(c['mean'], c['sd'], n) + cr['stability_link'] * _z(df['_stability'].to_numpy())
    p_ntc = ntc['base'] + ntc['young_extra'] * (df['Age'] < ntc['young_below_age']) \
        + ntc['rural_extra'] * (df['Property_Area'] == 'Rural')
    df['CIBIL_Score'] = np.where(rng.random(n) < p_ntc, -1, np.clip(np.round(cibil), c['min'], c['max']))

    df['Loan_Type'] = _choice(rng, ln['type'], n)
    lo_hi = np.array([ln['amount_income_multiple'][t] for t in df['Loan_Type']])
    df['Loan_Amount'] = np.maximum(_round(df['Monthly_Income'] * rng.uniform(lo_hi[:, 0], lo_hi[:, 1]),
                                          ln['amount_round_to']), ln['amount_round_to'])
    df['Loan_Tenure'] = 0.0
    for t, spec in ln['tenure_months'].items():
        mask = df['Loan_Type'] == t
        df.loc[mask, 'Loan_Tenure'] = rng.choice(spec['values'], mask.sum(), p=spec['p'])
        # applicants who plan the loan to end by plan_to_finish_by_age take the longest option that fits
        months_left = (ln['plan_to_finish_by_age'] - df.loc[mask, 'Age']) * 12
        fitted = [max([v for v in spec['values'] if v <= m], default=min(spec['values'])) for m in months_left]
        plans = rng.random(mask.sum()) < ln['tenure_fits_plan_p']
        df.loc[mask, 'Loan_Tenure'] = np.where(plans, np.minimum(df.loc[mask, 'Loan_Tenure'], fitted),
                                               df.loc[mask, 'Loan_Tenure'])

    home_ltv = rng.beta(*ln['home_ltv_beta'], n)
    veh_ltv = rng.uniform(*ln['vehicle_ltv'], n)
    biz_secured = rng.random(n) < ln['business_secured_p']
    biz_cov = rng.uniform(*ln['business_coverage'], n)
    amt = df['Loan_Amount']
    coll = np.select([df['Loan_Type'] == 'Home', df['Loan_Type'] == 'Vehicle',
                      (df['Loan_Type'] == 'Business') & biz_secured],
                     [amt / home_ltv, amt / veh_ltv, amt * biz_cov], np.nan)
    df['Collateral_Value'] = _round(coll, ln['collateral_round_to'])
    return df


# --------------------------------------------------------------------------------------
# 2. Label from a latent repayment-risk score (rules are not involved)
# --------------------------------------------------------------------------------------
def latent_score(df: pd.DataFrame, cfg: dict, rates: dict) -> np.ndarray:
    """Noise-free creditworthiness (higher = better) from stability, FOIR, CIBIL, experience, coverage."""
    lat = cfg['latent']
    w = lat['weights']
    total_income = df['Monthly_Income'] + df['Coapplicant_Income'].fillna(0)
    r = df['Loan_Type'].map(rates).to_numpy() / 12
    growth = (1 + r) ** df['Loan_Tenure'].to_numpy()
    proposed_emi = df['Loan_Amount'].to_numpy() * r * growth / (growth - 1)
    foir = (df['Existing_EMI'].to_numpy() + proposed_emi) / total_income.to_numpy()
    ntc = (df['CIBIL_Score'] == -1).to_numpy()
    cibil = np.where(ntc, np.median(df.loc[~ntc, 'CIBIL_Score']), df['CIBIL_Score'])
    coverage = np.minimum(df['Collateral_Value'].fillna(0) / df['Loan_Amount'], lat['coverage_cap']).to_numpy()
    return (w['stability'] * _z(df['_stability'].to_numpy()) + w['foir'] * _z(np.log1p(foir))
            + w['cibil'] * _z(cibil) + w['experience'] * _z(np.log1p(df['Work_Experience'].to_numpy()))
            + w['coverage'] * _z(coverage) + w['ntc'] * ntc)


def latent_label(rng: np.random.Generator, df: pd.DataFrame, cfg: dict, rates: dict) -> pd.DataFrame:
    lat = cfg['latent']
    df = df.copy()
    df['_score'] = latent_score(df, cfg, rates) + df['Gender'].map(lat['group_bias']).to_numpy()
    noisy = df['_score'] + rng.logistic(0, lat['noise_scale'], len(df))
    cut = np.quantile(noisy, 1 - cfg['approval_rate'])
    df['Loan_Status'] = np.where(noisy >= cut, 'Approved', 'Rejected')
    return df


# --------------------------------------------------------------------------------------
# 3. Defects
# --------------------------------------------------------------------------------------
def _indian_grouping(x: float) -> str:
    s = str(int(x))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    return ','.join([head] + parts + [tail])


def _pick(rng, candidates: np.ndarray, k: int) -> np.ndarray:
    idx = np.flatnonzero(candidates)
    if k > len(idx):
        raise ValueError(f'need {k} rows for a defect, only {len(idx)} eligible')
    return np.sort(rng.choice(idx, k, replace=False))


def corrupt(rng: np.random.Generator, df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Render canonical values as raw text and inject every documented defect into the unique rows."""
    d, labels = cfg['defects'], cfg['labels']
    out = df[COLUMNS[1:]].copy()
    n = len(out)
    out['Dependents'] = out['Dependents'].astype(int).astype(str).replace('3', '3+').astype(object)
    out['Loan_Amount'] = out['Loan_Amount'].astype(object)
    for c in ['Age', 'Work_Experience', 'CIBIL_Score', 'Loan_Tenure']:
        out[c] = out[c].astype(float)

    for c in TEXT_CATEGORICALS:   # canonical rendering, then spelling variants, then whitespace
        canon = out[c].map(labels[c]['canonical'])
        var_rows = rng.random(n) < d['variant_rate']
        variants = [rng.choice(labels[c]['variants'][v]) for v in out[c]]
        out[c] = np.where(var_rows, variants, canon).astype(object)
        ws = rng.random(n) < d['whitespace_rate']
        pad = rng.choice([' {}', '{} ', ' {} '], n)
        out[c] = [p.format(v) if w else v for v, w, p in zip(out[c], ws, pad)]

    for c, rate in d['missing_rate'].items():     # MCAR first, so value defects land on present cells
        out.loc[rng.random(n) < rate, c] = np.nan

    present = lambda c: out[c].notna().to_numpy()  # noqa: E731
    rows = _pick(rng, present('Age'), d['impossible_age'])
    out.loc[rows, 'Age'] = rng.choice(d['impossible_age_values'], len(rows)).astype(float)
    bad_age = np.zeros(n, bool)
    bad_age[rows] = True

    inc_rows = _pick(rng, present('Monthly_Income'), d['negative_income'] + d['zero_income'])
    rng.shuffle(inc_rows)
    out.loc[inc_rows[:d['negative_income']], 'Monthly_Income'] *= -1
    out.loc[inc_rows[d['negative_income']:], 'Monthly_Income'] = 0.0

    scored = present('CIBIL_Score') & (out['CIBIL_Score'] != -1).to_numpy()
    rows = _pick(rng, scored, d['invalid_cibil'])
    out.loc[rows, 'CIBIL_Score'] = rng.choice(d['invalid_cibil_values'], len(rows)).astype(float)

    rows = _pick(rng, present('Work_Experience') & present('Age') & ~bad_age, d['impossible_experience'])
    half = len(rows) // 2
    out.loc[rows[:half], 'Work_Experience'] = -rng.integers(1, 4, half).astype(float)
    over = out.loc[rows[half:], 'Age'] - 18 + rng.integers(2, 10, len(rows) - half)
    out.loc[rows[half:], 'Work_Experience'] = over.to_numpy(dtype=float)

    home = (df['Loan_Type'] == 'Home').to_numpy() & present('Loan_Tenure')
    rows = _pick(rng, home, d['home_tenure_in_years'])
    out.loc[rows, 'Loan_Tenure'] = out.loc[rows, 'Loan_Tenure'] / 12

    rows = _pick(rng, present('Loan_Amount'), d['amount_as_text'])
    rs = set(rng.choice(rows, d['amount_with_rs_prefix'], replace=False).tolist())
    for i in rows:
        txt = _indian_grouping(out.at[i, 'Loan_Amount'])
        out.at[i, 'Loan_Amount'] = f'Rs. {txt}' if i in rs else txt

    rows = _pick(rng, np.ones(n, bool), cfg['n_unlabelled'])
    out.loc[rows, 'Loan_Status'] = np.nan
    return out


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------
def generate(seed: int | None = None, cfg: dict | None = None, return_clean: bool = False):
    """Return the raw dirty frame (and, if asked, the clean labelled frame with latent columns)."""
    cfg = cfg or config.load('synthetic')
    rates = config.load('policies_v1')['indicative_rates']
    rng = np.random.default_rng(cfg['seed'] if seed is None else seed)
    n_unique = cfg['n_rows'] - cfg['n_duplicates']

    clean = latent_label(rng, simulate_applicants(rng, n_unique, cfg), cfg, rates)
    ids = rng.choice(np.arange(100_000, 1_000_000), n_unique, replace=False)
    clean.insert(0, 'Loan_ID', [f"{cfg['id_prefix']}{i}" for i in ids])

    raw = corrupt(rng, clean, cfg)
    raw.insert(0, 'Loan_ID', clean['Loan_ID'])
    dup_src = _pick(rng, raw['Loan_Status'].notna().to_numpy(), cfg['n_duplicates'])
    raw = pd.concat([raw, raw.iloc[dup_src]], ignore_index=True)
    raw = raw.iloc[rng.permutation(len(raw))].reset_index(drop=True)[COLUMNS]
    return (raw, clean) if return_clean else raw


def write(path: str | Path | None = None, seed: int | None = None) -> Path:
    path = Path(path or config.ROOT / config.load('settings')['paths']['synthetic_raw'])
    path.parent.mkdir(parents=True, exist_ok=True)
    generate(seed).to_csv(path, index=False, lineterminator='\n')
    return path


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__ == '__main__':
    p = write()
    print(f'wrote {p}  sha256={sha256(p)}')
