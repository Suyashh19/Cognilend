import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import common  # noqa: E402
from cognilend import config  # noqa: E402
from cognilend.ml.tree_plot import draw_tree  # noqa: E402
from cognilend.rules.rules import load_policy, load_rules  # noqa: E402

common.setup('Model & Policy')
reports = config.ROOT / config.load('settings')['paths']['reports']

v = common.repo().versions()
st.subheader('Versions in force')
c1, c2 = st.columns(2)
c1.dataframe(pd.DataFrame(v['policies']), hide_index=True, width='stretch')
c2.dataframe(pd.DataFrame(v['models']), hide_index=True, width='stretch')

st.subheader('Constrained decision tree (dt_v1)')
m = json.loads((reports / 'dt_metrics.json').read_text())
cols = st.columns(6)
for col, (label, value) in zip(cols, [('Val accuracy', f'{m["val_accuracy"]:.4f}'),
                                      ('Test accuracy', f'{m["test_accuracy"]:.4f}'),
                                      ('Gap (train-val)', f'{m["generalization_gap"]:.4f}'),
                                      ('Depth', m['depth']), ('Nodes', m['node_count']),
                                      ('KPI val >= 0.80', 'met' if m['kpi_met'] else 'NOT met')]):
    col.metric(label, value)
st.pyplot(draw_tree(common.pipeline().explainer, figsize=(14, 5.5)))
st.caption('Thresholds in original units; n and P(approve) from real (pre-SMOTE) training counts.')

st.subheader('Benchmark (same split and features)')
bench = reports / 'benchmark.csv'
if bench.exists():
    st.dataframe(pd.read_csv(bench), hide_index=True, width='stretch')
routing = reports / 'routing.json'
if routing.exists():
    r = json.loads(routing.read_text())
    st.caption(f'Routing: tau = {r["chosen"]["tau"]:.2f}, n_min = {r["n_min"]}; test auto share '
               f'{r["routing"]["test"]["auto_share"]:.1%} at accuracy {r["routing"]["test"]["auto_accuracy"]:.4f}.')

st.subheader('Policy rules (policies_v1)')
rules = load_rules(load_policy('v1'))
st.dataframe(pd.DataFrame([{'id': r.id, 'type': r.type, 'name': r.name, 'condition': r.condition,
                            'rationale': r.rationale, 'source': r.source} for r in rules]),
             hide_index=True, width='stretch')
