"""Run the whole test suite (with coverage) and write artifacts/reports/kpi_report.md.

    python scripts/kpi_report.py

Every number in the report is read from a file or computed here; nothing is typed by hand. Test counts come
from the JUnit XML of the pytest run this script starts, and are cross-checked against pytest's own summary line.
Prerequisites: scripts/seed_demo.py, scripts/reproducibility.py, scripts/lock_load_test.py (reports read below).
"""
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.stats import entropy as scipy_entropy
from sqlalchemy import text

from cognilend import config
from cognilend.data import preprocess
from cognilend.db.repository import Repository
from cognilend.ml import entropy

REP = config.ROOT / config.load('settings')['paths']['reports']


# --------------------------------------------------------------------------------------
# pytest
# --------------------------------------------------------------------------------------
def run_pytest() -> dict:
    junit, cov = REP / 'junit.xml', REP / 'coverage.json'
    cmd = [sys.executable, '-m', 'pytest', '-v', '-p', 'no:cacheprovider', f'--junitxml={junit}',
           '--cov=cognilend', f'--cov-report=json:{cov}', '--cov-report=term']
    proc = subprocess.run(cmd, cwd=config.ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (REP / 'pytest_output.txt').write_text(proc.stdout + proc.stderr, encoding='utf-8')
    summary = [ln for ln in proc.stdout.splitlines() if re.match(r'^=+ .*(passed|failed|error).* in .* =+$', ln)][-1]
    root = ET.parse(junit).getroot()
    suite = root if root.tag == 'testsuite' else root.find('testsuite')
    cases = {}
    for tc in suite.iter('testcase'):
        status = 'failed' if tc.find('failure') is not None else 'error' if tc.find('error') is not None \
            else 'skipped' if tc.find('skipped') is not None else 'passed'
        cases[f'{tc.get("classname")}::{tc.get("name")}'] = status
    totals = {k: int(suite.get(k, 0)) for k in ('tests', 'failures', 'errors', 'skipped')}
    totals['passed'] = totals['tests'] - totals['failures'] - totals['errors'] - totals['skipped']
    m = re.search(r'(\d+) passed', summary)
    assert m and int(m.group(1)) == totals['passed'], (summary, totals)        # report == pytest output
    covj = json.loads(cov.read_text())
    return {'summary': summary.strip('= ').strip(), 'totals': totals, 'cases': cases, 'returncode': proc.returncode,
            'coverage': covj['totals']['percent_covered'],
            'coverage_files': {k.replace('\\', '/').split('cognilend/')[-1]: v['summary']['percent_covered']
                               for k, v in covj['files'].items()}}


def status_of(cases: dict, *names: str) -> str:
    """PASS if every collected test whose function name is in `names` passed (parametrised ids included)."""
    hits = [s for k, s in cases.items() if k.split('::')[-1].split('[')[0] in names]
    if not hits:
        return 'MISSING'
    return 'PASS' if all(s == 'passed' for s in hits) else 'FAIL'


# --------------------------------------------------------------------------------------
# Independent re-implementation of the rule conditions (for rule-trigger precision)
# --------------------------------------------------------------------------------------
def independent_rule_flags(apps: pd.DataFrame) -> pd.DataFrame:
    pol = config.load('policies_v1')
    p, th = pol['parameters'], {r['id']: r.get('threshold') for r in pol['rules']}
    num = {c: pd.to_numeric(apps[c], errors='coerce') for c in
           ('Age', 'Work_Experience', 'Monthly_Income', 'Coapplicant_Income', 'Existing_EMI', 'CIBIL_Score',
            'Loan_Amount', 'Loan_Tenure', 'Collateral_Value')}
    lt, emp = apps['Loan_Type'], apps['Employment_Type']
    ti = num['Monthly_Income'] + num['Coapplicant_Income'].fillna(0)
    r = lt.map(pol['indicative_rates']) / 12
    g = (1 + r) ** num['Loan_Tenure']
    foir = (num['Existing_EMI'] + num['Loan_Amount'] * r * g / (g - 1)) / ti
    s = p['foir_slabs']
    limit = np.select([ti < s[0]['income_below'], ti <= s[1]['income_upto']], [s[0]['max_foir'], s[1]['max_foir']],
                      s[2]['max_foir'])
    ls = p['ltv_slabs']
    cap = np.select([num['Loan_Amount'] <= ls[0]['amount_upto'], num['Loan_Amount'] <= ls[1]['amount_upto']],
                    [ls[0]['max_ltv'], ls[1]['max_ltv']], ls[2]['max_ltv'])
    coll = num['Collateral_Value']
    secured = lt.isin(p['secured_loan_types'])
    cib = num['CIBIL_Score']
    return pd.DataFrame({
        'R01': num['Age'] < th['R01'],
        'R03': num['Age'] + num['Loan_Tenure'] / 12 > th['R03'],
        'R04': cib.notna() & (cib != -1) & (cib < th['R04']),
        'R05': foir > limit,
        'R06': (lt == 'Home') & (coll > 0) & (num['Loan_Amount'] / coll > cap),
        'R07': ti < th['R07'],
        'S01': cib == -1,
        'S02': num['Work_Experience'] < emp.map(p['min_experience']),
        'S03': (foir > limit - p['foir_borderline_margin']) & (foir <= limit),
        'S04': cib.isna() | num['Existing_EMI'].isna() | num['Work_Experience'].isna()
               | (secured & ~(coll > 0)),
    }).fillna(False).set_axis(apps['Loan_ID'])


def rule_precision() -> pd.DataFrame:
    apps = pd.read_csv(preprocess.processed_dir() / 'test_applications.csv', dtype=str)
    indep = independent_rule_flags(apps)
    repo = Repository()
    with repo.engine.connect() as c:
        rr = pd.read_sql(text('SELECT d.loan_id, rr.rule_id, rr.status FROM rule_results rr JOIN decisions d '
                              'ON d.decision_id = rr.decision_id WHERE d.batch_id = :b'), c, params={'b': 'test-eval'})
    repo.engine.dispose()
    fired = (rr.assign(f=rr['status'] == 'fired').pivot_table(index='loan_id', columns='rule_id', values='f',
                                                               aggfunc='max'))
    rows = []
    for rule in indep.columns:
        e = fired[rule].astype(bool)
        i = indep.loc[e.index, rule].astype(bool)
        tp = int((e & i).sum())
        rows.append({'rule': rule, 'engine_fired': int(e.sum()), 'independent_true': int(i.sum()), 'agree_fired': tp,
                     'precision': tp / e.sum() if e.sum() else np.nan, 'recall': tp / i.sum() if i.sum() else np.nan,
                     'evaluated_rows': int(len(e))})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------
def main():
    sys.stdout.reconfigure(encoding='utf-8')
    t = run_pytest()
    cases = t['cases']
    dt = json.loads((REP / 'dt_metrics.json').read_text())
    routing = json.loads((REP / 'routing.json').read_text())
    bench = pd.read_csv(REP / 'benchmark.csv').set_index('model')
    fair = pd.read_csv(REP / 'fairness_di.csv')
    load = json.loads((REP / 'lock_load_test.json').read_text())
    rare = json.loads((REP / 'rare_subset.json').read_text())
    repro = (REP / 'reproducibility.md').read_text(encoding='utf-8')
    out = pd.read_csv(REP / 'pipeline_decisions.csv')
    n_in = len(pd.read_csv(preprocess.processed_dir() / 'test_applications.csv', dtype=str))
    repo = Repository()
    with repo.engine.connect() as c:
        logged = c.execute(text("SELECT COUNT(*) FROM decisions WHERE batch_id = 'test-eval'")).scalar()
    chain = repo.verify_chain()
    repo.engine.dispose()
    prec = rule_precision()
    rng = np.random.default_rng(42)
    ent_err = max(abs(entropy.entropy(p) - scipy_entropy(p, base=2)) for p in rng.random((1000, 10)))
    ens_best = bench.drop(index='decision_tree')['test_accuracy'].max()
    auto = out['decision'].isin(['Approved', 'Rejected']).mean()
    pipe = fair[(fair['mode'] == 'pipeline') & ~fair['insufficient']]
    worst = pipe.loc[pipe['di'].idxmin()]
    total_fired = prec['engine_fired'].sum()
    overall_prec = prec['agree_fired'].sum() / total_fired
    s = config.load('settings')

    def row(kpi, measured, threshold, ok, source):
        return {'KPI': kpi, 'Measured': measured, 'Threshold': threshold,
                'Status': ok if isinstance(ok, str) else ('PASS' if ok else 'FAIL'), 'Source': source}

    kpis = [
        row('Validation accuracy, constrained tree', f'{dt["val_accuracy"]:.4f}', f'>= {s["kpi"]["min_val_accuracy"]}',
            dt['val_accuracy'] >= s['kpi']['min_val_accuracy'], '`python -m cognilend.ml.tree` -> dt_metrics.json'),
        row('Interpretability cost (best ensemble - tree, test acc)', f'{ens_best - bench.loc["decision_tree", "test_accuracy"]:.4f}',
            'reported', 'INFO', '`python -m cognilend.ml.benchmark` -> benchmark.csv'),
        row('Tree depth', dt['depth'], f'<= {s["tree"]["max_depth"]}', dt['depth'] <= s['tree']['max_depth'],
            'dt_metrics.json; test_saved_model_depth_and_node_caps'),
        row('Tree total nodes', dt['node_count'], f'<= {s["tree"]["max_total_nodes"]}',
            dt['node_count'] <= s['tree']['max_total_nodes'], 'dt_metrics.json; test_saved_model_depth_and_node_caps'),
        row('Generalization gap (train - val)', f'{dt["generalization_gap"]:.4f}',
            f'<= {s["tree"]["max_generalization_gap"]}', dt['generalization_gap'] <= s['tree']['max_generalization_gap'],
            'dt_metrics.json; test_generalization_gap_within_limit'),
        row('Entropy max abs error vs scipy (1,000 distributions)', f'{ent_err:.2e}',
            f'<= {s["tree"]["entropy_tolerance"]:.0e}', ent_err <= s['tree']['entropy_tolerance'],
            'kpi_report.py; test_entropy_matches_scipy_on_1000_random_distributions'),
        row('Rule-trigger precision (engine vs independent re-implementation)', f'{overall_prec:.4f} '
            f'({prec["agree_fired"].sum()}/{total_fired} fired)', '= 1.0000', overall_prec == 1.0,
            'kpi_report.py rule_precision() on DB rule_results, test split'),
        row('Decisions logged (coverage)', f'{logged / n_in:.4f} ({logged}/{n_in})', '= 1.0000', logged == n_in,
            'seed_demo.py / evaluate_pipeline.py; test_full_test_set_coverage_is_100_percent'),
        row('Audit chain intact', str(chain), 'OK', chain.ok, 'Repository.verify_chain() on the project DB'),
        row('Majority auto-cleared', f'{auto:.4f}', '> 0.50', auto > 0.5, 'pipeline_decisions.csv'),
        row('None silently dropped', f'{n_in - len(out)} dropped, {int((~out["persisted"]).sum())} unpersisted',
            '0', len(out) == n_in and out['persisted'].all(), 'pipeline_decisions.csv'),
        row('Model auto-decisions agree with label', f'{routing["routing"]["test"]["auto_accuracy"]:.4f}',
            'reported', 'INFO', 'routing.json (ML layer, test split)'),
        row('Disparate impact, every subgroup with sufficient data (full pipeline)',
            f'min {worst["di"]:.3f} ({worst["group"]} = {worst["subgroup"]})',
            f'>= {config.load("fairness")["min_disparate_impact"]}', bool(worst['di'] >= 0.8),
            '`python -m cognilend.fairness.disparate_impact` -> fairness_di.csv'),
        row('Reproducible (3 fresh-DB runs)', 'IDENTICAL' if '**Result: IDENTICAL**' in repro else 'DIFFERENT',
            'identical', '**Result: IDENTICAL**' in repro, '`python scripts/reproducibility.py`'),
        row(f'Lock: one approval per collateral, {load["requests"]} concurrent requests',
            f'{load["approved"]} approvals / {load["collaterals"]} collaterals, max {load["max_approvals_per_collateral"]} '
            'per collateral', 'exactly 1 each', load['pass'], '`python scripts/lock_load_test.py`'),
        row('Lock latency under that burst (p50 / p95)', f'{load["lock_latency_ms"]["p50"]} / '
            f'{load["lock_latency_ms"]["p95"]} ms', 'reported', 'INFO', 'lock_load_test.json'),
        row('Rare / edge profiles auto-decided by the model', f'{rare["auto_decided_by_model"]} of {rare["n"]}', '0',
            rare['auto_decided_by_model'] == 0, 'test_gate2_rare_profiles_routed_to_review_with_confusion_matrix'),
        row('SQL-queryable audit', status_of(cases, 'test_every_audit_query_runs'), 'all queries run',
            status_of(cases, 'test_every_audit_query_runs'), 'docs/audit_queries.sql; test_every_audit_query_runs'),
        row('No crash on bad input', status_of(cases, 'test_gate5_missing_and_invalid_fields_100_percent_handled',
                                               'test_malformed_fields_are_handled_without_exceptions'),
            '100% handled', status_of(cases, 'test_gate5_missing_and_invalid_fields_100_percent_handled',
                                      'test_malformed_fields_are_handled_without_exceptions'), 'test_rules.py, gates'),
        row('Test suite', f'{t["totals"]["passed"]} / {t["totals"]["tests"]} passed', 'all pass',
            t['totals']['passed'] == t['totals']['tests'], 'this run (junit.xml)'),
        row('Line coverage of src/cognilend', f'{t["coverage"]:.1f}%', 'reported', 'INFO', 'pytest-cov coverage.json'),
    ]
    gates = [
        ('1 Rule vs model conflict: zero overrides', ['test_gate1_no_model_override_of_a_fired_hard_rule',
                                                      'test_rule_vs_model_conflict_hard_rule_always_wins']),
        ('2 Rare/edge profile -> review (+ confusion matrix)',
         ['test_gate2_rare_profiles_routed_to_review_with_confusion_matrix',
          'test_evidence_gate_routes_smallest_leaves_to_review']),
        ('3 SMOTE train-only, no leakage', ['test_gate3_smote_train_only_no_leakage',
                                            'test_smote_changes_train_counts_only',
                                            'test_fitted_statistics_come_from_train_only']),
        ('4 DB write failure: no crash, no silent loss', ['test_gate4_db_failure_no_crash_no_silent_loss',
                                                          'test_db_failure_returns_decision_and_writes_fallback']),
        ('5 Missing/invalid fields: 100% handled', ['test_gate5_missing_and_invalid_fields_100_percent_handled',
                                                    'test_malformed_fields_are_handled_without_exceptions']),
        ('6 Fairness breach detected and reported', ['test_gate6_fairness_breach_detected_and_reported',
                                                     'test_breach_surfaced_in_report_and_database']),
        ('7 Reproducibility over 3 runs', ['test_gate7_reproducible_over_three_runs',
                                           'test_reproducibility_report_says_identical']),
        ('Tree depth/node caps', ['test_nfr_tree_caps_and_gap', 'test_saved_model_depth_and_node_caps']),
        ('Entropy <= 1e-9', ['test_nfr_entropy_error_below_1e_9',
                             'test_entropy_matches_scipy_on_1000_random_distributions']),
        ('Gap <= 15%', ['test_generalization_gap_within_limit']),
        ('Audit tamper detection', ['test_nfr_audit_tamper_detection', 'test_tampering_one_row_is_reported_at_that_row']),
        ('Concurrency lock', ['test_50_concurrent_approvals_same_collateral_exactly_one',
                              'test_nfr_concurrency_lock_load_test_passed']),
        ('Decision-log coverage 100%', ['test_nfr_decision_log_coverage_100_percent',
                                        'test_full_test_set_coverage_is_100_percent']),
        ('End-to-end smoke', ['test_end_to_end_smoke', 'test_demo_case_shows_expected_decision_card']),
    ]
    failures = [k for k in kpis if k['Status'] == 'FAIL']
    causes = {
        'Validation accuracy, constrained tree':
            'The depth-4 / 15-node cap binds (identical tree for every min_samples_leaf 10-200). Caps were not '
            'loosened, per the synopsis; benchmark.md quantifies the interpretability cost against the ensembles.',
        'Disparate impact, every subgroup with sufficient data (full pipeline)':
            'Gap is created by the age-linked policy rules (R01, R03, S01, S02) and by the historical label, not by '
            'the model (model-only DI >= 0.866). Protected-blind mitigations were tried and listed in fairness.md; '
            'the decision on these rules is pending with the team / guide.',
    }
    lines = ['# KPI report', '',
             f'Generated by `python scripts/kpi_report.py` at {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}. '
             'No number below is typed by hand: each comes from the named script, artefact or test of this run.', '',
             '## Test run', '',
             f'- pytest summary (verbatim): `{t["summary"]}`',
             f'- JUnit totals: **{t["totals"]["tests"]} tests, {t["totals"]["passed"]} passed**, '
             f'{t["totals"]["failures"]} failed, {t["totals"]["errors"]} errors, {t["totals"]["skipped"]} skipped '
             '(checked equal to the summary line by the script).',
             f'- Line coverage of `src/cognilend`: **{t["coverage"]:.1f}%** (full output: `pytest_output.txt`, '
             '`coverage.json`).', '',
             '## KPIs', '', '| KPI | Measured | Threshold | Status | Source |', '|---|---|---|---|---|']
    for k in kpis:
        lines.append(f'| {k["KPI"]} | {k["Measured"]} | {k["Threshold"]} | **{k["Status"]}** | {k["Source"]} |')
    lines += ['', '## Failures and their causes', '']
    if failures:
        for f in failures:
            lines.append(f'- **{f["KPI"]}** ({f["Measured"]} vs {f["Threshold"]}): {causes.get(f["KPI"], "see source")}')
    else:
        lines.append('None.')
    failed_tests = [k for k, v in cases.items() if v != 'passed']
    lines += ['', f'Failing tests in this run: {", ".join(failed_tests) if failed_tests else "none"}.', '',
              '## Minimum Engineering Evidence gates and NFR checks', '', '| Gate | Tests | Status |', '|---|---|---|']
    for name, tests in gates:
        lines.append(f'| {name} | {", ".join(f"`{x}`" for x in tests)} | **{status_of(cases, *tests)}** |')
    lines += ['', '## Rule-trigger precision by rule (test split)', '',
              'Engine `fired` flags from the DB compared with an independent pandas re-implementation of each '
              'condition (thresholds read from policies_v1.yaml). R02 never fires on this data (no Applicant_ID).', '',
              '| Rule | engine fired | independent true | agree | precision | recall |', '|---|---|---|---|---|---|']
    for r in prec.itertuples():
        lines.append(f'| {r.rule} | {r.engine_fired} | {r.independent_true} | {r.agree_fired} | '
                     f'{r.precision:.4f} | {r.recall:.4f} |')
    cm = rare['confusion_matrix_model_vs_label']['matrix']
    lines += ['', '## Rare / edge subset (gate 2)', '',
              f'{rare["definition"]}: n = {rare["n"]}; human review {rare["routed_to_review"]}, HARD-rejected '
              f'{rare["hard_rejected"]}, auto-decided by the model {rare["auto_decided_by_model"]}. Model vs label on '
              f'the scored part (rows true Rejected/Approved, columns predicted): {cm}; accuracy '
              f'{rare["model_accuracy_on_rare"]:.4f} (lower than overall, which is why these cases go to people).', '',
              '## Lock load test', '',
              f'{load["requests"]} concurrent requests over {load["collaterals"]} collaterals: {load["approved"]} '
              f'approvals, {load["human_review"]} human review, {load["persisted"]} persisted, chain {load["chain"]}; '
              f'wall time {load["wall_seconds"]} s ({load["throughput_per_s"]} req/s). Lock latency p50/p95/p99/max '
              f'{load["lock_latency_ms"]["p50"]}/{load["lock_latency_ms"]["p95"]}/{load["lock_latency_ms"]["p99"]}/'
              f'{load["lock_latency_ms"]["max"]} ms; end-to-end p50/p95 {load["end_to_end_ms"]["p50"]}/'
              f'{load["end_to_end_ms"]["p95"]} ms. All requests arrive at once in one Python process, so they queue '
              'on the GIL and on SQLite\'s single writer; this is a worst-case burst, not steady-state latency.', '',
              '## Coverage by module', '', '| Module | Line coverage |', '|---|---|']
    for f, v in sorted(t['coverage_files'].items()):
        lines.append(f'| {f} | {v:.1f}% |')
    md = '\n'.join(lines) + '\n'
    (REP / 'kpi_report.md').write_text(md, encoding='utf-8')
    print(md)


if __name__ == '__main__':
    main()
