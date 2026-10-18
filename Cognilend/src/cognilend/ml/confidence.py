"""Bayesian confidence score; low confidence -> human review (FR-5).

    python -m cognilend.ml.confidence
        -> artifacts/models/confidence_v1.joblib, artifacts/reports/{calibration.png, routing.md, routing.json}

For every leaf of the saved tree, class counts are taken from the REAL training rows (before SMOTE). With a
Beta(a, b) prior on the leaf approval rate, the posterior is Beta(a + k, b + n - k):
  P(Approved | leaf)  = (k + a) / (n + a + b)
  confidence          = posterior mean of the class the tree predicts   (Beta(1,1): (k_pred + 1) / (n + 2))
  credible interval   = central interval of the posterior for that class
A case is auto-decided only if confidence >= tau AND leaf support n >= n_min; otherwise human review.
tau is tuned on the validation split (tune_tau) and stored in config/settings.yaml.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import beta

from cognilend import config
from cognilend.ml import tree


def _cfg() -> dict:
    return config.load('settings')['confidence']


def leaf_ids(model, X: pd.DataFrame) -> np.ndarray:
    feats = model.named_steps['select'].columns
    return model.named_steps['clf'].apply(X[list(feats)])


def fit_leaf_table(model, X_train: pd.DataFrame, y_train: pd.Series) -> pd.DataFrame:
    c = _cfg()
    a, b = c['prior']
    clf = model.named_steps['clf']
    leaves = leaf_ids(model, X_train)
    y = np.asarray(y_train)
    all_leaves = np.flatnonzero(clf.tree_.children_left == -1)
    rows = []
    for leaf in all_leaves:
        mask = leaves == leaf
        n, k = int(mask.sum()), int(y[mask].sum())
        pred = int(np.argmax(clf.tree_.value[leaf][0]))          # the tree's own decision at this leaf
        k_pred = k if pred == 1 else n - k
        post = beta(k_pred + a, n - k_pred + b)
        lo, hi = post.interval(c['credible_interval'])
        rows.append({'leaf': int(leaf), 'n': n, 'k_approved': k, 'predicted': pred,
                     'p_approved': (k + a) / (n + a + b), 'confidence': (k_pred + a) / (n + a + b),
                     'ci_low': float(lo), 'ci_high': float(hi)})
    return pd.DataFrame(rows).set_index('leaf')


def node_table(model, X_train: pd.DataFrame, y_train: pd.Series) -> pd.DataFrame:
    """Real (pre-SMOTE) training counts and P(Approved) for EVERY node, used for path contributions."""
    a, b = _cfg()['prior']
    feats = list(model.named_steps['select'].columns)
    ind = model.named_steps['clf'].decision_path(X_train[feats])
    y = np.asarray(y_train)
    n = np.asarray(ind.sum(axis=0)).ravel()
    k = np.asarray(ind.T @ y).ravel()
    return pd.DataFrame({'n': n.astype(int), 'k_approved': k.astype(int), 'p_approved': (k + a) / (n + a + b)})


def score(model, table: pd.DataFrame, X: pd.DataFrame, tau: float | None = None, n_min: int | None = None):
    """Per-row leaf, prediction, confidence, credible interval, support and routing."""
    c = _cfg()
    tau = c['tau'] if tau is None else tau
    n_min = c['n_min'] if n_min is None else n_min
    t = table.loc[leaf_ids(model, X)].reset_index()
    t.index = X.index
    t['route'] = route(t['confidence'], t['n'], tau, n_min)
    return t


def route(confidence, n, tau: float, n_min: int) -> np.ndarray:
    """'auto' only when the leaf is confident enough AND backed by enough real training rows."""
    confidence, n = np.asarray(confidence, dtype=float), np.asarray(n)
    if tau is None:
        raise ValueError('tau is not set; run python -m cognilend.ml.confidence and copy tau into settings.yaml')
    return np.where((confidence >= tau) & (n >= n_min), 'auto', 'review')


def routing_curve(model, table, X, y) -> pd.DataFrame:
    c = _cfg()
    g = c['tau_grid']
    s = score(model, table, X, tau=0.5)
    correct = (s['predicted'].to_numpy() == np.asarray(y))
    rows = []
    for tau in np.round(np.arange(g['start'], g['stop'] + 1e-9, g['step']), 4):
        auto = route(s['confidence'], s['n'], tau, c['n_min']) == 'auto'
        rows.append({'tau': float(tau), 'auto_share': float(auto.mean()), 'review_share': float(1 - auto.mean()),
                     'auto_accuracy': float(correct[auto].mean()) if auto.any() else float('nan'),
                     'review_accuracy': float(correct[~auto].mean()) if (~auto).any() else float('nan')})
    return pd.DataFrame(rows)


def tune_tau(curve: pd.DataFrame) -> dict:
    """Smallest tau whose auto accuracy meets the target while review stays <= max share. If none exists,
    the tau with the best auto accuracy among those keeping review <= max share (target reported as missed)."""
    c = _cfg()
    ok_review = curve[curve['review_share'] <= c['max_review_share']]
    feasible = ok_review[ok_review['auto_accuracy'] >= c['target_auto_accuracy']]
    if len(feasible):
        r = feasible.sort_values('tau').iloc[0]
        target_met = True
    else:
        r = ok_review.sort_values(['auto_accuracy', 'auto_share', 'tau'], ascending=[False, False, True]).iloc[0]
        target_met = False
    return {'tau': float(r['tau']), 'target_met': target_met, **{k: float(r[k]) for k in
            ('auto_share', 'review_share', 'auto_accuracy', 'review_accuracy')}}


def brier(p, y) -> float:
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y)) ** 2))


def calibration(model, table, X, y) -> pd.DataFrame:
    """Per leaf: predicted P(Approved) from real train counts vs observed approval rate on (X, y)."""
    s = score(model, table, X, tau=0.5)
    s['y'] = np.asarray(y)
    g = s.groupby('leaf').agg(n_eval=('y', 'size'), observed=('y', 'mean'))
    return table[['n', 'p_approved']].join(g, how='left')


def plot_calibration(cal: pd.DataFrame, raw: pd.DataFrame, path: Path, briers: dict):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.5, 6))
    ax.plot([0, 1], [0, 1], color='#999999', lw=1, ls='--', label='perfect calibration')
    ax.scatter(raw['p_raw'], raw['observed'], s=raw['n_eval'] / 3, color='#d95f02', alpha=0.6,
               label=f'tree predict_proba (SMOTE scale), Brier {briers["raw"]:.4f}')
    ax.scatter(cal['p_approved'], cal['observed'], s=cal['n_eval'] / 3, color='#1b9e77',
               label=f'Bayesian leaf posterior, Brier {briers["bayes"]:.4f}')
    ax.set_xlabel('predicted P(Approved) for the leaf')
    ax.set_ylabel('observed approval rate on validation')
    ax.set_title('Reliability by leaf (validation); marker area ~ cases')
    ax.set_xlim(0, 1), ax.set_ylim(0, 1)
    ax.legend(loc='upper left', fontsize=8)
    fig.savefig(path, dpi=120, bbox_inches='tight')
    plt.close(fig)


def model_path() -> Path:
    s = config.load('settings')
    return config.ROOT / s['paths']['models'] / f"{s['confidence']['version']}.joblib"


def load(path: str | Path | None = None) -> dict:
    return joblib.load(path or model_path())


def run() -> dict:
    data = tree.load_processed()
    dt = tree.load_model()
    model = dt['model']
    table = fit_leaf_table(model, data['train']['X'], data['train']['y'])

    Xv, yv = data['val']['X'], data['val']['y']
    cal = calibration(model, table, Xv, yv)
    p_bayes = score(model, table, Xv, tau=0.5)['p_approved']
    p_raw = model.predict_proba(Xv)[:, 1]
    briers = {'bayes': brier(p_bayes, yv), 'raw': brier(p_raw, yv)}
    raw_cal = pd.DataFrame({'leaf': leaf_ids(model, Xv), 'p_raw': p_raw, 'y': np.asarray(yv)}).groupby('leaf').agg(
        p_raw=('p_raw', 'first'), observed=('y', 'mean'), n_eval=('y', 'size'))
    out = tree.reports_dir()
    plot_calibration(cal, raw_cal, out / 'calibration.png', briers)

    curve = routing_curve(model, table, Xv, yv)
    chosen = tune_tau(curve)
    cfg = _cfg()
    test = {}
    for name in ('val', 'test'):
        s = score(model, table, data[name]['X'], tau=chosen['tau'])
        correct = s['predicted'].to_numpy() == data[name]['y'].to_numpy()
        auto = s['route'].to_numpy() == 'auto'
        test[name] = {'n': int(len(s)), 'auto': int(auto.sum()), 'review': int((~auto).sum()),
                      'auto_share': float(auto.mean()), 'auto_accuracy': float(correct[auto].mean()),
                      'review_accuracy': float(correct[~auto].mean()) if (~auto).any() else None,
                      'overall_accuracy': float(correct.mean()), 'dropped': int(len(s) - auto.sum() - (~auto).sum())}
    result = {'version': cfg['version'], 'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'tree_version': dt['version'], 'prior': cfg['prior'], 'n_min': cfg['n_min'],
              'target_auto_accuracy': cfg['target_auto_accuracy'], 'max_review_share': cfg['max_review_share'],
              'chosen': chosen, 'brier': briers, 'routing': test}
    nodes = node_table(model, data['train']['X'], data['train']['y'])
    joblib.dump({**result, 'leaf_table': table, 'node_table': nodes}, model_path())
    (out / 'routing.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (out / 'routing.md').write_text(render(result, table, cal, curve), encoding='utf-8')
    return {**result, 'leaf_table': table, 'curve': curve, 'calibration': cal}


def render(r: dict, table: pd.DataFrame, cal: pd.DataFrame, curve: pd.DataFrame) -> str:
    ch = r['chosen']
    lines = ['# Confidence and routing', '',
             'Generated by `python -m cognilend.ml.confidence`. Leaf counts are from the real training rows (before '
             f'SMOTE). Prior Beta{tuple(r["prior"])}; {int(config.load("settings")["confidence"]["credible_interval"] * 100)}% '
             'credible interval on the predicted class.', '',
             '## Leaf table (train counts)', '',
             '| Leaf | n | approved | tree predicts | P(Approved) | confidence | 90% CI | val n | val observed |',
             '|---|---|---|---|---|---|---|---|---|']
    for leaf, t in table.iterrows():
        c = cal.loc[leaf]
        obs = f'{c.observed:.3f}' if pd.notna(c.observed) else '-'
        n_eval = int(c.n_eval) if pd.notna(c.n_eval) else 0
        lines.append(f'| {leaf} | {int(t.n)} | {int(t.k_approved)} | {"Approved" if t.predicted else "Rejected"} | '
                     f'{t.p_approved:.3f} | {t.confidence:.3f} | [{t.ci_low:.3f}, {t.ci_high:.3f}] | '
                     f'{n_eval} | {obs} |')
    lines += ['', '## Calibration (validation)', '',
              f'- Brier score, Bayesian leaf posterior: **{r["brier"]["bayes"]:.4f}**',
              f'- Brier score, raw tree `predict_proba` (SMOTE-balanced scale): {r["brier"]["raw"]:.4f}',
              '- Reliability diagram: `calibration.png`.', '',
              '## Routing threshold', '',
              f'Rule: auto-decide only if confidence ≥ τ and leaf support n ≥ n_min = {r["n_min"]}. '
              f'τ is the smallest value with auto accuracy ≥ {r["target_auto_accuracy"]:.2f} and review share ≤ '
              f'{r["max_review_share"]:.2f} on validation; if no τ meets both, the best auto accuracy within the '
              'review cap is taken and the target is reported as missed.', '',
              f'- Chosen **τ = {ch["tau"]:.2f}**; accuracy target {"met" if ch["target_met"] else "**NOT met**"}.', '',
              '| Split | n | auto | review | auto share | auto accuracy | review accuracy | overall tree accuracy | '
              'dropped |', '|---|---|---|---|---|---|---|---|---|']
    for name, s in r['routing'].items():
        ra = f'{s["review_accuracy"]:.4f}' if s['review_accuracy'] is not None else '-'
        lines.append(f'| {name} | {s["n"]} | {s["auto"]} | {s["review"]} | {s["auto_share"]:.3f} | '
                     f'{s["auto_accuracy"]:.4f} | {ra} | {s["overall_accuracy"]:.4f} | {s["dropped"]} |')
    lines += ['', 'These numbers are for the ML layer alone. In the full pipeline the rule layer runs first and '
              'removes HARD rejections and SOFT reviews before the tree is consulted.', '',
              '## Trade-off curve (validation)', '', '| τ | auto share | auto accuracy | review accuracy |',
              '|---|---|---|---|']
    prev = None
    for _, c in curve.iterrows():
        key = (round(c.auto_share, 4))
        if key != prev:
            ra = f'{c.review_accuracy:.4f}' if pd.notna(c.review_accuracy) else '-'
            aa = f'{c.auto_accuracy:.4f}' if pd.notna(c.auto_accuracy) else '-'
            lines.append(f'| {c.tau:.2f} | {c.auto_share:.3f} | {aa} | {ra} |')
            prev = key
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    from cognilend.ml import confidence as _self
    res = _self.run()
    print(res['leaf_table'].round(4).to_string())
    print(json.dumps({k: res[k] for k in ('chosen', 'brier', 'routing')}, indent=2))
