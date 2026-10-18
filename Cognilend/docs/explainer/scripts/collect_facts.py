"""Collect every key number for the explainer into docs/explainer/facts.json.

Each fact is read from its source file by a locator, never typed by hand:
  json   -> a key path into a JSON file              e.g. "scores.test.confusion_matrix.0.0"
  yaml   -> a key path into a YAML file
  csv    -> "<row-key-col>=<row-key>[&col=val...]:<value-col>"
  regex  -> a regular expression whose first group is the value (Markdown / text files)
  xml    -> attribute of the first <testsuite> in a JUnit file

Run:  .venv/Scripts/python.exe docs/explainer/scripts/collect_facts.py
      .venv/Scripts/python.exe docs/explainer/scripts/collect_facts.py --check   (D7: re-read and compare)
"""
from __future__ import annotations

import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'docs' / 'explainer' / 'facts.json'

R = 'artifacts/reports/'
# (name, source file, kind, locator, short description)
SPEC = [
    # --- dataset / synthetic generator
    ('synthetic.seed', 'config/synthetic.yaml', 'yaml', 'seed', 'Random seed of the generator'),
    ('synthetic.n_rows', 'config/synthetic.yaml', 'yaml', 'n_rows', 'Rows in the raw synthetic file'),
    ('synthetic.n_duplicates', 'config/synthetic.yaml', 'yaml', 'n_duplicates', 'Exact duplicate rows injected'),
    ('synthetic.n_unlabelled', 'config/synthetic.yaml', 'yaml', 'n_unlabelled', 'Rows with blank Loan_Status'),
    ('synthetic.approval_rate_target', 'config/synthetic.yaml', 'yaml', 'approval_rate', 'Target approval share'),
    ('defect.whitespace_rate', 'config/synthetic.yaml', 'yaml', 'defects.whitespace_rate', 'Stray whitespace rate per text column'),
    ('defect.variant_rate', 'config/synthetic.yaml', 'yaml', 'defects.variant_rate', 'Spelling-variant rate per text column'),
    ('defect.amount_as_text', 'config/synthetic.yaml', 'yaml', 'defects.amount_as_text', 'Loan amounts written as Indian-grouped text'),
    ('defect.amount_with_rs_prefix', 'config/synthetic.yaml', 'yaml', 'defects.amount_with_rs_prefix', 'Of those, with "Rs." prefix'),
    ('defect.impossible_age', 'config/synthetic.yaml', 'yaml', 'defects.impossible_age', 'Rows with impossible age'),
    ('defect.negative_income', 'config/synthetic.yaml', 'yaml', 'defects.negative_income', 'Rows with negative income (sign error)'),
    ('defect.zero_income', 'config/synthetic.yaml', 'yaml', 'defects.zero_income', 'Rows with zero income'),
    ('defect.invalid_cibil', 'config/synthetic.yaml', 'yaml', 'defects.invalid_cibil', 'Rows with invalid CIBIL'),
    ('defect.impossible_experience', 'config/synthetic.yaml', 'yaml', 'defects.impossible_experience', 'Rows with impossible experience'),
    ('defect.home_tenure_in_years', 'config/synthetic.yaml', 'yaml', 'defects.home_tenure_in_years', 'Home-loan tenures written in years'),
    ('synthetic.raw_rows', R + 'synthetic_profile.json', 'json', 'raw_shape.0', 'Raw rows'),
    ('synthetic.raw_cols', R + 'synthetic_profile.json', 'json', 'raw_shape.1', 'Raw columns'),
    ('synthetic.approval_rate_unique', R + 'synthetic_profile.json', 'json', 'approval_rate_unique_rows', 'Approval rate, unique rows'),
    ('synthetic.any_rule_violated', R + 'synthetic_profile.json', 'json', 'any_rule_violated', 'Share violating any original rule'),
    ('synthetic.approval_if_violation', R + 'synthetic_profile.json', 'json', 'approval_rate_if_violation', 'Label approval rate among rule violators'),
    ('synthetic.approval_if_compliant', R + 'synthetic_profile.json', 'json', 'approval_rate_if_compliant', 'Label approval rate among compliant'),
    ('synthetic.acc_rules_only', R + 'synthetic_profile.json', 'json', 'accuracy_rules_only_predictor', 'Accuracy of rules-only predictor vs label'),
    ('synthetic.acc_noise_free', R + 'synthetic_profile.json', 'json', 'accuracy_noise_free_latent_score', 'Accuracy ceiling of noise-free latent score'),
    ('synthetic.ntc_rate', R + 'synthetic_profile.json', 'json', 'ntc_rate', 'New-to-credit share'),
    ('synthetic.median_income', R + 'synthetic_profile.json', 'json', 'median_monthly_income', 'Median monthly income (INR)'),
    ('synthetic.gender_n_male', R + 'synthetic_profile.json', 'json', 'label_rate_by_gender.Male.n', 'Male rows'),
    ('synthetic.gender_n_female', R + 'synthetic_profile.json', 'json', 'label_rate_by_gender.Female.n', 'Female rows'),
    ('synthetic.gender_n_tg', R + 'synthetic_profile.json', 'json', 'label_rate_by_gender.Transgender.n', 'Transgender rows'),
    ('synthetic.sha256', R + 'synthetic_profile.json', 'json', 'sha256', 'SHA-256 of raw file'),
    # --- preprocessing / split
    ('prep.rows_in', R + 'preprocess_summary.json', 'json', 'rows_in', 'Rows before cleaning'),
    ('prep.rows_out', R + 'preprocess_summary.json', 'json', 'rows_out', 'Rows after cleaning'),
    ('prep.n_features', R + 'preprocess_summary.json', 'json', 'feature_names.__len__', 'Model feature columns'),
    ('split.train_n', R + 'preprocess_summary.json', 'json', 'class_distribution.train.n', 'Training rows'),
    ('split.val_n', R + 'preprocess_summary.json', 'json', 'class_distribution.val.n', 'Validation rows'),
    ('split.test_n', R + 'preprocess_summary.json', 'json', 'class_distribution.test.n', 'Test rows'),
    ('split.train_approved_share', R + 'preprocess_summary.json', 'json', 'class_distribution.train.approved_share', 'Approved share, train'),
    ('split.val_approved_share', R + 'preprocess_summary.json', 'json', 'class_distribution.val.approved_share', 'Approved share, val'),
    ('split.test_approved_share', R + 'preprocess_summary.json', 'json', 'class_distribution.test.approved_share', 'Approved share, test'),
    ('smote.before_rejected', R + 'preprocess_summary.json', 'json', 'smote_train_counts.before.0', 'Train Rejected before SMOTE'),
    ('smote.before_approved', R + 'preprocess_summary.json', 'json', 'smote_train_counts.before.1', 'Train Approved before SMOTE'),
    ('smote.after_rejected', R + 'preprocess_summary.json', 'json', 'smote_train_counts.after.0', 'Train Rejected after SMOTE'),
    ('smote.after_approved', R + 'preprocess_summary.json', 'json', 'smote_train_counts.after.1', 'Train Approved after SMOTE'),
    ('contract.n_fields', 'docs/traceability.md', 'regex', r'contract: (\d+) fields', 'Fields in the data contract (per traceability)'),
    # --- decision tree
    ('dt.depth', R + 'dt_metrics.json', 'json', 'depth', 'Tree depth'),
    ('dt.node_count', R + 'dt_metrics.json', 'json', 'node_count', 'Tree nodes'),
    ('dt.n_leaves', R + 'dt_metrics.json', 'json', 'n_leaves', 'Tree leaves'),
    ('dt.cap_depth', R + 'dt_metrics.json', 'json', 'caps.max_depth', 'Depth cap'),
    ('dt.cap_nodes', R + 'dt_metrics.json', 'json', 'caps.max_total_nodes', 'Node cap'),
    ('dt.min_samples_leaf', R + 'dt_metrics.json', 'json', 'params.min_samples_leaf', 'Chosen min_samples_leaf'),
    ('dt.train_acc', R + 'dt_metrics.json', 'json', 'train_accuracy', 'Train accuracy'),
    ('dt.val_acc', R + 'dt_metrics.json', 'json', 'val_accuracy', 'Validation accuracy'),
    ('dt.test_acc', R + 'dt_metrics.json', 'json', 'test_accuracy', 'Test accuracy'),
    ('dt.gap', R + 'dt_metrics.json', 'json', 'generalization_gap', 'Generalization gap train-val'),
    ('dt.kpi_val_min', R + 'dt_metrics.json', 'json', 'kpi_val_accuracy_min', 'KPI threshold val accuracy'),
    ('dt.gap_max', R + 'dt_metrics.json', 'json', 'gap_max', 'Gap limit'),
    ('dt.test_roc_auc', R + 'dt_metrics.json', 'json', 'scores.test.roc_auc', 'Test ROC-AUC'),
    ('dt.val_roc_auc', R + 'dt_metrics.json', 'json', 'scores.val.roc_auc', 'Val ROC-AUC'),
    ('dt.test_cm_TN', R + 'dt_metrics.json', 'json', 'scores.test.confusion_matrix.0.0', 'Test: actual Rejected, predicted Rejected'),
    ('dt.test_cm_FP', R + 'dt_metrics.json', 'json', 'scores.test.confusion_matrix.0.1', 'Test: actual Rejected, predicted Approved'),
    ('dt.test_cm_FN', R + 'dt_metrics.json', 'json', 'scores.test.confusion_matrix.1.0', 'Test: actual Approved, predicted Rejected'),
    ('dt.test_cm_TP', R + 'dt_metrics.json', 'json', 'scores.test.confusion_matrix.1.1', 'Test: actual Approved, predicted Approved'),
    ('dt.test_precision_approved', R + 'dt_metrics.json', 'json', 'scores.test.per_class.Approved.precision', 'Test precision (Approved)'),
    ('dt.test_recall_approved', R + 'dt_metrics.json', 'json', 'scores.test.per_class.Approved.recall', 'Test recall (Approved)'),
    ('dt.test_f1_approved', R + 'dt_metrics.json', 'json', 'scores.test.per_class.Approved.f1-score', 'Test F1 (Approved)'),
    ('dt.test_precision_rejected', R + 'dt_metrics.json', 'json', 'scores.test.per_class.Rejected.precision', 'Test precision (Rejected)'),
    ('dt.test_recall_rejected', R + 'dt_metrics.json', 'json', 'scores.test.per_class.Rejected.recall', 'Test recall (Rejected)'),
    ('dt.ig_top_feature', R + 'dt_metrics.json', 'json', 'information_gain_ranking.0.feature', 'Highest information-gain feature'),
    ('dt.ig_top_gain', R + 'dt_metrics.json', 'json', 'information_gain_ranking.0.gain', 'Its information gain (bits)'),
    ('dt.ig_second_feature', R + 'dt_metrics.json', 'json', 'information_gain_ranking.1.feature', 'Second feature'),
    ('dt.ig_second_gain', R + 'dt_metrics.json', 'json', 'information_gain_ranking.1.gain', 'Its information gain (bits)'),
    ('dt.root_split', R + 'tree_rules.txt', 'regex', r'if (cibil_score <= \d+) CIBIL', 'Root split rule'),
    ('dt.entropy_max_abs_error', R + 'kpi_report.md', 'regex', r'Entropy max abs error[^|]*\| ([^|]+?) \|', 'Entropy error vs scipy'),
    # --- benchmark
    *[(f'bench.{m}.{c}', R + 'benchmark.csv', 'csv', f'model={m}:{c}', f'{m} {c}')
      for m in ('decision_tree', 'random_forest', 'xgboost', 'gradient_boosting')
      for c in ('test_accuracy', 'test_f1', 'test_roc_auc', 'val_accuracy', 'cv_accuracy_mean', 'complexity')],
    ('bench.interpretability_cost', R + 'kpi_report.md', 'regex', r'Interpretability cost[^|]*\| ([0-9.]+) \|', 'Best ensemble minus tree, test acc'),
    # --- confidence / routing
    ('conf.tau', 'config/settings.yaml', 'yaml', 'confidence.tau', 'Confidence threshold tau'),
    ('conf.n_min', 'config/settings.yaml', 'yaml', 'confidence.n_min', 'Minimum leaf support'),
    ('conf.prior', R + 'routing.json', 'json', 'prior', 'Beta prior'),
    ('conf.target_auto_acc', R + 'routing.json', 'json', 'target_auto_accuracy', 'Target auto accuracy'),
    ('conf.brier_bayes', R + 'routing.json', 'json', 'brier.bayes', 'Brier score, Bayesian'),
    ('conf.brier_raw', R + 'routing.json', 'json', 'brier.raw', 'Brier score, raw leaf fraction'),
    ('route.test_auto', R + 'routing.json', 'json', 'routing.test.auto', 'Test auto (ML layer)'),
    ('route.test_review', R + 'routing.json', 'json', 'routing.test.review', 'Test review (ML layer)'),
    ('route.test_auto_share', R + 'routing.json', 'json', 'routing.test.auto_share', 'Test auto share (ML layer)'),
    ('route.test_auto_acc', R + 'routing.json', 'json', 'routing.test.auto_accuracy', 'Test auto accuracy (ML layer)'),
    ('route.test_review_acc', R + 'routing.json', 'json', 'routing.test.review_accuracy', 'Test review accuracy (ML layer)'),
    ('route.val_auto_share', R + 'routing.json', 'json', 'routing.val.auto_share', 'Val auto share'),
    ('route.val_auto_acc', R + 'routing.json', 'json', 'routing.val.auto_accuracy', 'Val auto accuracy'),
    ('rare.n', R + 'rare_subset.json', 'json', 'n', 'Rare/edge profiles'),
    ('rare.auto_by_model', R + 'rare_subset.json', 'json', 'auto_decided_by_model', 'Rare profiles auto-decided by model'),
    ('rare.routed_to_review', R + 'rare_subset.json', 'json', 'routed_to_review', 'Rare profiles routed to review'),
    ('rare.hard_rejected', R + 'rare_subset.json', 'json', 'hard_rejected', 'Rare profiles hard-rejected'),
    # --- rules
    ('policy.version', 'config/policies_v1.yaml', 'yaml', 'version', 'Policy version'),
    ('policy.n_rules', 'config/policies_v1.yaml', 'yaml', 'rules.__len__', 'Number of rules'),
    ('rules.train_hard_reject_share', R + 'rule_analysis.json', 'json', 'buckets.REJECT (HARD rule).share', 'Train share rejected by HARD rule'),
    ('rules.train_soft_review_share', R + 'rule_analysis.json', 'json', 'buckets.REVIEW (SOFT rule).share', 'Train share sent to review by SOFT rule'),
    ('rules.train_pass_share', R + 'rule_analysis.json', 'json', 'buckets.PASS.share', 'Train share passing all rules'),
    ('rules.precision', R + 'kpi_report.md', 'regex', r'Rule-trigger precision[^|]*\| ([0-9.]+ \(\d+/\d+ fired\)) \|', 'Rule-trigger precision'),
    # --- pipeline
    ('pipe.n', R + 'pipeline_eval.md', 'regex', r'Applications in: \*\*(\d+)\*\*', 'Test applications through pipeline'),
    ('pipe.approved_model', R + 'pipeline_eval.md', 'regex', r'\| Approved \| MODEL \| (\d+) \|', 'Approved by model'),
    ('pipe.review_model', R + 'pipeline_eval.md', 'regex', r'\| Human Review \| MODEL \| (\d+) \|', 'Review (low confidence)'),
    ('pipe.review_rule', R + 'pipeline_eval.md', 'regex', r'\| Human Review \| RULE \| (\d+) \|', 'Review (SOFT rule / lock)'),
    ('pipe.rejected_model', R + 'pipeline_eval.md', 'regex', r'\| Rejected \| MODEL \| (\d+) \|', 'Rejected by model'),
    ('pipe.rejected_rule', R + 'pipeline_eval.md', 'regex', r'\| Rejected \| RULE \| (\d+) \|', 'Rejected by rules / invalid input'),
    ('pipe.auto_share', R + 'pipeline_eval.md', 'regex', r'Auto-decided[^*]*\*\*([0-9.]+%)\*\*', 'Pipeline auto-decided share'),
    ('pipe.model_auto_acc', R + 'pipeline_eval.md', 'regex', r'Model auto-decisions: n = \d+, accuracy vs label \*\*([0-9.]+)\*\*', 'Pipeline model auto-decision accuracy'),
    ('pipe.ms_per_decision', R + 'pipeline_eval.md', 'regex', r'([0-9.]+) ms per decision', 'Mean time per decision'),
    ('pipe.rule_result_rows', R + 'pipeline_eval.md', 'regex', r'Rule-result rows: ([0-9,]+)', 'Rule-result rows'),
    # --- DB / lock / audit
    ('audit.n_queries', 'docs/traceability.md', 'regex', r'\| (\d+) queries \|', 'SQL audit queries'),
    ('lock.requests', R + 'lock_load_test.json', 'json', 'requests', 'Lock load test requests'),
    ('lock.collaterals', R + 'lock_load_test.json', 'json', 'collaterals', 'Distinct collaterals'),
    ('lock.approved', R + 'lock_load_test.json', 'json', 'approved', 'Approvals granted'),
    ('lock.max_per_collateral', R + 'lock_load_test.json', 'json', 'max_approvals_per_collateral', 'Max approvals per collateral'),
    ('lock.p50_ms', R + 'lock_load_test.json', 'json', 'lock_latency_ms.p50', 'Lock latency p50 ms'),
    ('lock.p95_ms', R + 'lock_load_test.json', 'json', 'lock_latency_ms.p95', 'Lock latency p95 ms'),
    ('lock.chain', R + 'lock_load_test.json', 'json', 'chain', 'Audit chain after load test'),
    # --- fairness
    ('fair.min_di', 'config/fairness.yaml', 'yaml', 'min_disparate_impact', 'DI threshold'),
    ('fair.min_group_size', 'config/fairness.yaml', 'yaml', 'min_group_size', 'Minimum subgroup size'),
    ('fair.pipeline_min_di', R + 'fairness_di.csv', 'csv', 'mode=pipeline&group=age_band&subgroup=<=25:di', 'Pipeline DI, age <=25'),
    ('fair.pipeline_di_26_35', R + 'fairness_di.csv', 'csv', 'mode=pipeline&group=age_band&subgroup=26-35:di', 'Pipeline DI, age 26-35'),
    ('fair.pipeline_di_gt55', R + 'fairness_di.csv', 'csv', 'mode=pipeline&group=age_band&subgroup=>55:di', 'Pipeline DI, age >55'),
    ('fair.pipeline_di_male', R + 'fairness_di.csv', 'csv', 'mode=pipeline&group=gender&subgroup=Male:di', 'Pipeline DI, Male vs Female'),
    ('fair.pipeline_di_dep0', R + 'fairness_di.csv', 'csv', 'mode=pipeline&group=dependents&subgroup=0:di', 'Pipeline DI, 0 dependents'),
    ('fair.model_only_di_le25', R + 'fairness_di.csv', 'csv', 'mode=model_only&group=age_band&subgroup=<=25:di', 'Model-only DI, age <=25'),
    ('fair.rules_only_di_le25', R + 'fairness_di.csv', 'csv', 'mode=rules_only&group=age_band&subgroup=<=25:di', 'Rules-only DI, age <=25'),
    ('fair.label_di_le25', R + 'fairness_di.csv', 'csv', 'mode=label&group=age_band&subgroup=<=25:di', 'Historical-label DI, age <=25'),
    ('fair.model_only_min_di_text', R + 'kpi_report.md', 'regex', r'model-only DI >= ([0-9.]+)', 'Model-only minimum DI'),
    # --- add-on
    ('maxamt.step', 'config/features.yaml', 'yaml', 'max_amount_suggestion.step', 'Grid step INR'),
    ('maxamt.min_loan', 'config/features.yaml', 'yaml', 'max_amount_suggestion.min_loan_amount', 'Minimum suggested amount'),
    ('maxamt.rejected_cases', 'reports/feature_max_amount_eval.md', 'regex', r'\| rejected_cases \| (\d+) \|', 'Rejected test cases'),
    ('maxamt.possible', 'reports/feature_max_amount_eval.md', 'regex', r'\| possible \| (\d+) \|', 'Lower amount possible'),
    ('maxamt.not_possible', 'reports/feature_max_amount_eval.md', 'regex', r'\| not_possible \| (\d+) \|', 'Not possible'),
    ('maxamt.confirmed', 'reports/feature_max_amount_eval.md', 'regex', r'\| confirmed_approved \| (\d+) \|', 'Confirmed approved by normal pipeline'),
    ('maxamt.p50_ms', 'reports/feature_max_amount_eval.md', 'regex', r'\| runtime_ms_p50 \| ([0-9.]+) \|', 'Search time p50 ms'),
    ('maxamt.max_ms', 'reports/feature_max_amount_eval.md', 'regex', r'\| runtime_ms_max \| ([0-9.]+) \|', 'Search time max ms'),
    # --- testing / KPI
    ('tests.junit_total', R + 'junit.xml', 'xml', 'tests', 'Tests in last full JUnit run (pre add-on)'),
    ('tests.junit_failures', R + 'junit.xml', 'xml', 'failures', 'Failures in that run'),
    ('tests.coverage', R + 'kpi_report.md', 'regex', r'Line coverage of `src/cognilend`: \*\*([0-9.]+%)\*\*', 'Line coverage'),
    ('tests.addons_collected', 'reports/pytest_after_addons.txt', 'regex', r'collected (\d+) items', 'Add-on tests collected (partial log)'),
    ('kpi.auto_cleared', R + 'kpi_report.md', 'regex', r'Majority auto-cleared \| ([0-9.]+) \|', 'Majority auto-cleared (pipeline)'),
    ('kpi.reproducible', R + 'kpi_report.md', 'regex', r'Reproducible \(3 fresh-DB runs\) \| (\w+) \|', 'Reproducibility'),
    ('stress.resilience_example', R + 'stress_twin_example.json', 'json', 'result.resilience', 'Stress-twin example resilience score'),
]


def _walk(obj, path: str):
    for part in path.split('.') if path else []:
        if part == '__len__':
            return len(obj)
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def _json_path(path: str, raw: str):
    # keys may themselves contain dots/spaces (rule_analysis buckets); greedy match against real keys
    d = json.loads(raw)
    parts, cur, i = path.split('.'), d, 0
    while i < len(parts):
        if parts[i] == '__len__':
            return len(cur)
        if isinstance(cur, list):
            cur, i = cur[int(parts[i])], i + 1
            continue
        for j in range(len(parts), i, -1):
            key = '.'.join(parts[i:j])
            if key in cur:
                cur, i = cur[key], j
                break
        else:
            raise KeyError(path)
    return cur


def read(source: str, kind: str, loc: str):
    p = ROOT / source
    raw = p.read_text(encoding='utf-8')
    if kind == 'json':
        return _json_path(loc, raw)
    if kind == 'yaml':
        return _walk(yaml.safe_load(raw), loc)
    if kind == 'csv':
        cond, col = loc.rsplit(':', 1)
        want = dict(c.split('=', 1) for c in cond.split('&'))
        for row in csv.DictReader(raw.splitlines()):
            if all(row[k] == v for k, v in want.items()):
                v = row[col]
                try:
                    return float(v) if '.' in v else int(v)
                except ValueError:
                    return v
        raise KeyError(loc)
    if kind == 'regex':
        m = re.search(loc, raw)
        if not m:
            raise KeyError(loc)
        v = m.group(1).strip()
        try:
            return float(v) if re.fullmatch(r'-?\d+\.\d+(e[-+]?\d+)?', v) else int(v.replace(',', ''))
        except ValueError:
            return v
    if kind == 'xml':
        return int(ET.fromstring(raw).find('testsuite').attrib[loc])
    raise ValueError(kind)


def collect():
    facts, errors = [], []
    for name, src, kind, loc, desc in SPEC:
        try:
            facts.append({'name': name, 'value': read(src, kind, loc), 'source': src,
                          'kind': kind, 'locator': loc, 'description': desc})
        except Exception as e:  # noqa: BLE001 -- report, never invent
            errors.append(f'{name}: {type(e).__name__} {e}')
            facts.append({'name': name, 'value': 'not measured', 'source': src,
                          'kind': kind, 'locator': loc, 'description': desc})
    return facts, errors


def main():
    facts, errors = collect()
    if '--check' in sys.argv:
        old = {f['name']: f['value'] for f in json.loads(OUT.read_text(encoding='utf-8'))}
        diff = [f"{f['name']}: facts.json={old.get(f['name'])!r} source={f['value']!r}"
                for f in facts if old.get(f['name']) != f['value']]
        print('\n'.join(diff) or f'OK: all {len(facts)} facts match their sources')
        sys.exit(1 if diff else 0)
    OUT.write_text(json.dumps(facts, indent=1, ensure_ascii=False), encoding='utf-8')
    print(f'{len(facts)} facts written to {OUT.relative_to(ROOT)}; {len(errors)} not found')
    for e in errors:
        print('  MISSING', e)


if __name__ == '__main__':
    main()
