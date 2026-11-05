import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import common  # noqa: E402
from cognilend import config  # noqa: E402
from cognilend.rules.rules import load_policy, load_rules  # noqa: E402
from ui import charts  # noqa: E402
from ui import components as ui  # noqa: E402
from ui import format as fmt  # noqa: E402

common.setup('Model & Policy')
reports = config.ROOT / config.load('settings')['paths']['reports']

# ---- metrics ----
st.subheader('Constrained decision tree (dt_v1)')
m_path = reports / 'dt_metrics.json'
if not m_path.exists():
    ui.error_box('dt_metrics.json not found. Train the model first: python -m cognilend.ml.tree', 'Model metrics missing')
else:
    m = json.loads(m_path.read_text())
    cols = st.columns(6)
    for col, (label, value, hlp) in zip(cols, [
            ('Val accuracy', f'{m["val_accuracy"]:.4f}', 'Accuracy on the validation split.'),
            ('Test accuracy', f'{m["test_accuracy"]:.4f}', 'Accuracy on the held-out test split.'),
            ('Gap (train-val)', f'{m["generalization_gap"]:.4f}', 'Train minus validation accuracy (overfitting check).'),
            ('Depth', m['depth'], 'Tree depth (limit 4).'), ('Nodes', m['node_count'], 'Total nodes (limit 15).'),
            ('KPI val >= 0.80', 'met' if m['kpi_met'] else 'NOT met', 'Project KPI: validation accuracy at least 0.80.')]):
        with col:
            ui.metric_tile(label, value, hlp)

# ---- tree with zoom ----
png = common.tree_png((), None, False, (14, 5.5))
zoom = st.select_slider('Zoom', options=[100, 125, 150, 200, 250], value=100, format_func=lambda z: f'{z}%',
                        help='Enlarge the tree; scroll sideways inside the frame.')
st.html(f'<div style="overflow:auto;border:1px solid var(--cl-border);border-radius:var(--cl-radius);'
        f'background:#fcfcfb;max-height:640px"><img alt="Constrained decision tree with thresholds in original units" '
        f'src="data:image/png;base64,{base64.b64encode(png).decode()}" style="width:{zoom}%;max-width:none;'
        f'display:block"></div>')
st.caption('Thresholds in original units; n and P(approve) from real (pre-SMOTE) training counts.')

# ---- benchmark ----
st.subheader('Benchmark (same split and features)')
bench = reports / 'benchmark.csv'
if bench.exists():
    b = pd.read_csv(bench)
    st.plotly_chart(charts.benchmark_bars(b), width='stretch', config={'displayModeBar': False})
    with st.expander('Benchmark table', icon=':material/table:'):
        st.dataframe(b, hide_index=True, width='stretch')
else:
    ui.empty_state('No benchmark yet.', '○', 'Run python -m cognilend.ml.benchmark or use the Model Comparison page.')
routing = reports / 'routing.json'
if routing.exists():
    r = json.loads(routing.read_text())
    st.caption(f'Routing: tau = {r["chosen"]["tau"]:.2f}, n_min = {r["n_min"]}; test auto share '
               f'{r["routing"]["test"]["auto_share"]:.1%} at accuracy {r["routing"]["test"]["auto_accuracy"]:.4f}.')

# ---- policy rules ----
st.subheader('Policy rules (policies_v1)')
rules = load_rules(load_policy('v1'))
st.html('<div class="cl-tile-help" style="margin-bottom:8px">'
        f'{ui.status_badge_html("Rejected", "HARD")} a failed HARD rule rejects the application at once (the model is '
        f'not consulted). {ui.status_badge_html("Human Review", "SOFT")} a fired SOFT rule sends it to Human Review.'
        '</div>')
cards = []
for r in rules:
    badge = ui.status_badge_html('Rejected', 'HARD') if r.type == 'HARD' else ui.status_badge_html('Human Review', 'SOFT')
    cards.append(f'<div class="cl-card" style="padding:12px 14px"><div style="display:flex;gap:8px;align-items:center;'
                 f'flex-wrap:wrap;margin-bottom:6px">{badge}<strong>{ui.esc(r.id)} · {ui.esc(r.name)}</strong></div>'
                 f'<div style="font-family:Consolas,monospace;font-size:.82rem;color:var(--cl-text);margin-bottom:6px">'
                 f'{ui.esc(r.condition)}</div><p style="font-size:.86rem">{ui.esc(r.rationale)}</p>'
                 f'<div class="cl-tile-help" style="margin-top:6px">Source: {ui.esc(r.source)}</div></div>')
st.html(f'<div class="cl-grid-2">{"".join(cards)}</div>')
with st.expander('Rules as a table', icon=':material/table:'):
    st.dataframe(pd.DataFrame([{'id': r.id, 'type': r.type, 'name': r.name, 'condition': r.condition,
                                'rationale': r.rationale, 'source': r.source} for r in rules]),
                 hide_index=True, width='stretch')

# ---- versions ----
st.subheader('Versions in force')
v = common.repo().versions()
c1, c2 = st.columns(2)
c1.markdown('**Policies**')
c1.dataframe(pd.DataFrame(v['policies']), hide_index=True, width='stretch')
c2.markdown('**Models**')
c2.dataframe(pd.DataFrame(v['models']), hide_index=True, width='stretch')
st.caption('Registered at ' + ', '.join(f'{p["version"]} {fmt.datetime_in(p["activated_at"])}' for p in v['policies']))
common.footer()
