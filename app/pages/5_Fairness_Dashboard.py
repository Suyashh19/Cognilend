import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import common  # noqa: E402
from cognilend import config  # noqa: E402
from cognilend.fairness import disparate_impact  # noqa: E402

common.setup('Fairness Dashboard')
threshold = config.load('fairness')['min_disparate_impact']

if st.button('Rerun fairness audit', type='primary'):
    with st.spinner('Auditing the latest test-set decisions...'):
        disparate_impact.run()
    st.success('Fairness audit rerun and stored.')

runs = common.repo().fairness_runs()
if not runs:
    st.warning('No fairness runs stored yet. Click "Rerun fairness audit".')
    st.stop()
latest = {}
for r in runs:
    latest.setdefault(r['mode'], r)
st.caption('Last run: ' + ', '.join(f'{m} at {r["created_at"]:%Y-%m-%d %H:%M:%S} UTC' for m, r in latest.items()))

rows = pd.concat([pd.DataFrame(common.repo().fairness_rows(latest[m]['run_id']))
                  for m in ('rules_only', 'model_only', 'pipeline') if m in latest], ignore_index=True)
rows = rows.rename(columns={'di': 'di'})
pipe = rows[rows['mode'] == 'pipeline']
flagged = pipe[pipe['flagged']]
if flagged.empty:
    st.success(f'DI >= {threshold:.2f} holds for every subgroup with sufficient data (full pipeline).')
else:
    st.error(f'DI >= {threshold:.2f} does NOT hold for: ' + ', '.join(
        f'{r.group} = {r.subgroup} (DI {r.di:.2f}, n = {r.n})' for r in flagged.itertuples()))
st.pyplot(disparate_impact.figure(rows))
st.dataframe(pipe[['group', 'subgroup', 'n', 'approval_rate', 'di', 'ci_low', 'ci_high', 'flagged', 'insufficient']],
             hide_index=True, width='stretch')
if 'breach_test' in latest:
    b = pd.DataFrame(common.repo().fairness_rows(latest['breach_test']['run_id']))
    b = b[b['subgroup'] == 'SYNTHETIC-BREACH']
    if len(b):
        st.caption(f'Evidence gate: injected SYNTHETIC-BREACH subgroup DI {b["di"].iloc[0]:.3f}, flagged = '
                   f'{bool(b["flagged"].iloc[0])}.')
report = config.ROOT / config.load('settings')['paths']['reports'] / 'fairness.md'
if report.exists():
    with st.expander('Full fairness report (mitigation analysis, contribution shift)'):
        st.markdown(report.read_text(encoding='utf-8'))
