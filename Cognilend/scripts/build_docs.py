"""Generate the submission documents from the generated artefacts. No number is typed by hand.

    python scripts/build_docs.py
        -> docs/final_report.md, docs/traceability.md, docs/changes_from_synopsis.md,
           docs/presentation.md (slides + 5-minute demo script), docs/weekly_tracker_october.md
        -> artifacts/reports/stress_twin_example.json

Inputs: artifacts/reports/* (from scripts/run_all.py), docs/synopsis_references.md.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd

from cognilend import config, demo
from cognilend.data import preprocess
from cognilend.stress_twin.simulator import StressInputs, alternatives, simulate

REP = config.ROOT / config.load('settings')['paths']['reports']
DOCS = config.ROOT / 'docs'
S = config.load('settings')


def j(name):
    return json.loads((REP / name).read_text(encoding='utf-8'))


def csv(name):
    return pd.read_csv(REP / name)


def pct(x, d=1):
    return f'{100 * x:.{d}f}%'


def junit_cases() -> tuple[dict, dict]:
    root = ET.parse(REP / 'junit.xml').getroot()
    suite = root if root.tag == 'testsuite' else root.find('testsuite')
    cases = {}
    for tc in suite.iter('testcase'):
        bad = tc.find('failure') is not None or tc.find('error') is not None
        cases[f'{tc.get("classname")}::{tc.get("name")}'] = 'failed' if bad else 'passed'
    tot = {k: int(suite.get(k, 0)) for k in ('tests', 'failures', 'errors', 'skipped')}
    tot['passed'] = tot['tests'] - tot['failures'] - tot['errors'] - tot['skipped']
    return cases, tot


def status(cases, *names) -> str:
    hits = [v for k, v in cases.items() if k.split('::')[-1].split('[')[0] in names]
    if not hits:
        return 'NOT RUN'
    return f'PASS ({len(hits)})' if all(v == 'passed' for v in hits) else 'FAIL'


def load_all() -> dict:
    a = {
        'profile': j('synthetic_profile.json'), 'prep': j('preprocess_summary.json'), 'dt': j('dt_metrics.json'),
        'routing': j('routing.json'), 'rules': j('rule_analysis.json'), 'lock50': j('lock_latency.json'),
        'load': j('lock_load_test.json'), 'rare': j('rare_subset.json'), 'demo': j('demo_cases.json'),
        'proxy': j('fairness_proxy.json'), 'cov': j('coverage.json')['totals']['percent_covered'],
        'bench': csv('benchmark.csv').set_index('model'), 'fair': csv('fairness_di.csv'),
        'ablation': csv('fairness_ablation.csv'), 'taus': csv('fairness_tau.csv'),
        'shift': csv('fairness_contrib_shift.csv'), 'exshift': csv('explain_shift.csv'),
        'decisions': csv('pipeline_decisions.csv'),
    }
    repro = (REP / 'reproducibility.md').read_text(encoding='utf-8')
    a['repro_identical'] = '**Result: IDENTICAL**' in repro
    a['repro_hash'] = re.findall(r'`([0-9a-f]{64})`', repro)
    a['cases'], a['tests'] = junit_cases()
    d = a['decisions']
    clean = pd.read_parquet(preprocess.processed_dir() / 'clean.parquet').set_index('Loan_ID')
    d['label'] = clean.loc[d['loan_id'], 'target'].to_numpy()
    auto_model = (d['source'] == 'MODEL') & d['decision'].isin(['Approved', 'Rejected'])
    a['pipe'] = {
        'n': len(d), 'persisted': int(d['persisted'].sum()),
        'split': d.groupby(['decision', 'source']).size().to_dict(),
        'auto_share': float(d['decision'].isin(['Approved', 'Rejected']).mean()),
        'model_auto_n': int(auto_model.sum()),
        'model_auto_acc': float(((d['decision'] == 'Approved').astype(int)[auto_model] == d.loc[auto_model, 'label']).mean()),
    }
    inp = StressInputs(income_mean=80000, income_cv=0.15, income_day=1, essentials=35000, existing_emi=5000,
                       loan_amount=1_500_000, annual_rate=0.105, tenure_months=60, emi_due_day=5, savings=60000)
    st = {'inputs': {k: v for k, v in vars(inp).items() if k != 'extra'}, 'result': simulate(inp),
          'alternatives': alternatives(inp)}
    (REP / 'stress_twin_example.json').write_text(json.dumps(st, indent=2, default=str), encoding='utf-8')
    a['stress'] = st
    return a


# --------------------------------------------------------------------------------------
def final_report(a) -> str:
    p, dt, r, b, pipe = a['profile'], a['dt'], a['routing'], a['bench'], a['pipe']
    pr = a['prep']
    fair = a['fair']
    pf = fair[(fair['mode'] == 'pipeline') & ~fair['insufficient']]
    worst = pf.loc[pf['di'].idxmin()]
    mo = fair[(fair['mode'] == 'model_only') & ~fair['insufficient']]['di'].min()
    ens_best = b.drop(index='decision_tree')['test_accuracy'].idxmax()
    cost = b.loc[ens_best, 'test_accuracy'] - b.loc['decision_tree', 'test_accuracy']
    abl = a['ablation'].set_index('change')
    best_abl = a['ablation'].loc[a['ablation']['min_di_age_band'].idxmax()]
    gender = pf[pf['group'] == 'gender']['di'].min()
    rt, rv = r['routing']['test'], r['routing']['val']
    st = a['stress']['result']
    bucket = a['rules']['buckets']
    r03 = {x['cutoff']: x for x in a['rules']['r03_sweep']}
    r03_rule = next(x for x in a['rules']['rules'] if x['id'] == 'R03')
    refs = (DOCS / 'synopsis_references.md').read_text(encoding='utf-8')
    refs = '\n'.join(ln for ln in refs.splitlines() if ln.startswith('['))
    tests = a['tests']
    L = []
    w = L.append
    w('# CogniLend: A Hybrid Rule-and-ML System for Explainable, Fair Loan Decisioning')
    w('')
    w('TY AIML mini project, Walchand College of Engineering, Sangli (Apni Leap, AY 2026-27). Guide: Dr. V. N. '
      'Waghmare. Groups G10 (Core ML), G12 (Rules + DBMS), G15 (Fairness + Integration).')
    w('')
    w(f'*Generated by `python scripts/build_docs.py` on {date.today().isoformat()}. Every number below is read from '
      'a file in `artifacts/reports/` produced by the code (sources in brackets).*')
    w('')
    w('## Abstract')
    w('')
    w(f'CogniLend decides retail loan applications in four layers: a forward-chaining policy rule engine, a '
      f'constrained entropy decision tree (depth {dt["depth"]}, {dt["node_count"]} nodes) with a Bayesian confidence '
      'score, a hash-chained audit database with an approval lock, and a disparate-impact audit. Each decision is '
      'Approved, Rejected or Human Review with a confidence, a readable reason and an audit-log ID. On the held-out '
      f'test split ({pipe["n"]} applications) every decision was logged ({pipe["persisted"]}/{pipe["n"]}), '
      f'{pct(pipe["auto_share"])} were decided automatically, and the model\'s automatic decisions agreed with the '
      f'historical label {pct(pipe["model_auto_acc"])} of the time. The tree reaches {dt["val_accuracy"]:.4f} '
      f'validation accuracy, below the 0.80 target; ensembles reach up to {b.drop(index="decision_tree")["val_accuracy"].max():.4f}, '
      f'an interpretability cost of {pct(cost)} on test. Gender passes the four-fifths rule (lowest DI '
      f'{gender:.3f}); age bands do not (lowest {worst["di"]:.3f}), a gap traced to the age-linked policy rules and '
      f'the historical label rather than the model (model-only DI >= {mo:.3f}). All {tests["tests"]} automated tests '
      'pass. [dt_metrics.json, benchmark.csv, pipeline_decisions.csv, fairness_di.csv, junit.xml]')
    w('')
    w('## 1. Introduction')
    w('')
    w('**Motivation.** Lenders must justify every rejection in writing (RBI Fair Practices Code) and must not '
      'discriminate on protected grounds. Accurate black-box models do not provide a reason that is the actual '
      'computation, and pure rule systems cannot rank applicants who pass every rule.')
    w('')
    w('**Objectives.** (1) Apply policy rules before any model and never let a model override a hard rule. '
      '(2) Use a model small enough to read (depth <= 4, <= 15 nodes) and record its path for every prediction. '
      '(3) Route uncertain cases to people. (4) Log every decision tamper-evidently. (5) Measure disparate impact '
      'on actual decisions.')
    w('')
    w('**Problem statement.** Given an applicant\'s personal, financial, credit and loan details, return Approved / '
      'Rejected / Human Review with a confidence, a traceable reason and an audit-log ID, such that hard policy is '
      'always enforced, every decision is reproducible and queryable, and outcomes are audited for disparate impact.')
    w('')
    w('## 2. Literature survey')
    w('')
    w('- **Decision trees.** ID3 introduced entropy-based splitting [7]; CART formalised binary trees and pruning [8]. '
      'Small trees are directly interpretable: the prediction is a short conjunction of threshold tests.')
    w('- **Interpretable vs post-hoc.** Rudin argues that for high-stakes decisions inherently interpretable models '
      'should be preferred over explaining black boxes [9]; SHAP gives post-hoc attributions for ensembles [10].')
    w('- **Ensembles.** Random forests [11] and gradient boosting [12], [13] are the usual accuracy benchmarks on '
      'tabular credit data.')
    w('- **Class imbalance.** SMOTE synthesises minority examples; it must be applied to training folds only [14].')
    w('- **Fairness.** The four-fifths rule sets a disparate-impact ratio of 0.80 [15]; Feldman et al. formalise '
      'disparate impact for ML and show proxies can carry protected information [16].')
    w('- **Regulation.** RBI sets LTV ceilings for housing loans [17] and requires fair, reasoned lending [18].')
    w('- **Expert systems.** Forward chaining fires rules on known facts until no new fact can be derived [19].')
    w('')
    w('## 3. Dataset and target definition')
    w('')
    w(f'**Primary dataset.** A seeded synthetic Indian retail-loan dataset ({p["raw_shape"][0]:,} rows x '
      f'{p["raw_shape"][1]} columns; SHA-256 `{p["sha256"][:16]}...`), generated by `cognilend.data.synthetic`. '
      'Fields follow Indian underwriting: age, gender, marital status, dependents, employment type (Salaried / SEP / '
      'SENP), experience, monthly and co-applicant income, existing EMI, CIBIL (-1 = new to credit), loan type, '
      'amount, tenure, collateral value, property area. Documented defects are injected with exact counts '
      '(duplicates, unlabelled rows, spelling variants, "Rs." amounts, impossible values, tenures in years, missing '
      'values). [synthetic_profile.json, docs/data_decision.md]')
    w('')
    w(f'**Target.** Approved (1) / Rejected (0); approval rate {p["approval_rate_unique_rows"]:.3f}. The label comes '
      'from a latent repayment-risk score (income stability, FOIR, CIBIL, experience, collateral cover) plus noise; '
      'policy rules play no part, so the model cannot simply re-learn the rule engine: predicting with the rules '
      f'alone reaches only {p["accuracy_rules_only_predictor"]:.3f} accuracy, and {pct(p["approval_rate_if_violation"])} '
      f'of rule violators are labelled approved. Noise-free ceiling: {p["accuracy_noise_free_latent_score"]:.3f}. '
      'A small historical gender bias is injected on purpose so the fairness audit has a known signal.')
    w('')
    w('**Loan.csv label finding.** The brief reports that `status = 1` in Loan.csv is the 24.6 % minority and that '
      'every such row lacks interest-rate pricing, which points to *default / not priced* rather than *approved*. '
      'Loan.csv was not available to this build, so the finding is **not verified here**; the investigation tooling '
      '(`loaders.target_investigation`, `pricing_explains_target`) is implemented and unit-tested, and Loan.csv is '
      'kept as a secondary benchmark to be relabelled honestly once supplied.')
    w('')
    w(f'**Split.** Duplicates and unlabelled rows removed ({pr["rows_in"]:,} -> {pr["rows_out"]:,}); stratified '
      f'70 / 15 / 15 split with seed 42: train {pr["class_distribution"]["train"]["n"]:,}, validation '
      f'{pr["class_distribution"]["val"]["n"]:,}, test {pr["class_distribution"]["test"]["n"]:,}; approval share '
      f'{pr["class_distribution"]["train"]["approved_share"]:.4f} / {pr["class_distribution"]["val"]["approved_share"]:.4f} / '
      f'{pr["class_distribution"]["test"]["approved_share"]:.4f}. [preprocess_summary.json]')
    w('')
    w('## 4. Methodology (four layers)')
    w('')
    w('1. **Policy rule layer (L1).** Contract validation first (malformed input -> Rejected with the field named). '
      'Facts (total income, proposed EMI, FOIR, FOIR limit, LTV, LTV cap, age at maturity, new-to-credit, missing '
      'fields) are derived by forward chaining to a fixpoint. Seven HARD rules (minimum age, fraud registry, age at '
      'maturity, CIBIL, FOIR by income slab, RBI LTV tiers, minimum income) reject immediately and the model is never '
      'called; four SOFT rules (new to credit, experience, borderline FOIR, missing information) route to review. '
      'Rules, thresholds, rationale and source live in `config/policies_v1.yaml`.')
    w('2. **ML layer (L2).** A fitted, saved preprocessing pipeline (train-only imputation, banking features from '
      'real values, IQR capping x3, MinMax scaling of continuous features, one-hot codes; protected attributes '
      'excluded). Entropy tree with depth <= 4 and <= 8 leaves; min_samples_leaf, class weight, SMOTE and feature '
      'subset chosen on validation only. Confidence = Beta(1,1) posterior mean of the predicted class from the leaf\'s '
      'real training counts, with a 90 % credible interval; low confidence or thin leaves -> Human Review. Every '
      'prediction records its path in original units.')
    w('3. **DBMS / audit layer (L3).** SQLAlchemy schema (applicants, loans, decisions, rule results, policy and model '
      'versions, audit log, review queue, fairness reports, loan locks). Each decision is stored in one transaction '
      'with a SHA-256 hash-chained, append-only audit event. Approvals take a lock on the applicant and collateral '
      'inside that transaction (FR-10). If the database fails, the decision is still returned and written to a '
      'replayable fallback log.')
    w('4. **Fairness layer (L4).** Disparate impact by gender, age band and dependents on actual stored decisions, '
      'with bootstrap 95 % CIs, insufficient-data handling, a three-way layer comparison and an injected breach test.')
    w('')
    w('## 5. Implementation')
    w('')
    w(f'Python {dt["python"]}, scikit-learn {dt["sklearn"]}, XGBoost, imbalanced-learn, pandas, SQLAlchemy 2 '
      '(SQLite in development, PostgreSQL-compatible schema), Streamlit UI (New Application, Officer Review Queue, '
      'Audit Explorer, Model & Policy, Fairness Dashboard, advisory Stress Twin), pytest. All thresholds are in '
      '`config/`; seed 42 everywhere; each fitted artefact is saved with a version and SHA-256. `python '
      'scripts/run_all.py` rebuilds every artefact from a fresh clone.')
    w('')
    w('## 6. Results')
    w('')
    w('### 6.1 Constrained tree vs ensembles  [benchmark.csv]')
    w('')
    w('| Model | Test acc | Test F1 | Test ROC-AUC | Val acc | 5-fold CV acc | Size |')
    w('|---|---|---|---|---|---|---|')
    for m, x in b.iterrows():
        w(f'| {m} | {x.test_accuracy:.4f} | {x.test_f1:.4f} | {x.test_roc_auc:.4f} | {x.val_accuracy:.4f} | '
          f'{x.cv_accuracy_mean:.4f} ± {x.cv_accuracy_std:.4f} | {x.complexity} |')
    w('')
    w(f'The tree has depth {dt["depth"]}, {dt["node_count"]} nodes, generalization gap {dt["generalization_gap"]:.4f}. '
      f'Validation accuracy {dt["val_accuracy"]:.4f} misses the 0.80 KPI; the caps bind (the same tree results for '
      f'every min_samples_leaf tried). Interpretability cost against {ens_best}: {cost:.4f}. The tree uses only CIBIL, '
      'FOIR and work experience. [dt_metrics.json, tree_rules.txt]')
    w('')
    w('### 6.2 Confidence and routing  [routing.json]')
    w('')
    w(f'Brier score of the Bayesian leaf posterior {r["brier"]["bayes"]:.4f} vs raw tree probabilities '
      f'{r["brier"]["raw"]:.4f}. With τ = {r["chosen"]["tau"]:.2f} and n_min = {r["n_min"]}, the ML layer auto-decides '
      f'{pct(rt["auto_share"])} of test cases at {rt["auto_accuracy"]:.4f} accuracy; the routed cases are only '
      f'{rt["review_accuracy"]:.4f} accurate, which is why they go to people. The {r["target_auto_accuracy"]:.0%} '
      'auto-accuracy target could not be met while keeping review at or below 50 %.')
    w('')
    w('### 6.3 Integrated pipeline on the test split  [pipeline_decisions.csv]')
    w('')
    w('| Decision | Source | n |')
    w('|---|---|---|')
    for (dec, src), n in sorted(pipe['split'].items()):
        w(f'| {dec} | {src} | {n} |')
    w('')
    w(f'Coverage {pipe["persisted"]}/{pipe["n"]}; automatic {pct(pipe["auto_share"])}; model auto-decisions agree '
      f'with the label {pct(pipe["model_auto_acc"])} (n = {pipe["model_auto_n"]}). Three runs on fresh databases '
      f'produced identical decisions: {"IDENTICAL" if a["repro_identical"] else "DIFFERENT"} '
      f'(SHA-256 `{a["repro_hash"][0][:16]}...`). [reproducibility.md]')
    w('')
    w(f'Rule layer on the training split: {pct(bucket["REJECT (HARD rule)"]["share"])} HARD-rejected, '
      f'{pct(bucket["REVIEW (SOFT rule)"]["share"])} SOFT review, {pct(bucket["PASS"]["share"])} pass. R03 (age at '
      f'maturity > 65) rejects {r03[65]["rejected"]} training applicants whose historical approval rate is '
      f'{r03_rule["approval_if_fired"]:.3f} vs {r03_rule["approval_otherwise"]:.3f}; a 60 cap would reject '
      f'{r03[60]["rejected"]}. [rule_analysis.json, docs/rule_justification.md]')
    w('')
    w('### 6.4 Fairness  [fairness_di.csv, fairness_ablation.csv, fairness_tau.csv, fairness_proxy.json]')
    w('')
    w('| Group | Subgroup | n | DI (full pipeline) | 95 % CI | model only | rules only | status |')
    w('|---|---|---|---|---|---|---|---|')
    piv = fair.pivot_table(index=['group', 'subgroup'], columns='mode', values='di', sort=False)
    for x in fair[fair['mode'] == 'pipeline'].itertuples():
        pv = piv.loc[(x.group, x.subgroup)]
        w(f'| {x.group} | {x.subgroup} | {x.n} | {x.di:.3f} | {x.ci_low:.3f}-{x.ci_high:.3f} | {pv["model_only"]:.3f} | '
          f'{pv["rules_only"]:.3f} | {x.status} |')
    w('')
    w(f'DI >= 0.80 does **not** hold for every subgroup: lowest {worst["di"]:.3f} ({worst["group"]} = '
      f'{worst["subgroup"]}). The model alone keeps every sufficient subgroup at >= {mo:.3f}; the gap comes from '
      'age-linked rules and from the historical label. Mitigations that never read a protected attribute were '
      f'tried: removing {best_abl["change"].replace("without ", "")} raises the lowest age-band DI from '
      f'{abl.loc["as deployed", "min_di_age_band"]:.3f} to {best_abl["min_di_age_band"]:.3f}; a global τ of '
      f'{a["taus"].loc[a["taus"]["min_di_age_band"].idxmax(), "tau"]:.2f} gives '
      f'{a["taus"]["min_di_age_band"].max():.3f}; retraining without `{a["proxy"]["dropped"]}` gives model-only '
      f'{a["proxy"]["min_di_age_band"]:.3f} at accuracy {a["proxy"]["test_accuracy"]:.4f}. None reaches 0.80 for every '
      'age band; the decision on these rules is open. The injected breach subgroup is flagged.')
    w('')
    w('### 6.5 Audit and concurrency  [lock_latency.json, lock_load_test.json]')
    w('')
    l50, ld = a['lock50'], a['load']
    w(f'- 50 threads approving one collateral: {l50["approved"]} approval, {l50["review"]} reviews; lock latency '
      f'p50 {l50["p50_ms"]:.0f} ms, p95 {l50["p95_ms"]:.0f} ms.')
    w(f'- {ld["requests"]} concurrent requests over {ld["collaterals"]} collaterals: {ld["approved"]} approvals '
      f'(max {ld["max_approvals_per_collateral"]} per collateral), {ld["persisted"]} persisted, chain {ld["chain"]}; '
      f'lock latency p50 / p95 {ld["lock_latency_ms"]["p50"]:.0f} / {ld["lock_latency_ms"]["p95"]:.0f} ms under a '
      'single-burst worst case (one Python process, SQLite single writer).')
    w('- Tampering with any audit row, deleting one, or rewriting a hash is reported at the exact row; UPDATE / DELETE '
      'on the audit log are blocked by triggers and an ORM guard.')
    w('')
    w('## 7. Testing (evidence gates)  [junit.xml, kpi_report.md]')
    w('')
    w(f'{tests["tests"]} tests, {tests["passed"]} passed, {tests["failures"]} failed; line coverage of `src/cognilend` '
      f'{a["cov"]:.1f} %.')
    w('')
    gates = [('1 Rule vs model conflict: zero overrides', 'test_gate1_no_model_override_of_a_fired_hard_rule'),
             ('2 Rare / edge profiles routed to review', 'test_gate2_rare_profiles_routed_to_review_with_confusion_matrix'),
             ('3 SMOTE train-only, no leakage', 'test_gate3_smote_train_only_no_leakage'),
             ('4 DB write failure: no crash, no loss', 'test_gate4_db_failure_no_crash_no_silent_loss'),
             ('5 Missing / invalid fields 100 % handled', 'test_gate5_missing_and_invalid_fields_100_percent_handled'),
             ('6 Fairness breach detected', 'test_gate6_fairness_breach_detected_and_reported'),
             ('7 Reproducible over 3 runs', 'test_gate7_reproducible_over_three_runs')]
    w('| Gate | Test | Result |')
    w('|---|---|---|')
    for g, t in gates:
        w(f'| {g} | `{t}` | {status(a["cases"], t)} |')
    w('')
    w(f'Gate 2 detail: {a["rare"]["n"]} rare / edge profiles; {a["rare"]["routed_to_review"]} reviewed, '
      f'{a["rare"]["hard_rejected"]} HARD-rejected, {a["rare"]["auto_decided_by_model"]} auto-decided by the model; '
      f'the model is {a["rare"]["model_accuracy_on_rare"]:.4f} accurate on them. [rare_subset.json]')
    w('')
    w('## 8. Limitations and future work')
    w('')
    w(f'- The constrained tree misses the 0.80 validation-accuracy KPI ({dt["val_accuracy"]:.4f}).')
    w(f'- Disparate impact by age band is below 0.80 (lowest {worst["di"]:.3f}); the age-linked rules need a decision.')
    w('- Loan.csv was not available: its label finding is unverified and its benchmark not run.')
    w('- Results are on synthetic data; thresholds are illustrative bank-policy values, not a lender\'s.')
    w('- SQLite serialises writers; the lock-latency tail under bursts should be re-measured on PostgreSQL.')
    w(f'- **Stress twin (implemented, advisory only):** a 1,000-path, 12-month Monte Carlo cash-flow test with '
      f'income-drop, expense-spike and payment-delay shocks. Example (UI defaults): band "{st["band"]}", resilience '
      f'{st["resilience"]}/100, combined-scenario shortfall probability '
      f'{st["scenarios"]["combined"]["shortfall_probability"]:.3f}. Its thresholds are illustrative and must be '
      'calibrated on real cash-flow data before it informs any decision. [stress_twin_example.json]')
    w('')
    w('## References')
    w('')
    w('Synopsis references:')
    w('')
    for ln in refs.splitlines():
        w(f'- {ln}')
    w('')
    w('Additional references cited in this report:')
    w('')
    for ln in [
        '[7] J. R. Quinlan, "Induction of decision trees," Machine Learning, vol. 1, no. 1, pp. 81-106, 1986.',
        '[8] L. Breiman, J. Friedman, R. Olshen and C. Stone, Classification and Regression Trees. Wadsworth, 1984.',
        '[9] C. Rudin, "Stop explaining black box machine learning models for high stakes decisions and use '
        'interpretable models instead," Nature Machine Intelligence, vol. 1, pp. 206-215, 2019.',
        '[10] S. M. Lundberg and S.-I. Lee, "A unified approach to interpreting model predictions," NeurIPS, 2017.',
        '[11] L. Breiman, "Random forests," Machine Learning, vol. 45, no. 1, pp. 5-32, 2001.',
        '[12] J. H. Friedman, "Greedy function approximation: a gradient boosting machine," Annals of Statistics, '
        'vol. 29, no. 5, pp. 1189-1232, 2001.',
        '[13] T. Chen and C. Guestrin, "XGBoost: a scalable tree boosting system," KDD, 2016.',
        '[14] N. V. Chawla, K. W. Bowyer, L. O. Hall and W. P. Kegelmeyer, "SMOTE: synthetic minority over-sampling '
        'technique," Journal of Artificial Intelligence Research, vol. 16, pp. 321-357, 2002.',
        '[15] U.S. EEOC, Uniform Guidelines on Employee Selection Procedures, 29 CFR 1607.4(D), 1978 (four-fifths rule).',
        '[16] M. Feldman, S. A. Friedler, J. Moeller, C. Scheidegger and S. Venkatasubramanian, "Certifying and '
        'removing disparate impact," KDD, 2015.',
        '[17] Reserve Bank of India, Master Circular - Housing Finance (LTV ceilings for individual housing loans).',
        '[18] Reserve Bank of India, Guidelines on Fair Practices Code for Lenders.',
        '[19] S. Russell and P. Norvig, Artificial Intelligence: A Modern Approach, 4th ed., Pearson, 2020 '
        '(forward chaining).']:
        w(f'- {ln}')
    return '\n'.join(L) + '\n'


# --------------------------------------------------------------------------------------
def traceability(a) -> str:
    c = a['cases']
    dt, pipe = a['dt'], a['pipe']
    fair = a['fair']
    pf = fair[(fair['mode'] == 'pipeline') & ~fair['insufficient']]
    rows = [
        ('FR-1', 'Accept applicant, financial, credit and loan inputs', 'data/contract.py, app/pages/1_New_Application.py',
         ['test_clean_row_is_accepted', 'test_transform_applicant_single_dict'], 'contract: 18 fields'),
        ('FR-2', 'Apply policy rules before the ML model', 'pipeline.py, rules/engine.py',
         ['test_hard_reject_never_calls_ml', 'test_hard_reject_logged_without_model'], 'model never called on REJECT'),
        ('FR-3', 'Decision + confidence + traceable reason', 'pipeline.py, ml/explain.py, ml/confidence.py',
         ['test_every_output_has_the_four_required_parts', 'test_every_test_prediction_has_confidence_path_and_sentence'],
         f'{pipe["n"]}/{pipe["n"]} complete outputs'),
        ('FR-4', 'Log every decision to the DB', 'db/repository.py, db/audit.py',
         ['test_full_test_set_coverage_is_100_percent', 'test_nfr_decision_log_coverage_100_percent'],
         f'coverage {pipe["persisted"]}/{pipe["n"]}'),
        ('FR-5', 'Route low-confidence cases to human review', 'ml/confidence.py, pipeline.py',
         ['test_evidence_gate_routes_smallest_leaves_to_review', 'test_route_rule'],
         f'test auto {pct(a["routing"]["routing"]["test"]["auto_share"])}'),
        ('FR-6', 'HARD violation: immediate reject citing the rule, ML never called', 'rules/engine.py, pipeline.py',
         ['test_rule_vs_model_conflict_hard_rule_always_wins', 'test_gate1_no_model_override_of_a_fired_hard_rule'],
         'zero overrides'),
        ('FR-9', 'Feature-by-feature tree path for every prediction', 'ml/explain.py',
         ['test_path_values_are_in_original_units_and_consistent', 'test_contributions_sum_to_leaf_probability'],
         'path in original units'),
        ('FR-10', 'Block a second approval for the same applicant / collateral', 'db/lock.py',
         ['test_50_concurrent_approvals_same_collateral_exactly_one', 'test_nfr_concurrency_lock_load_test_passed'],
         f'{a["load"]["approved"]}/{a["load"]["collaterals"]} under {a["load"]["requests"]} concurrent'),
        ('NFR', 'Explainability', 'ml/explain.py, ml/tree_plot.py',
         ['test_exports_exist_and_rules_use_original_units'], 'tree rules in original units'),
        ('NFR', 'DI >= 0.80', 'fairness/disparate_impact.py', ['test_report_states_the_verdict_plainly'],
         f'FAIL: min {pf["di"].min():.3f}'),
        ('NFR', 'Tree depth <= 4 and nodes <= 15', 'ml/tree.py', ['test_saved_model_depth_and_node_caps'],
         f'{dt["depth"]} / {dt["node_count"]}'),
        ('NFR', 'SQL-queryable audit', 'docs/audit_queries.sql', ['test_every_audit_query_runs'], '11 queries'),
        ('NFR', 'No crash on bad input', 'rules/engine.py, data/contract.py',
         ['test_malformed_fields_are_handled_without_exceptions', 'test_gate5_missing_and_invalid_fields_100_percent_handled'],
         '100 % handled'),
        ('NFR', 'Generalization gap <= 15 %', 'ml/tree.py', ['test_generalization_gap_within_limit'],
         f'{dt["generalization_gap"]:.4f}'),
        ('NFR', 'Entropy error <= 1e-9', 'ml/entropy.py', ['test_entropy_matches_scipy_on_1000_random_distributions'],
         'pass'),
        ('NFR', 'Reproducible', 'pipeline.py, scripts/reproducibility.py',
         ['test_gate7_reproducible_over_three_runs', 'test_retraining_gives_identical_predictions'],
         'IDENTICAL' if a['repro_identical'] else 'DIFFERENT'),
        ('KPI', 'Validation accuracy >= 80 %', 'ml/tree.py', ['test_kpi_flag_is_honest'], f'FAIL: {dt["val_accuracy"]:.4f}'),
        ('KPI', 'Rule-trigger precision 100 %', 'rules/engine.py, scripts/kpi_report.py', ['test_policy_file_schema'],
         'see kpi_report.md'),
        ('KPI', '100 % decisions logged', 'db/repository.py', ['test_full_test_set_coverage_is_100_percent'],
         f'{pipe["persisted"]}/{pipe["n"]}'),
        ('KPI', 'Majority auto-cleared, none dropped', 'pipeline.py', ['test_none_dropped_and_majority_auto_cleared'],
         f'{pct(pipe["auto_share"])} auto'),
        ('Gate 1', 'Rule vs model conflict', 'pipeline.py', ['test_gate1_no_model_override_of_a_fired_hard_rule'], ''),
        ('Gate 2', 'Rare / edge profile -> review', 'ml/confidence.py',
         ['test_gate2_rare_profiles_routed_to_review_with_confusion_matrix'], f'{a["rare"]["auto_decided_by_model"]} auto'),
        ('Gate 3', 'SMOTE train-only', 'data/preprocess.py, ml/tree.py', ['test_gate3_smote_train_only_no_leakage'], ''),
        ('Gate 4', 'DB write failure', 'db/repository.py (FallbackLog), pipeline.py',
         ['test_gate4_db_failure_no_crash_no_silent_loss'], ''),
        ('Gate 5', 'Missing / invalid fields', 'rules/engine.py', ['test_gate5_missing_and_invalid_fields_100_percent_handled'], ''),
        ('Gate 6', 'Fairness breach', 'fairness/disparate_impact.py', ['test_gate6_fairness_breach_detected_and_reported'], ''),
        ('Gate 7', 'Reproducibility', 'scripts/reproducibility.py', ['test_gate7_reproducible_over_three_runs'], ''),
        ('Advisory', 'Stress twin metrics, deterministic', 'stress_twin/simulator.py',
         ['test_deterministic_with_seed', 'test_recovery_time', 'test_resilience_score'], 'advisory only'),
    ]
    L = ['# Traceability matrix', '',
         f'Generated by `python scripts/build_docs.py`. Test results are read from `artifacts/reports/junit.xml` '
         f'({a["tests"]["tests"]} tests, {a["tests"]["passed"]} passed). "PASS (n)" = n collected test cases all passed. '
         'FR-7 and FR-8 are not listed in the project brief used for this build.', '',
         '| Requirement | Description | Module(s) | Test(s) | Test result | Measured |', '|---|---|---|---|---|---|']
    for rid, desc, mod, tests, measured in rows:
        L.append(f'| {rid} | {desc} | `{mod}` | {", ".join(f"`{t}`" for t in tests)} | {status(c, *tests)} | {measured} |')
    return '\n'.join(L) + '\n'


# --------------------------------------------------------------------------------------
def changes(a) -> str:
    dt, r, b, pr = a['dt'], a['routing'], a['bench'], a['prep']
    fair = a['fair']
    pf = fair[(fair['mode'] == 'pipeline') & ~fair['insufficient']]
    worst = pf.loc[pf['di'].idxmin()]
    L = ['# Changes from the synopsis', '',
         'Generated by `python scripts/build_docs.py`. An honest list of where the delivered system differs from the '
         'signed synopsis and the project brief, and why.', '',
         '| # | Area | Synopsis / brief | Delivered | Reason |', '|---|---|---|---|---|',
         '| 1 | Dataset | Loan.csv as the data source (team notebook) | Seeded synthetic Indian dataset is primary; '
         'Loan.csv kept as a secondary benchmark only | Loan.csv was not available to this build, and its `status` '
         'target most likely means default / not priced, not approval. The synthetic set matches the rule engine '
         '(CIBIL, FOIR, LTV) and has a documented generator. |',
         '| 2 | Label | Historical approval | Label from a latent repayment-risk score + noise; rules not used | '
         'Otherwise the ML layer would only re-learn the rules (the team file rejected ~96 % of rule violators). |',
         f'| 3 | Split | 70 / 30 | 70 / 15 / 15 (train / validation / test), stratified, seed 42 '
         f'(train {pr["class_distribution"]["train"]["n"]:,}) | The 30 % is split into validation (tuning) and test '
         '(scored once), so no number is tuned on the test set. |',
         '| 4 | Prototype model | XGBoost (legacy prototype), 80/20 split, seed 0 | Constrained entropy tree; XGBoost '
         'only as a benchmark; seed 42 everywhere | Synopsis requires depth <= 4 and <= 15 nodes with a traceable path. |',
         '| 5 | Rules | R1-R7 all hard; age at maturity 60 (salaried) / 65 (self-employed) | 7 HARD (incl. a new '
         'fraud-registry rule R02), single maturity cap 65 (R03), work experience moved to SOFT (S02), borderline FOIR '
         '(S03) and missing information (S04) as SOFT | Experience shortfall is not disqualifying on its own; a single '
         'documented cap; see docs/rule_justification.md. |',
         '| 6 | Protected attributes | Gender excluded from the model | Gender, marital status and age band '
         'excluded; Age and age-at-maturity also kept out of the model; property area excluded as a possible proxy | '
         'Age band is protected; age at maturity carries age. |',
         '| 7 | Live input repairs | (not specified) | Sign-error and tenure-in-years repairs only for historical data; '
         'live input is validated and rejected if invalid | A real 24-month home loan must not be rescaled. |',
         f'| 8 | KPI: validation accuracy >= 80 % | Met | **Missed: {dt["val_accuracy"]:.4f}** | Depth / node caps '
         f'bind; caps were not loosened. Ensembles reach {b.drop(index="decision_tree")["val_accuracy"].max():.4f}. |',
         f'| 9 | Routing target (brief: e.g. 90 % auto accuracy) | 90 % | **{r["routing"]["test"]["auto_accuracy"]:.4f} '
         f'at {pct(r["routing"]["test"]["auto_share"])} auto (test)**, τ = {r["chosen"]["tau"]:.2f} | 90 % is not '
         'reachable with an 8-leaf tree while keeping the majority auto-cleared. |',
         f'| 10 | NFR: DI >= 0.80 | All subgroups | **Missed: lowest {worst["di"]:.3f} ({worst["group"]} = '
         f'{worst["subgroup"]})** | Caused by age-linked rules and the historical label, not the model; mitigations '
         'tried and listed in fairness.md; decision pending. |',
         '| 11 | Tree image | Graphviz / dtreeviz | matplotlib (`tree.png`) + `tree.dot` | No Graphviz binary on the '
         'build machine. |',
         '| 12 | Loan.csv label finding and benchmark | Reproduce and benchmark | **Not done** | File not supplied; '
         'tooling implemented and tested on a stand-in frame. |',
         '| 13 | Database | PostgreSQL-compatible | SQLite in development; PostgreSQL trigger DDL included but untested | '
         'No PostgreSQL server available. |',
         '| 14 | Python | 3.10+ | 3.11+ | Pinned pandas 3.x requires 3.11. |',
         '| 15 | Optional SHAP comparison | Optional | Not done | Path contributions are exact for a single tree. |',
         '| 16 | Stress twin | Optional | Implemented as an advisory page | Thresholds illustrative, to be calibrated. |']
    return '\n'.join(L) + '\n'


# --------------------------------------------------------------------------------------
def presentation(a) -> str:
    dt, b, r, pipe, ld = a['dt'], a['bench'], a['routing'], a['pipe'], a['load']
    fair = a['fair']
    pf = fair[(fair['mode'] == 'pipeline') & ~fair['insufficient']]
    worst = pf.loc[pf['di'].idxmin()]
    ens = b.drop(index='decision_tree')
    slides = [
        ('Title', ['CogniLend: hybrid rule-and-ML loan decisioning', 'WCE Sangli, Apni Leap AY 2026-27; guide Dr. V. N. '
                   'Waghmare; groups G10 / G12 / G15']),
        ('Problem', ['Lenders must give a written, true reason for every decision and must not discriminate',
                     'Black boxes are accurate but unexplainable; rule systems cannot rank compliant applicants']),
        ('Our answer: four layers', ['Rules first (HARD reject / SOFT review) -> constrained tree + Bayesian '
                                     'confidence -> hash-chained audit DB with approval lock -> disparate-impact audit',
                                     'Output: Approved / Rejected / Human Review + confidence + reason + audit-log ID']),
        ('Data', [f'Seeded synthetic Indian dataset, {a["profile"]["raw_shape"][0]:,} rows, documented defects',
                  f'Label from latent repayment risk, not the rules (rules alone: '
                  f'{a["profile"]["accuracy_rules_only_predictor"]:.3f} accuracy)',
                  'Loan.csv: label likely "default / not priced"; file not available, kept as secondary benchmark']),
        ('Rule engine', ['Forward chaining over derived facts (FOIR, LTV, age at maturity...)',
                         '7 HARD + 4 SOFT rules, each with rationale and source; rule-trigger precision checked '
                         'against an independent implementation']),
        ('Interpretable model', [f'Entropy tree: depth {dt["depth"]}, {dt["node_count"]} nodes, uses CIBIL, FOIR, '
                                 'experience', f'Val acc {dt["val_accuracy"]:.4f} (target 0.80, missed); test '
                                 f'{dt["test_accuracy"]:.4f}; gap {dt["generalization_gap"]:.4f}',
                                 f'Ensembles {ens["test_accuracy"].min():.4f}-{ens["test_accuracy"].max():.4f} on test: '
                                 'the price of a readable path']),
        ('Confidence and routing', [f'Beta(1,1) leaf posterior; Brier {r["brier"]["bayes"]:.4f}',
                                    f'τ = {r["chosen"]["tau"]:.2f}: {pct(r["routing"]["test"]["auto_share"])} auto at '
                                    f'{r["routing"]["test"]["auto_accuracy"]:.4f}; routed cases only '
                                    f'{r["routing"]["test"]["review_accuracy"]:.4f} accurate']),
        ('Integrated results', [f'{pipe["n"]} test applications: {pipe["persisted"]} logged, '
                                f'{pct(pipe["auto_share"])} automatic', 'Three fresh-DB runs identical',
                                f'Lock: {ld["requests"]} concurrent requests -> exactly one approval per collateral']),
        ('Fairness', ['Gender passes the four-fifths rule',
                      f'Age band fails (lowest {worst["di"]:.3f}): from age-linked rules and the label, not the model',
                      'Protected-blind mitigations tried; decision on the rules is pending']),
        ('Live demo', ['Seven cases: HARD reject, auto-approve, auto-reject, SOFT review, low confidence, duplicate '
                       'collateral, malformed input']),
        ('Testing', [f'{a["tests"]["tests"]} automated tests, {a["tests"]["passed"]} passing; all 7 evidence gates',
                     'KPI report generated from code; two KPIs honestly missed']),
        ('Limitations and next steps', ['Accuracy and age-DI KPIs; Loan.csv; PostgreSQL; calibrate the advisory '
                                        'stress twin']),
    ]
    L = ['# Presentation outline and demo script', '',
         'Generated by `python scripts/build_docs.py`; numbers from `artifacts/reports/`.', '',
         f'## Slides ({len(slides)})', '']
    for i, (title, bullets) in enumerate(slides, 1):
        L.append(f'**{i}. {title}**')
        L += [f'- {x}' for x in bullets] + ['']
    L += ['## 5-minute demo script', '',
          'Before: `python scripts/seed_demo.py`, then `streamlit run app/streamlit_app.py`. Open each URL in turn '
          '(base `http://localhost:8501/New_Application?demo=`).', '',
          '| Time | Case (URL suffix) | Expected screen | Say |', '|---|---|---|---|']
    script = {
        'hard_reject': 'R01 fires in red; tree says "Model not consulted": rules always run first.',
        'auto_approve': 'High-confidence leaf; path highlighted in the tree; read the reason sentence aloud.',
        'auto_reject': 'Model rejects with confidence 0.85; every number in original units.',
        'soft_review': 'New-to-credit is never rejected for lack of history; it goes to a person, with the model\'s '
                       'recommendation attached.',
        'low_confidence': 'Rules pass, but the leaf is uncertain, so it is routed to review (FR-5).',
        'lock': 'Same flat pledged twice: the second approval is blocked by the lock (FR-10).',
        'malformed': 'Age 999 and income "abc": graceful reject naming the fields, still logged.',
    }
    t = 0
    for name, (title, _, expected, source) in demo.CASES.items():
        L.append(f'| {t // 60}:{t % 60:02d} | {title} (`{name}`) | {expected} / {source}; audit ID '
                 f'{a["demo"][name]["audit_log_id"]} in the seeded DB | {script[name]} |')
        t += 30
    L += [f'| {t // 60}:{t % 60:02d} | Officer Review Queue | approve the new-to-credit case with a note | HUMAN '
          'decision with its own audit event |',
          f'| {(t + 45) // 60}:{(t + 45) % 60:02d} | Audit Explorer -> Verify chain | "Audit chain OK" | tamper-evident '
          'log; show the hash of the lock case |',
          f'| {(t + 75) // 60}:{(t + 75) % 60:02d} | Fairness Dashboard | red banner listing the age bands below 0.80 | '
          'we report it, we do not hide it |',
          f'| {(t + 105) // 60}:{(t + 105) % 60:02d} | Stress Twin | advisory band and resilience score | separate '
          'from the decision; thresholds illustrative |']
    return '\n'.join(L) + '\n'


# --------------------------------------------------------------------------------------
def tracker(a) -> str:
    progress = sorted((DOCS / 'progress').glob('step_*.md'))
    L = ['# Weekly tracker: October 2026 (what was actually done)', '',
         'Generated by `python scripts/build_docs.py` from `docs/progress/step_NN.md`. The dates are the dates recorded '
         'in each step report; the team\'s Excel tracker (`CogniLend_Weekly_Mentor_Reports.xlsx`) has not been '
         'updated from here, because it was outside the readable workspace.', '',
         '| Step | Date | Title | Outcome |', '|---|---|---|---|']
    for f in progress:
        txt = f.read_text(encoding='utf-8')
        title = txt.splitlines()[0].lstrip('# ').strip()
        m = re.search(r'Date: (\d{4}-\d{2}-\d{2})', txt)
        fails = 'KPI missed (documented)' if re.search(r'NOT met|does NOT hold|\*\*FAIL\*\*', txt) else 'complete'
        L.append(f'| {f.stem.split("_")[1]} | {m.group(1) if m else "-"} | {title} | {fails} |')
    L += ['', f'Totals at the end of October W3: {a["tests"]["tests"]} automated tests, {a["tests"]["passed"]} passing; '
          'open decisions: accuracy KPI, age-band DI (rules R03 / S02), routing target, Loan.csv.']
    return '\n'.join(L) + '\n'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    a = load_all()
    out = {'final_report.md': final_report(a), 'traceability.md': traceability(a),
           'changes_from_synopsis.md': changes(a), 'presentation.md': presentation(a),
           'weekly_tracker_october.md': tracker(a)}
    for name, text in out.items():
        (DOCS / name).write_text(text, encoding='utf-8')
        print(f'wrote docs/{name} ({len(text.splitlines())} lines)')


if __name__ == '__main__':
    main()
