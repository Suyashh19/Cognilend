"""Rebuild everything from a fresh clone, in dependency order, then run the tests.

    python scripts/run_all.py            # all steps (~10 min)
    python scripts/run_all.py --no-tests

Every artefact in artifacts/ and data/processed/ is produced by one of these steps.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
STEPS = [
    ('synthetic dataset (verify committed file)', [PY, '-m', 'cognilend.data.synthetic']),
    ('preprocessing (split, fit on train, save)', [PY, '-m', 'cognilend.data.preprocess']),
    ('constrained decision tree', [PY, '-m', 'cognilend.ml.tree']),
    ('benchmark vs ensembles', [PY, '-m', 'cognilend.ml.benchmark']),
    ('Bayesian confidence + routing', [PY, '-m', 'cognilend.ml.confidence']),
    ('explanations + contribution shift', [PY, '-m', 'cognilend.ml.explain']),
    ('rule threshold analysis', [PY, 'scripts/rule_analysis.py']),
    ('seed DB: test split, fairness audit, demo cases', [PY, 'scripts/seed_demo.py']),
    ('reproducibility (3 fresh-DB runs)', [PY, 'scripts/reproducibility.py']),
    ('lock load test (500 concurrent)', [PY, 'scripts/lock_load_test.py']),
    ('dataset profile', [PY, 'scripts/describe_synthetic.py']),
]


def main():
    steps = list(STEPS)
    if '--no-tests' not in sys.argv:
        steps.append(('test suite + KPI report', [PY, 'scripts/kpi_report.py']))
    t_all = time.perf_counter()
    for i, (name, cmd) in enumerate(steps, 1):
        t0 = time.perf_counter()
        print(f'[{i}/{len(steps)}] {name} ...', flush=True)
        r = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                           encoding='utf-8', errors='replace')
        if r.returncode != 0:
            print(r.stderr[-3000:])
            raise SystemExit(f'FAILED at step {i}: {name}')
        print(f'      done in {time.perf_counter() - t0:.0f} s', flush=True)
    print(f'All {len(steps)} steps passed in {(time.perf_counter() - t_all) / 60:.1f} min. '
          'Start the app with: streamlit run app/streamlit_app.py')


if __name__ == '__main__':
    main()
