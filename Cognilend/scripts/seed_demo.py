"""Create a fresh, seeded database for the app, then run the demo cases.

    python scripts/seed_demo.py
    streamlit run app/streamlit_app.py

1. fresh data/processed/cognilend.db with the full test split decided (batch test-eval)  [evaluate_pipeline]
2. fairness audit stored in fairness_reports                                              [disparate_impact]
3. the seven demo cases (batch demo); results -> artifacts/reports/demo_cases.json, expected vs actual checked
"""
import importlib.util
import json
import sys

from cognilend import config, demo
from cognilend.fairness import disparate_impact
from cognilend.pipeline import DecisionPipeline


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    spec = importlib.util.spec_from_file_location('evaluate_pipeline', config.ROOT / 'scripts' / 'evaluate_pipeline.py')
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    ev.main()
    disparate_impact.run()
    p = DecisionPipeline()
    results, ok = {}, True
    for name, (title, _, expected, source) in demo.CASES.items():
        d = demo.run_case(p, name)
        match = (d['decision'], d['source']) == (expected, source)
        ok &= match
        results[name] = {'title': title, 'expected': [expected, source], 'actual': [d['decision'], d['source']],
                         'match': match, 'loan_id': d['loan_id'], 'audit_log_id': d['audit_log_id'],
                         'reason': d['reason']}
        print(f'{"OK " if match else "BAD"} {name:15s} {d["decision"]:13s} {d["source"]:6s} audit {d["audit_log_id"]}')
    out = config.ROOT / config.load('settings')['paths']['reports'] / 'demo_cases.json'
    out.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print('chain:', p.repo.verify_chain())
    if not ok:
        raise SystemExit('a demo case did not produce its expected decision')


if __name__ == '__main__':
    main()
