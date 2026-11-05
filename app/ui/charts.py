"""Plotly figures built from data the pages already load (benchmark.csv, fairness_rows). Display only."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ui import theme

MODEL_NAMES = {'decision_tree': 'Decision Tree', 'random_forest': 'Random Forest', 'xgboost': 'XGBoost',
               'gradient_boosting': 'Gradient Boosting'}


def _layout(fig: go.Figure, height: int) -> go.Figure:
    t = theme.TOKENS[theme.mode()]
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=36, b=8), paper_bgcolor='rgba(0,0,0,0)',
                      plot_bgcolor='rgba(0,0,0,0)', font=dict(color=t['text'], size=13),
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, x=0))
    fig.update_xaxes(gridcolor=t['border'], zerolinecolor=t['border'])
    fig.update_yaxes(gridcolor=t['border'], zerolinecolor=t['border'])
    return fig


def benchmark_bars(df: pd.DataFrame) -> go.Figure:
    """Grouped bars: test accuracy / F1 / ROC AUC per model; the decision tree (the deciding model) highlighted."""
    t = theme.TOKENS[theme.mode()]
    d = df.copy()
    d['name'] = d['model'].map(MODEL_NAMES).fillna(d['model'])
    metrics = [(c, lbl) for c, lbl in (('test_accuracy', 'Accuracy'), ('test_f1', 'F1'), ('test_roc_auc', 'ROC AUC'))
               if c in d.columns]
    shades = [t['primary'], t['approve'], t['review']]
    fig = go.Figure()
    for (col, lbl), colour in zip(metrics, shades):
        fig.add_bar(name=lbl, x=d['name'], y=d[col], marker_color=colour, text=d[col].map(lambda v: f'{v:.3f}'),
                    textposition='outside', hovertemplate='%{x}<br>' + lbl + ' %{y:.4f}<extra></extra>')
    lo = min(float(d[c].min()) for c, _ in metrics) if metrics else 0
    fig.update_yaxes(range=[max(0, lo - 0.08), 1.0], title='test-set score')
    fig.update_layout(barmode='group')
    return _layout(fig, 360)


def di_bars(rows: pd.DataFrame, threshold: float, min_n: int) -> go.Figure:
    """Horizontal DI bars per subgroup (pipeline mode), one panel per group, 0.80 line, below-threshold in red."""
    from plotly.subplots import make_subplots
    t = theme.TOKENS[theme.mode()]
    groups = list(dict.fromkeys(rows['group']))
    fig = make_subplots(rows=1, cols=max(len(groups), 1), shared_xaxes=False,
                        subplot_titles=[g.replace('_', ' ').title() for g in groups], horizontal_spacing=0.12)
    for i, g in enumerate(groups, 1):
        sub = rows[rows['group'] == g]
        labels = [f'{s} (n={int(n)})' for s, n in zip(sub['subgroup'], sub['n'])]
        colours, patterns = [], []
        for r in sub.itertuples():
            if bool(r.insufficient):
                colours.append(t['border-strong'])
                patterns.append('/')
            elif bool(r.flagged) or (pd.notna(r.di) and r.di < threshold):
                colours.append(t['reject'])
                patterns.append('')
            else:
                colours.append(t['approve'])
                patterns.append('')
        status = ['insufficient data (n < %d)' % min_n if bool(r.insufficient) else
                  ('below threshold' if (bool(r.flagged) or (pd.notna(r.di) and r.di < threshold)) else 'ok')
                  for r in sub.itertuples()]
        err_hi = (sub['ci_high'] - sub['di']).clip(lower=0)
        err_lo = (sub['di'] - sub['ci_low']).clip(lower=0)
        fig.add_bar(x=sub['di'], y=labels, orientation='h', marker=dict(color=colours, pattern_shape=patterns),
                    error_x=dict(type='data', symmetric=False, array=err_hi, arrayminus=err_lo, color=t['muted'],
                                 thickness=1.2),
                    text=[f'{v:.2f}' if pd.notna(v) else '—' for v in sub['di']], textposition='inside',
                    customdata=list(zip(sub['approval_rate'], status)), showlegend=False,
                    hovertemplate='%{y}<br>DI %{x:.3f}<br>approval rate %{customdata[0]:.1%}<br>%{customdata[1]}'
                                  '<extra></extra>', row=1, col=i)
        fig.add_vline(x=threshold, line=dict(color=t['text'], dash='dash', width=1.5), row=1, col=i)
        fig.update_yaxes(autorange='reversed', row=1, col=i)
        fig.update_xaxes(range=[0, max(1.25, float(sub['ci_high'].max() or 1) + 0.05)], title='DI', row=1, col=i)
    fig.add_annotation(text=f'dashed line = {threshold:.2f} threshold', xref='paper', yref='paper', x=1, y=-0.18,
                       showarrow=False, font=dict(size=11, color=t['muted']), xanchor='right')
    return _layout(fig, 340)
