import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import common  # noqa: E402
from cognilend.ml import tree  # noqa: E402
from ui import charts  # noqa: E402
from ui import components as ui  # noqa: E402

common.setup('Model Comparison')
st.markdown('The **decision tree** is the only model that makes CogniLend decisions. Random Forest, XGBoost and '
            'Gradient Boosting are benchmarked on the same split and the same features, and are shown as advisory '
            'comparisons only.')

bench = tree.reports_dir() / 'benchmark.csv'
if st.button('Run comparison' if not bench.exists() else 'Re-run comparison', icon=':material/refresh:'):
    from cognilend.ml import benchmark
    with st.spinner('Tuning and cross-validating four models (a few minutes)...'):
        benchmark.run()
    st.rerun()

if not bench.exists():
    st.info('No benchmark yet. Click "Run comparison", or run `python -m cognilend.ml.benchmark`.')
else:
    t = pd.read_csv(bench)
    names = {'decision_tree': 'Decision Tree', 'random_forest': 'Random Forest', 'xgboost': 'XGBoost',
             'gradient_boosting': 'Gradient Boosting'}
    raw = t.copy()
    t['model'] = t['model'].map(names)
    dt = t[t['model'] == 'Decision Tree'].iloc[0]
    best = t[t['model'] != 'Decision Tree'].sort_values('test_accuracy', ascending=False).iloc[0]
    k1, k2, k3 = st.columns(3)
    with k1:
        ui.metric_tile('Decision Tree test accuracy', f'{dt.test_accuracy:.4f}', 'The model that decides.')
    with k2:
        ui.metric_tile(f'Best ensemble ({best.model})', f'{best.test_accuracy:.4f}', 'Advisory only.')
    with k3:
        st.metric('Accuracy given up for explainability',
                  f'{(best.test_accuracy - dt.test_accuracy) * 100:.1f} points', border=True,
                  help=f'Best ensemble ({best.model}) test accuracy minus decision tree test accuracy.')
    st.subheader('Test-set results (same split, same features)')
    st.plotly_chart(charts.benchmark_bars(raw), width='stretch', config={'displayModeBar': False})
    st.dataframe(t[['model', 'test_accuracy', 'test_f1', 'test_roc_auc', 'cv_accuracy_mean', 'cv_accuracy_std',
                    'complexity', 'explainability']], hide_index=True, width='stretch')

st.subheader('Why the decision tree decides')
st.markdown("""
- **Readable reason for every decision.** A decision is one short path of comparisons on named banking quantities
  (for example CIBIL, FOIR, experience), in original units. Officers can read it and applicants can be told.
- **Auditable.** The exact reason is stored in the hash-chained audit log. Ensembles average hundreds of trees, so
  their explanations are only post-hoc approximations of the computation, not the computation itself.
- **Safe by design.** Policy rules run first, and uncertain leaves are routed to a human instead of being decided
  by an opaque model.
- **The cost is measured, not hidden.** The accuracy gap above is the price paid for full explainability.
""")
common.footer()
