"""Disparate-impact ratio by gender, age band, dependents (target >= 0.80) on ACTUAL decisions.

    python -m cognilend.fairness.disparate_impact
        -> artifacts/reports/fairness.md, fairness_di.png, fairness_di.csv, fairness_contrib_shift.csv
        -> rows in the fairness_reports table (one run_id per mode)

DI(subgroup) = approval rate(subgroup) / approval rate(reference subgroup); the reference is the most-favoured
subgroup with enough data (configurable in config/fairness.yaml). "Approval" = final decision Approved;
Human Review and Rejected both count as not approved. Subgroups with fewer than min_group_size cases are
reported as "insufficient data": shown, never flagged, never hidden. 95% CI by bootstrap (resampling each
subgroup and the reference independently).

Three modes on the same test applications:
  rules_only  approved = rule layer outcome PASS
  model_only  approved = tree predicts Approved (no rules, no routing)
  pipeline    approved = final decision stored in the decisions table (joined to applicants)
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from cognilend import config
from cognilend.data import preprocess

GROUPS = ('gender', 'age_band', 'dependents')


def _cfg() -> dict:
    return config.load('fairness')


def subgroup_labels(frame: pd.DataFrame) -> pd.DataFrame:
    """gender / age_band / dependents labels from raw protected columns (Gender, Age, Dependents)."""
    g = _cfg()['groups']
    out = pd.DataFrame(index=frame.index)
    out['gender'] = frame['Gender'].fillna(g['gender']['missing_label']).astype(str)
    for name in ('age_band', 'dependents'):
        spec = g[name]
        out[name] = pd.cut(pd.to_numeric(frame[spec['column']], errors='coerce'), bins=spec['bins'],
                           labels=spec['labels']).astype(object).fillna('Unknown').astype(str)
    return out


def di_table(labels: pd.Series, approved: pd.Series, group: str, seed: int | None = None) -> pd.DataFrame:
    cfg = _cfg()
    seed = config.load('settings')['seed'] if seed is None else seed
    rng = np.random.default_rng(seed)
    y = pd.Series(np.asarray(approved, dtype=int), index=labels.index)
    stats = y.groupby(labels).agg(['size', 'sum']).rename(columns={'size': 'n', 'sum': 'approvals'})
    stats['approval_rate'] = stats['approvals'] / stats['n']
    stats['insufficient'] = stats['n'] < cfg['min_group_size']
    ref_cfg = cfg['groups'][group].get('reference', cfg['reference'])
    eligible = stats[~stats['insufficient'] & (stats.index != 'Unknown')]
    if ref_cfg != 'most_favoured' and ref_cfg in stats.index:
        ref = ref_cfg
    else:
        ref = (eligible if len(eligible) else stats)['approval_rate'].idxmax()
    n_ref, p_ref = int(stats.loc[ref, 'n']), stats.loc[ref, 'approval_rate']
    B, alpha = cfg['bootstrap']['n'], 1 - cfg['bootstrap']['ci']
    ref_draws = rng.binomial(n_ref, p_ref, B) / n_ref
    rows = []
    for sub, r in stats.iterrows():
        di = r['approval_rate'] / p_ref if p_ref > 0 else np.nan
        if sub == ref:
            lo = hi = 1.0
        else:
            draws = rng.binomial(int(r['n']), r['approval_rate'], B) / r['n']
            with np.errstate(divide='ignore', invalid='ignore'):
                ratio = np.where(ref_draws > 0, draws / ref_draws, np.nan)
            lo, hi = np.nanquantile(ratio, [alpha / 2, 1 - alpha / 2])
        flagged = bool(not r['insufficient'] and np.isfinite(di) and di < cfg['min_disparate_impact'])
        rows.append({'group': group, 'subgroup': str(sub), 'n': int(r['n']), 'approvals': int(r['approvals']),
                     'approval_rate': float(r['approval_rate']), 'reference': str(ref), 'di': float(di),
                     'ci_low': float(lo), 'ci_high': float(hi), 'insufficient': bool(r['insufficient']),
                     'flagged': flagged,
                     'status': 'insufficient data' if r['insufficient'] else ('BELOW 0.80' if flagged else 'ok')})
    return pd.DataFrame(rows)


def audit(frame: pd.DataFrame, approved_col: str, mode: str) -> pd.DataFrame:
    labels = subgroup_labels(frame)
    out = pd.concat([di_table(labels[g], frame[approved_col], g) for g in GROUPS], ignore_index=True)
    out.insert(0, 'mode', mode)
    return out


def inject_breach(frame: pd.DataFrame, approved_col: str, n: int = 200, rate_factor: float = 0.5,
                  name: str = 'SYNTHETIC-BREACH', seed: int = 42) -> pd.DataFrame:
    """Append n synthetic applicants of a new gender subgroup whose approval rate is rate_factor x the overall
    rate. Used to prove a breach is flagged and surfaced (evidence gate)."""
    rng = np.random.default_rng(seed)
    p = frame[approved_col].mean() * rate_factor
    fake = pd.DataFrame({'Gender': name, 'Age': rng.integers(26, 55, n), 'Dependents': rng.integers(0, 3, n),
                         approved_col: (rng.random(n) < p).astype(int), 'Loan_ID': [f'SYN{i:04d}' for i in range(n)]})
    return pd.concat([frame, fake], ignore_index=True)


# --------------------------------------------------------------------------------------
# Data for the three modes
# --------------------------------------------------------------------------------------
def build_frame(batch_id: str = 'test-eval') -> pd.DataFrame:
    """One row per test application: protected attributes and approved flags for every mode, plus what the
    counterfactual (rule-ablation / threshold) analysis needs."""
    from sqlalchemy import text

    from cognilend.db.repository import Repository
    from cognilend.ml import tree
    from cognilend.ml.explain import Explainer
    from cognilend.rules import engine

    apps = pd.read_csv(preprocess.processed_dir() / 'test_applications.csv', dtype=str)
    side = pd.read_parquet(preprocess.processed_dir() / 'protected.parquet').set_index('Loan_ID')
    frame = side.loc[apps['Loan_ID'], ['Gender', 'Marital_Status', 'Age', 'Dependents']].reset_index()

    records = [{k: v for k, v in r.items() if isinstance(v, str)} for r in apps.to_dict('records')]
    rules = engine.evaluate_many(records)
    frame['rule_outcome'] = [r['outcome'] for r in rules]
    frame['fired'] = [r['fired_rules'] for r in rules]
    frame['rules_only'] = (frame['rule_outcome'] == 'PASS').astype(int)

    data = tree.load_processed()
    X = data['test']['X'].set_axis(data['test']['ids'].to_numpy()).loc[frame['Loan_ID']]
    frame['model_only'] = tree.load_model()['model'].predict(X)

    clean = pd.read_parquet(preprocess.processed_dir() / 'clean.parquet').set_index('Loan_ID')
    ex = Explainer().explain(clean.loc[frame['Loan_ID']].drop(columns=['split']).reset_index())
    frame['ml_confidence'] = [e['confidence'] for e in ex]
    frame['ml_support'] = [e['support'] for e in ex]
    frame['ml_pred'] = [1 if e['predicted'] == 'Approved' else 0 for e in ex]

    repo = Repository()
    sql = text("""SELECT d.loan_id, d.outcome, a.gender, a.age, a.dependents
                  FROM decisions d JOIN loans l ON l.loan_id = d.loan_id
                  JOIN applicants a ON a.applicant_id = l.applicant_id
                  WHERE d.batch_id = :b""")
    with repo.engine.connect() as c:
        db = pd.read_sql(sql, c, params={'b': batch_id}).set_index('loan_id')
    repo.engine.dispose()
    if len(db) != len(frame):
        raise RuntimeError(f'decisions table has {len(db)} rows for {batch_id}, expected {len(frame)}; '
                           'run scripts/evaluate_pipeline.py first')
    db = db.loc[frame['Loan_ID']]
    frame['pipeline'] = (db['outcome'].to_numpy() == 'Approved').astype(int)
    frame['pipeline_not_rejected'] = (db['outcome'].to_numpy() != 'Rejected').astype(int)
    frame['label'] = clean.loc[frame['Loan_ID'], 'target'].to_numpy()
    frame['db_gender'] = db['gender'].to_numpy()
    return frame


def counterfactual_pipeline(frame: pd.DataFrame, drop_rule=None, tau: float | None = None) -> np.ndarray:
    """Pipeline approval recomputed from stored rule results and tree outputs, optionally without one rule or with
    a different global tau. Uses no protected attribute."""
    c = config.load('settings')['confidence']
    tau = c['tau'] if tau is None else tau

    dropped = set() if drop_rule is None else ({drop_rule} if isinstance(drop_rule, str) else set(drop_rule))

    def ok(fired):
        return not [r for r in fired if r not in dropped]
    rules_pass = frame['fired'].map(ok).to_numpy()
    auto = (frame['ml_confidence'].to_numpy() >= tau) & (frame['ml_support'].to_numpy() >= c['n_min'])
    return (rules_pass & auto & (frame['ml_pred'].to_numpy() == 1)).astype(int)


def proxy_removal(frame: pd.DataFrame, drop: str = 'work_experience') -> dict:
    """Retrain the constrained tree WITHOUT one feature that proxies a protected attribute (same params, same
    caps) and measure model-only accuracy and DI. No protected attribute is used."""
    from sklearn.metrics import accuracy_score

    from cognilend.ml import tree
    dt = tree.load_model()
    data = tree.load_processed()
    feats = [f for f in dt['features'] if f != drop]
    p = dt['params']
    m = tree.make_model(feats, p['min_samples_leaf'], p['class_weight'], p['smote'])
    m.fit(data['train']['X'], data['train']['y'])
    X = data['test']['X'].set_axis(data['test']['ids'].to_numpy()).loc[frame['Loan_ID']]
    pred = m.predict(X)
    t = audit(frame.assign(alt=pred), 'alt', 'alt')
    out = {'dropped': drop, 'test_accuracy': float(accuracy_score(frame['label'], pred)),
           'baseline_accuracy': float(accuracy_score(frame['label'], frame['model_only'])),
           'used_features': sorted({f for f, n in zip(feats, m.named_steps['clf'].feature_importances_) if n > 0})}
    for g in GROUPS:
        out[f'min_di_{g}'], out[f'worst_{g}'] = min_di(t, g)
    return out


def min_di(table: pd.DataFrame, group: str) -> tuple[float, str]:
    t = table[(table['group'] == group) & ~table['insufficient']]
    r = t.loc[t['di'].idxmin()]
    return float(r['di']), r['subgroup']


# --------------------------------------------------------------------------------------
# Contribution shift by subgroup (train vs test)
# --------------------------------------------------------------------------------------
def contribution_shift() -> pd.DataFrame:
    from cognilend.ml.explain import Explainer, contribution_frame
    ex = Explainer()
    clean = pd.read_parquet(preprocess.processed_dir() / 'clean.parquet')
    rows = []
    parts = {}
    for split in ('train', 'test'):
        c = clean[clean['split'] == split].reset_index(drop=True)
        e = ex.explain(c.drop(columns=['split']))
        cf = contribution_frame(e, ex.features)
        used = [f for f in ex.features if cf[f].abs().sum() > 0]
        parts[split] = (subgroup_labels(c), cf[used])
    used = parts['train'][1].columns
    for g in GROUPS:
        for sub in sorted(set(parts['train'][0][g]) | set(parts['test'][0][g])):
            mt = parts['train'][0][g] == sub
            ms = parts['test'][0][g] == sub
            for f in used:
                tr = parts['train'][1].loc[mt, f]
                te = parts['test'][1].loc[ms, f]
                rows.append({'group': g, 'subgroup': sub, 'feature': f, 'n_train': int(mt.sum()),
                             'n_test': int(ms.sum()), 'mean_contrib_train': tr.mean() if len(tr) else np.nan,
                             'mean_contrib_test': te.mean() if len(te) else np.nan})
    out = pd.DataFrame(rows)
    out['shift'] = out['mean_contrib_test'] - out['mean_contrib_train']
    return out


# --------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------
COLORS = {'rules_only': '#2a78d6', 'model_only': '#eb6834', 'pipeline': '#1baf7a'}   # validated categorical slots
MARKERS = {'rules_only': 'o', 'model_only': 's', 'pipeline': '^'}


def plot(results: pd.DataFrame, path):
    import matplotlib.pyplot as plt
    fig = figure(results)
    fig.savefig(path, dpi=120, facecolor=fig.get_facecolor())
    plt.close(fig)


def figure(results: pd.DataFrame):
    """DI dot plot (one panel per group) with the 0.80 line; results needs mode/group/subgroup/n/di/ci/insufficient."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    modes = [m for m in ['rules_only', 'model_only', 'pipeline'] if m in set(results['mode'])]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), sharex=True)
    fig.patch.set_facecolor('#fcfcfb')
    for ax, g in zip(axes, GROUPS):
        sub = results[results['group'] == g]
        present = list(dict.fromkeys(sub['subgroup']))
        spec = _cfg()['groups'][g]
        order = list(spec.get('labels', [])) or sorted(x for x in present if x != 'Unknown')
        cats = [c for c in order if c in present] + [c for c in present if c not in order and c != 'Unknown']             + (['Unknown'] if 'Unknown' in present else [])
        for j, m in enumerate(modes):
            t = sub[sub['mode'] == m].set_index('subgroup').reindex(cats)
            y = np.arange(len(cats)) + (j - 1) * 0.22
            ins = t['insufficient'].fillna(True).to_numpy(dtype=bool)
            err = np.vstack([(t['di'] - t['ci_low']).clip(lower=0), (t['ci_high'] - t['di']).clip(lower=0)])
            ax.errorbar(t['di'], y, xerr=err, fmt='none', ecolor=COLORS[m], elinewidth=1, alpha=0.6)
            ax.scatter(t['di'][~ins], y[~ins], marker=MARKERS[m], s=46, color=COLORS[m], zorder=3,
                       edgecolor='#fcfcfb', linewidth=1.5, label=m.replace('_', ' '))
            ax.scatter(t['di'][ins], y[ins], marker=MARKERS[m], s=46, facecolor='none', edgecolor=COLORS[m],
                       zorder=3)
        ax.axvline(0.8, color='#6b6a64', lw=1, ls='--')
        ax.text(0.8, -0.75, ' 0.80', color='#6b6a64', fontsize=8, va='bottom')
        ax.set_ylim(len(cats) - 0.5, -0.9)             # first category on top
        labels = [f'{c} (n={int(sub[(sub["mode"] == "pipeline") & (sub["subgroup"] == c)]["n"].iloc[0])})'
                  for c in cats]
        ax.set_yticks(range(len(cats)), labels, fontsize=9, color='#3d3c37')
        ax.set_title(g.replace('_', ' '), fontsize=11, color='#1f1e1b', loc='left')
        ax.grid(axis='x', color='#e6e5e0', lw=0.8)
        ax.set_axisbelow(True)
        for s in ('top', 'right'):
            ax.spines[s].set_visible(False)
        ax.set_facecolor('#fcfcfb')
    axes[0].set_xlabel('disparate impact (approval rate / reference)', fontsize=9, color='#3d3c37')
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper right', ncol=3, fontsize=9, frameon=False)
    fig.suptitle('Disparate impact on the test split - hollow markers: fewer than '
                 f'{_cfg()["min_group_size"]} cases (insufficient data); bars: 95% bootstrap CI',
                 fontsize=10, color='#3d3c37', x=0.01, ha='left')
    fig.tight_layout()
    return fig


def save_runs(results: pd.DataFrame, versions: dict) -> dict:
    from cognilend.db.models import FairnessReport
    from cognilend.db.repository import Repository
    repo = Repository()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    run_ids = {}
    with repo.Session.begin() as s:
        for mode, t in results.groupby('mode'):
            rid = f'{mode}-{stamp}-{uuid.uuid4().hex[:6]}'
            run_ids[mode] = rid
            for r in t.itertuples():
                s.add(FairnessReport(run_id=rid, mode=mode, group_name=r.group, subgroup=r.subgroup, n=r.n,
                                     approval_rate=r.approval_rate, di_ratio=r.di, ci_low=r.ci_low, ci_high=r.ci_high,
                                     flagged=r.flagged, insufficient=r.insufficient,
                                     versions_json=json.dumps(versions)))
    repo.engine.dispose()
    return run_ids


def run() -> dict:
    s = config.load('settings')
    frame = build_frame()
    consistency = int((counterfactual_pipeline(frame) != frame['pipeline']).sum())
    gender_mismatch = int((frame['Gender'].fillna('') != frame['db_gender'].fillna('')).sum())
    modes = ('label', 'rules_only', 'model_only', 'pipeline', 'pipeline_not_rejected')
    results = pd.concat([audit(frame, m, m) for m in modes], ignore_index=True)
    proxy = proxy_removal(frame)

    breach_frame = inject_breach(frame, 'pipeline')
    breach = audit(breach_frame, 'pipeline', 'breach_test')
    breach_row = breach[(breach['group'] == 'gender') & (breach['subgroup'] == 'SYNTHETIC-BREACH')].iloc[0]

    # mitigation analysis (no protected attribute at decision time)
    ablation = []
    changes = [None, 'R01', 'R03', 'R04', 'R05', 'R07', 'S01', 'S02', 'S03', 'S04', 'INPUT',
               ('R01', 'R03'), ('S01', 'S02'), ('R01', 'R03', 'S02'), ('R01', 'R03', 'S01', 'S02')]
    for rule in changes:
        fr = frame.assign(cf=counterfactual_pipeline(frame, drop_rule=rule))
        t = audit(fr, 'cf', 'cf')
        label = 'as deployed' if rule is None else 'without ' + (rule if isinstance(rule, str) else ' + '.join(rule))
        row = {'change': label, 'approval_rate': fr['cf'].mean()}
        for g in GROUPS:
            row[f'min_di_{g}'], row[f'worst_{g}'] = min_di(t, g)
        ablation.append(row)
    taus = []
    for tau in (0.60, 0.65, 0.70, 0.75, 0.80, 0.85):
        fr = frame.assign(cf=counterfactual_pipeline(frame, tau=tau))
        t = audit(fr, 'cf', 'cf')
        row = {'tau': tau, 'approval_rate': fr['cf'].mean()}
        for g in GROUPS:
            row[f'min_di_{g}'], row[f'worst_{g}'] = min_di(t, g)
        taus.append(row)
    ablation, taus = pd.DataFrame(ablation), pd.DataFrame(taus)

    shift = contribution_shift()
    versions = {'policy': 'v1', 'model': s['model']['version'], 'preprocessor': s['preprocess']['version'],
                'confidence': s['confidence']['version'], 'tau': s['confidence']['tau']}
    run_ids = save_runs(pd.concat([results, breach], ignore_index=True), versions)

    out = config.ROOT / s['paths']['reports']
    results.to_csv(out / 'fairness_di.csv', index=False, float_format='%.4f')
    shift.to_csv(out / 'fairness_contrib_shift.csv', index=False, float_format='%.5f')
    ablation.to_csv(out / 'fairness_ablation.csv', index=False, float_format='%.4f')
    taus.to_csv(out / 'fairness_tau.csv', index=False, float_format='%.4f')
    (out / 'fairness_proxy.json').write_text(json.dumps(proxy, indent=2), encoding='utf-8')
    plot(results[results['mode'].isin(['rules_only', 'model_only', 'pipeline'])], out / 'fairness_di.png')
    md = render(results, breach_row, ablation, taus, shift, run_ids, versions, consistency, gender_mismatch,
                len(frame), proxy)
    (out / 'fairness.md').write_text(md, encoding='utf-8')
    return {'results': results, 'breach': breach, 'breach_row': breach_row, 'ablation': ablation, 'taus': taus,
            'shift': shift, 'run_ids': run_ids, 'markdown': md, 'consistency_mismatches': consistency,
            'proxy': proxy}


def render(results, breach_row, ablation, taus, shift, run_ids, versions, consistency, gender_mismatch, n,
           proxy) -> str:
    cfg = _cfg()
    pipe = results[results['mode'] == 'pipeline']
    breaches = pipe[pipe['flagged']]
    holds = breaches.empty
    lines = ['# Fairness audit: disparate impact on actual decisions', '',
             f'Generated by `python -m cognilend.fairness.disparate_impact` on the test split (n = {n}). '
             f'Versions: `{json.dumps(versions)}`. Saved to `fairness_reports` as runs: '
             + ', '.join(f'`{v}`' for v in run_ids.values()) + '.', '',
             f'"Approved" = final decision Approved (Human Review and Rejected count as not approved). DI = '
             'approval rate / approval rate of the most-favoured subgroup with enough data. Subgroups with fewer '
             f'than {cfg["min_group_size"]} cases are reported as **insufficient data** (not flagged, not hidden). '
             f'95% CI: bootstrap, {cfg["bootstrap"]["n"]} resamples. Chart: `fairness_di.png`.', '',
             f'Data checks: pipeline approvals recomputed from stored rule results and tree outputs differ from the '
             f'decisions table in **{consistency}** rows; gender in `applicants` differs from the protected side '
             f'table in **{gender_mismatch}** rows.', '',
             '## Verdict', '']
    if holds:
        lines.append(f'**DI >= {cfg["min_disparate_impact"]:.2f} holds for every subgroup with sufficient data** in '
                     'the full pipeline.')
    else:
        lines.append(f'**DI >= {cfg["min_disparate_impact"]:.2f} does NOT hold for every subgroup.** Full-pipeline '
                     'subgroups below the threshold:')
        lines.append('')
        for r in breaches.itertuples():
            lines.append(f'- {r.group} = {r.subgroup}: DI {r.di:.3f} (95% CI {r.ci_low:.3f}-{r.ci_high:.3f}), '
                         f'approval {r.approval_rate:.3f} vs {r.reference} (n = {r.n})')
    ins = pipe[pipe['insufficient']]
    if len(ins):
        lines += ['', 'Insufficient data (reported, not judged): ' + ', '.join(
            f'{r.group} = {r.subgroup} (n = {r.n}, DI {r.di:.2f})' for r in ins.itertuples())]
    lines += ['', '## DI by layer', '',
              'Columns: **historical label** (context: the label itself, not a decision layer), the three '
              'decision layers, and **pipeline not-rejected** (Approved or Human Review; shows whether a gap is '
              'rejection or deferral to review).', '',
              '| Group | Subgroup | n | historical label | rules only | model only | full pipeline | pipeline 95% CI '
              '| pipeline not-rejected | status |',
              '|---|---|---|---|---|---|---|---|---|---|']
    piv = results.pivot_table(index=['group', 'subgroup'], columns='mode', values='di', sort=False)
    for (g, sub), r in piv.iterrows():
        p = pipe[(pipe['group'] == g) & (pipe['subgroup'] == sub)].iloc[0]
        lines.append(f'| {g} | {sub} | {p.n} | {r.label:.3f} | {r.rules_only:.3f} | {r.model_only:.3f} | '
                     f'{r.pipeline:.3f} | {p.ci_low:.3f}-{p.ci_high:.3f} | {r.pipeline_not_rejected:.3f} | '
                     f'{p.status} |')
    lines += ['', 'Approval rates (full pipeline): ' + '; '.join(
        f'{r.subgroup} {r.approval_rate:.3f}' for r in pipe.itertuples()) + '.', '',
              '## Which layer introduces disparity', '']
    for g in GROUPS:
        worst = {m: min_di(results[results['mode'] == m], g) for m in
                 ('label', 'rules_only', 'model_only', 'pipeline', 'pipeline_not_rejected')}
        lines.append(f'- **{g}**: lowest DI - historical label {worst["label"][0]:.3f} ({worst["label"][1]}), '
                     f'rules only {worst["rules_only"][0]:.3f} ({worst["rules_only"][1]}), model only '
                     f'{worst["model_only"][0]:.3f} ({worst["model_only"][1]}), pipeline '
                     f'{worst["pipeline"][0]:.3f} ({worst["pipeline"][1]}), pipeline not-rejected '
                     f'{worst["pipeline_not_rejected"][0]:.3f} ({worst["pipeline_not_rejected"][1]}).')
    lines += ['', '## Mitigation analysis (no protected attribute used at decision time)', '',
              'Per-group thresholds that read the protected attribute are not allowed. Instead, each policy rule was '
              'removed in turn (counterfactual on the stored rule results and tree outputs) to see which rule drives '
              'a disparity, and the global confidence threshold τ was varied. Lowest DI per group:', '',
              '| Change | approval rate | gender | age band | dependents |', '|---|---|---|---|---|']
    for r in ablation.itertuples():
        lines.append(f'| {r.change} | {r.approval_rate:.3f} | {r.min_di_gender:.3f} ({r.worst_gender}) | '
                     f'{r.min_di_age_band:.3f} ({r.worst_age_band}) | {r.min_di_dependents:.3f} '
                     f'({r.worst_dependents}) |')
    lines += ['', '| Global τ | approval rate | gender | age band | dependents |', '|---|---|---|---|---|']
    for r in taus.itertuples():
        lines.append(f'| {r.tau:.2f} | {r.approval_rate:.3f} | {r.min_di_gender:.3f} ({r.worst_gender}) | '
                     f'{r.min_di_age_band:.3f} ({r.worst_age_band}) | {r.min_di_dependents:.3f} '
                     f'({r.worst_dependents}) |')
    lines += ['', f'Proxy removal: the tree retrained without `{proxy["dropped"]}` (same caps and parameters) '
              f'uses {", ".join(proxy["used_features"])}; model-only test accuracy {proxy["test_accuracy"]:.4f} vs '
              f'{proxy["baseline_accuracy"]:.4f}; lowest DI gender {proxy["min_di_gender"]:.3f} '
              f'({proxy["worst_gender"]}), age band {proxy["min_di_age_band"]:.3f} ({proxy["worst_age_band"]}), '
              f'dependents {proxy["min_di_dependents"]:.3f} ({proxy["worst_dependents"]}). Not deployed: '
              'reported for the decision below.']
    base = ablation.iloc[0]
    best = ablation.loc[ablation['min_di_age_band'].idxmax()]
    tau_best = taus.loc[taus['min_di_age_band'].idxmax()]
    lab = {g: min_di(results[results['mode'] == 'label'], g) for g in GROUPS}
    mo = {g: min_di(results[results['mode'] == 'model_only'], g) for g in GROUPS}
    ro = {g: min_di(results[results['mode'] == 'rules_only'], g) for g in GROUPS}
    lines += ['', '### What was tried and what it shows', '',
              f'1. **Where the gap comes from.** The model alone keeps every sufficient subgroup at DI >= '
              f'{min(v[0] for v in mo.values()):.3f}. The age and dependents gaps come from (a) the historical '
              f'label itself (lowest age-band DI {lab["age_band"][0]:.3f} for {lab["age_band"][1]}: younger '
              'applicants have less experience and more thin credit files, which the repayment score penalises) '
              f'and (b) the policy rules (rules-only lowest age-band DI {ro["age_band"][0]:.3f} for '
              f'{ro["age_band"][1]}; dependents {ro["dependents"][0]:.3f} for {ro["dependents"][1]}). R01 and '
              'R03 test age directly; S01 (new to credit) and S02 (experience) correlate with age.',
              f'2. **Rule ablation** (above): the largest age-band improvement is "{best["change"]}" '
              f'(lowest DI {base["min_di_age_band"]:.3f} -> {best["min_di_age_band"]:.3f}, approval rate '
              f'{base["approval_rate"]:.3f} -> {best["approval_rate"]:.3f}). No rule change tried (single or combined, '
              'all protected-blind) brings every age band to 0.80.',
              f'3. **Global τ**: best age-band DI {tau_best["min_di_age_band"]:.3f} at τ = {tau_best["tau"]:.2f} '
              f'(approval rate {tau_best["approval_rate"]:.3f}), at the cost of auto-approving a less certain leaf.',
              f'4. **Proxy removal** (tree without `{proxy["dropped"]}`): model-only age-band DI '
              f'{proxy["min_di_age_band"]:.3f}, accuracy {proxy["test_accuracy"]:.4f} vs {proxy["baseline_accuracy"]:.4f}. '
              'Small effect, because the model is not where the age gap is created.',
              '5. **Not done, by rule:** per-group thresholds or any use of age band / gender at decision time.', '',
              '**Decision needed from the team / guide:** the remaining age gap is produced by explicit policy '
              '(minimum age, age at maturity, experience and credit-history requirements) and by the repayment '
              'signal in the data, not by the model. Options: (a) accept and document these as business-necessity '
              'rules with the DI shown here; (b) convert S02 / R03 to softer forms and re-measure (rows above); '
              '(c) review the human-review outcomes for young applicants, since much of their gap is deferral to '
              'review rather than rejection (see the not-rejected column).']
    big = shift[shift['n_test'] >= cfg['min_group_size']].copy()
    big['abs_shift'] = big['shift'].abs()
    top = big.sort_values('abs_shift', ascending=False).head(8)
    lines += ['', '## Feature-contribution shift by subgroup (train vs test)', '',
              f'Mean path contribution per feature, train vs test, for every subgroup (full table: '
              f'`fairness_contrib_shift.csv`). Largest absolute shift among subgroups with n_test >= '
              f'{cfg["min_group_size"]}: **{top["abs_shift"].max():.4f}**.', '',
              '| Group | Subgroup | Feature | n train | n test | train | test | shift |', '|---|---|---|---|---|---|---|---|']
    for r in top.itertuples():
        lines.append(f'| {r.group} | {r.subgroup} | {r.feature} | {r.n_train} | {r.n_test} | '
                     f'{r.mean_contrib_train:+.4f} | {r.mean_contrib_test:+.4f} | {r.shift:+.4f} |')
    lines += ['', '## Synthetic breach test (evidence gate)', '',
              f'200 synthetic applicants were added as gender subgroup `SYNTHETIC-BREACH` with half the overall '
              f'approval rate. Result: DI **{breach_row.di:.3f}** (95% CI {breach_row.ci_low:.3f}-'
              f'{breach_row.ci_high:.3f}), status **{breach_row.status}**, flagged = **{breach_row.flagged}**. It is '
              f'stored in `fairness_reports` under run `{run_ids.get("breach_test")}` and listed here, so a breach '
              'is surfaced, not hidden.', '']
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    from cognilend.fairness import disparate_impact as _self
    r = _self.run()
    print(r['markdown'])
