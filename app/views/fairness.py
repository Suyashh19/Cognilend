import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import common  # noqa: E402
from cognilend import config  # noqa: E402
from cognilend.fairness import disparate_impact  # noqa: E402
from ui import charts  # noqa: E402
from ui import components as ui  # noqa: E402
from ui import format as fmt  # noqa: E402
from ui import theme  # noqa: E402

common.setup('Fairness Dashboard')
fcfg = config.load('fairness')
threshold = fcfg['min_disparate_impact']

top_l, top_r = st.columns([3, 1], vertical_alignment='center')
top_l.html(f'<div class="cl-tile-help">Disparate impact (DI) = a subgroup\'s approval rate ÷ the most-favoured '
           f'subgroup\'s rate. DI below <strong>{threshold:.2f}</strong> (the four-fifths rule) is flagged. Subgroups '
           f'with fewer than {fcfg["min_group_size"]} cases are shown as insufficient data, never hidden.</div>')
with top_r:
    rerun = st.button('Rerun fairness audit', type='primary', icon=':material/refresh:', width='stretch')
if rerun:
    with st.spinner('Auditing the latest test-set decisions...'):
        disparate_impact.run()
    st.success('Fairness audit rerun and stored.')

runs = common.repo().fairness_runs()
if not runs:
    st.warning('No fairness runs stored yet. Click "Rerun fairness audit".')
    ui.empty_state('No fairness audit yet.', '⚖', 'Press "Rerun fairness audit" to audit the test-set decisions.')
    st.stop()
latest = {}
for r in runs:
    latest.setdefault(r['mode'], r)
st.caption('Last run: ' + ', '.join(f'{m} at {r["created_at"]:%Y-%m-%d %H:%M:%S} UTC' for m, r in latest.items()))

rows = pd.concat([pd.DataFrame(common.repo().fairness_rows(latest[m]['run_id']))
                  for m in ('rules_only', 'model_only', 'pipeline') if m in latest], ignore_index=True)
run_key = tuple(sorted((m, r['run_id']) for m, r in latest.items()))


@st.cache_data(show_spinner=False, max_entries=8)
def all_modes_png(key: tuple) -> bytes:
    """The original three-mode DI figure (disparate_impact.figure), drawn once per stored run."""
    import io

    import matplotlib.pyplot as plt
    fig = disparate_impact.figure(rows)
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=110, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


@st.cache_data(show_spinner=False, max_entries=8)
def di_figure(key: tuple, mode: str):
    return charts.di_bars(rows[rows['mode'] == 'pipeline'], threshold, fcfg['min_group_size'])

pipe = rows[rows['mode'] == 'pipeline']
flagged = pipe[pipe['flagged']]

newest = max(r['created_at'] for r in latest.values())
t1, t2, t3, t4 = st.columns(4)
with t1:
    ui.metric_tile('Last run', fmt.date_in(newest), f'Most recent stored audit: {fmt.datetime_in(newest)}.')
with t2:
    ui.metric_tile('Subgroups audited', int(len(pipe)), 'Full-pipeline mode.')
with t3:
    ui.metric_tile('Below 0.80', int(len(flagged)), 'Subgroups with sufficient data whose DI is below the threshold.')
with t4:
    enough = pipe[~pipe['insufficient'].astype(bool)]
    ui.metric_tile('Lowest DI', f'{enough["di"].min():.2f}' if len(enough) else '—',
                   'Smallest DI among subgroups with sufficient data (full pipeline).')

if flagged.empty:
    st.success(f'DI >= {threshold:.2f} holds for every subgroup with sufficient data (full pipeline).')
else:
    st.error(f'DI >= {threshold:.2f} does NOT hold for: ' + ', '.join(
        f'{r.group} = {r.subgroup} (DI {r.di:.2f}, n = {r.n})' for r in flagged.itertuples()))

st.subheader('Disparate impact by subgroup (full pipeline)')
st.plotly_chart(di_figure(run_key, theme.mode()), width='stretch',
                config={'displayModeBar': False})
st.html('<div class="cl-outcomes" style="margin-top:0">'
        f'{ui.status_badge_html("Approved", f"DI ≥ {threshold:.2f}")}'
        f'{ui.status_badge_html("Rejected", f"DI < {threshold:.2f} (flagged)")}'
        f'<span class="cl-badge neutral"><span class="cl-ico" aria-hidden="true">▨</span>insufficient data</span>'
        '</div>')

with st.expander('All three modes: rules only, model only, full pipeline (with 95% bootstrap CI)',
                 icon=':material/stacked_line_chart:'):
    st.image(all_modes_png(run_key), width='stretch')
st.dataframe(pipe[['group', 'subgroup', 'n', 'approval_rate', 'di', 'ci_low', 'ci_high', 'flagged', 'insufficient']],
             hide_index=True, width='stretch',
             column_config={'approval_rate': st.column_config.NumberColumn('approval_rate', format='percent'),
                            'di': st.column_config.NumberColumn('DI', format='%.3f'),
                            'ci_low': st.column_config.NumberColumn('ci_low', format='%.3f'),
                            'ci_high': st.column_config.NumberColumn('ci_high', format='%.3f')})
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
common.footer()
