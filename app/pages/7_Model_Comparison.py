import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import common  # noqa: E402
from cognilend.ml import tree  # noqa: E402

common.setup('Model Comparison')
st.markdown('The **decision tree** is the only model that makes CogniLend decisions. Random Forest, XGBoost and '
            'Gradient Boosting are benchmarked on the same split and the same features, and are shown as advisory '
            'comparisons only.')

bench = tree.reports_dir() / 'benchmark.csv'
if st.button('Run comparison' if not bench.exists() else 'Re-run comparison'):
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
    t['model'] = t['model'].map(names)
    st.subheader('Test-set results (same split, same features)')
    st.dataframe(t[['model', 'test_accuracy', 'test_f1', 'test_roc_auc', 'cv_accuracy_mean', 'cv_accuracy_std',
                    'complexity', 'explainability']], hide_index=True, width='stretch')
    st.bar_chart(t.set_index('model')[['test_accuracy', 'test_f1', 'test_roc_auc']])
    dt = t[t['model'] == 'Decision Tree'].iloc[0]
    best = t[t['model'] != 'Decision Tree'].sort_values('test_accuracy', ascending=False).iloc[0]
    st.metric('Accuracy given up for explainability',
              f'{(best.test_accuracy - dt.test_accuracy) * 100:.1f} points',
              help=f'Best ensemble ({best.model}) test accuracy minus decision tree test accuracy.')

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
