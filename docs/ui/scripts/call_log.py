"""Drive a UI headlessly (streamlit AppTest) and log every backend call it makes, with its arguments and result.

    python docs/ui/scripts/call_log.py <app_dir> <old|new> <out.json>

<app_dir> is an app/ folder: the old UI (extracted from git main) or the new one. The same user stories run on
both; only the way the widgets are found differs (the old form is found by label, the new one by key). The log
records, per story, the exact arguments passed to the backend (decide, complete_review, verify_chain,
decision_history, find_max_approvable_amount, disparate_impact.run, simulate, ...) and the values the UI got
back (decision, confidence, reason, fired rules, audit id, max-amount result). compare_calls.py diffs two logs.

Writes go to the real project DB, so run old and new against the SAME DB snapshot (compare_calls.py does that)
to get identical audit ids. complete_review and disparate_impact.run are intercepted (args logged, a fixed
result returned) so the stories do not close real review cases or rewrite the fairness tables.
"""
import copy
import json
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

from cognilend import demo
from cognilend.max_amount import search as max_amount
from cognilend.db.repository import Repository
from cognilend.fairness import disparate_impact
from cognilend.pipeline import DecisionPipeline
from cognilend.stress_twin import simulator

LOG: list = []
FOIR_JSON = {**demo.clean({**demo.BASE, 'Monthly_Income': 60000, 'Loan_Amount': 6_000_000,
                           'Collateral_Value': 9_000_000}), 'Loan_ID': 'LOG-FOIR', 'Applicant_ID': 'LOG-A1'}
RESULT_KEYS = ('decision', 'confidence', 'confidence_ci', 'reason', 'source', 'fired_rules', 'audit_log_id',
               'loan_id', 'applicant_id', 'model_version', 'policy_version', 'leaf', 'leaf_support', 'invalid_fields')


def _j(x):
    return json.loads(json.dumps(x, default=str))


def install_spies():
    orig_decide = DecisionPipeline.decide

    def decide(self, application, batch_id=None):
        out = orig_decide(self, application, batch_id)
        if self.repo is not None:                               # persisting calls only (dry runs are internal)
            LOG.append({'call': 'decide', 'args': _j(copy.deepcopy(application)), 'batch_id': batch_id,
                        'result': _j({k: out.get(k) for k in RESULT_KEYS})})
        return out
    DecisionPipeline.decide = decide

    def complete_review(self, review_id, officer, outcome, notes=''):
        LOG.append({'call': 'complete_review', 'args': [review_id, officer, outcome, notes]})
        return {'ok': True, 'decision_id': 0, 'audit_log_id': 0}
    DecisionPipeline.complete_review = complete_review

    for name in ('verify_chain', 'decision_history', 'list_reviews', 'summary', 'versions', 'fairness_runs',
                 'audit_event', 'fairness_rows'):
        orig = getattr(Repository, name)

        def spy(self, *a, _orig=orig, _name=name, **k):
            out = _orig(self, *a, **k)
            entry = {'call': _name, 'args': _j(list(a)), 'kwargs': _j(k)}
            if _name == 'verify_chain':
                entry['result'] = {'ok': out.ok, 'checked': out.checked, 'first_broken_seq': out.first_broken_seq}
            LOG.append(entry)
            return out
        setattr(Repository, name, spy)

    orig_max = max_amount.find_max_approvable_amount

    def find_max(application, *a, **k):
        out = orig_max(application, *a, **k)
        LOG.append({'call': 'find_max_approvable_amount', 'args': _j(application),
                    'result': _j({k2: v for k2, v in out.items() if k2 != 'runtime_ms'})})
        return out
    max_amount.find_max_approvable_amount = find_max

    def fair_run():
        LOG.append({'call': 'disparate_impact.run', 'args': []})
        return {}
    disparate_impact.run = fair_run

    orig_sim = simulator.simulate

    def simulate(inp, *a, **k):
        if not a and not k:                                     # the page's own call (alternatives() adds kwargs)
            LOG.append({'call': 'simulate', 'args': _j(inp.__dict__)})
        return orig_sim(inp, *a, **k)
    simulator.simulate = simulate


# new page file (app/views/) -> old page file (app/pages/ in git main), so both UIs can be driven by one name
OLD_PAGE = {'new_application.py': '1_New_Application.py', 'review_queue.py': '2_Officer_Review_Queue.py',
            'audit_explorer.py': '3_Audit_Explorer.py', 'model_and_policy.py': '4_Model_and_Policy.py',
            'fairness.py': '5_Fairness_Dashboard.py', 'stress_twin.py': '6_Stress_Twin.py',
            'model_comparison.py': '7_Model_Comparison.py'}


def page(app_dir: Path, name: str, **qp) -> AppTest:
    path = app_dir / 'views' / name
    if not path.exists():                      # old UI layout (git main): app/pages/<n>_<Name>.py
        path = app_dir / 'pages' / OLD_PAGE[name]
    at = AppTest.from_file(str(path), default_timeout=300)
    for k, v in qp.items():
        at.query_params[k] = v
    return at.run()


def button(at, label):
    return next(b for b in at.button if b.label == label)


def by_label(widgets, label):
    return next(w for w in widgets if w.label == label)


def fill_old_form(at, app: dict):
    """Old UI: type the application into the original single form, found by widget label."""
    t = {w.label: w for w in at.text_input}
    t['Loan ID (optional)'].input(app.get('Loan_ID', ''))
    t['Applicant ID, e.g. PAN (optional)'].input(app.get('Applicant_ID', ''))
    t['Collateral ID (optional, secured loans)'].input(app.get('Collateral_ID', ''))
    n = {w.label: w for w in at.number_input}
    s = {w.label: w for w in at.selectbox}
    n['Age (years)'].set_value(app['Age'])
    s['Gender (audit only, not used to decide)'].set_value(app.get('Gender', ''))
    s['Marital status (audit only)'].set_value(app.get('Marital_Status', ''))
    s['Dependents'].set_value(app['Dependents'])
    s['Employment type'].set_value(app['Employment_Type'])
    n['Work experience / business vintage (years)'].set_value(app['Work_Experience'])
    n['Monthly income (₹)'].set_value(app['Monthly_Income'])
    n['Co-applicant income (₹/month, 0 = none)'].set_value(app.get('Coapplicant_Income', 0))
    n['Existing EMIs (₹/month)'].set_value(app['Existing_EMI'])
    at.checkbox[0].set_value(app['CIBIL_Score'] == -1)
    if app['CIBIL_Score'] != -1:
        n['CIBIL score'].set_value(app['CIBIL_Score'])
    s['Property area'].set_value(app['Property_Area'])
    s['Loan type'].set_value(app['Loan_Type'])
    n['Loan amount (₹)'].set_value(app['Loan_Amount'])
    n['Tenure (months)'].set_value(app['Loan_Tenure'])
    n['Collateral value (₹, 0 = unsecured)'].set_value(app.get('Collateral_Value') or 0)
    button(at, 'Submit application').click().run()


def fill_new_form(at, app: dict):
    """New UI: load the same application with the 'Load a demo applicant' picker (step form), then submit."""
    name = next(n for n, c in demo.CASES.items() if demo.clean(c[1][-1]) == app)
    picker = next(w for w in at.button_group if w.key == 'cl_demo_pick')
    picker.set_value(name).run()
    assert not at.exception, [e.value for e in at.exception]
    button(at, 'Submit application').click().run()


def form_story(at, mode, app):
    (fill_old_form if mode == 'old' else fill_new_form)(at, app)


def main():
    app_dir, mode, out = Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3])
    sys.path.insert(0, str(app_dir))
    install_spies()
    stories = {}

    def story(name, fn):
        LOG.clear()
        try:
            fn()
            stories[name] = {'ok': True, 'calls': copy.deepcopy(LOG)}
        except Exception as e:  # noqa: BLE001 - record and continue with the next story
            stories[name] = {'ok': False, 'error': f'{type(e).__name__}: {e}', 'calls': copy.deepcopy(LOG)}
        print(name, 'ok' if stories[name]['ok'] else stories[name]['error'], flush=True)

    for name in demo.CASES:                                    # ?demo= deep links
        def run_demo(name=name):
            at = page(app_dir, 'new_application.py', demo=name)
            assert not at.exception, [e.value for e in at.exception]
            if at.session_state['result']['decision'] == 'Rejected':
                button(at, 'See maximum approvable amount').click().run()
                assert not at.exception, [e.value for e in at.exception]
        story(f'demo_{name}', run_demo)

    def form_default():
        at = page(app_dir, 'new_application.py')
        if mode == 'old':
            button(at, 'Submit application').click().run()
        else:
            new_submit(at)
        assert not at.exception, [e.value for e in at.exception]
    story('form_defaults', form_default)

    for name in ('hard_reject', 'auto_approve', 'auto_reject', 'soft_review', 'low_confidence', 'lock'):
        def run_form(name=name):
            at = page(app_dir, 'new_application.py')
            form_story(at, mode, demo.clean(demo.CASES[name][1][-1]))
            assert not at.exception, [e.value for e in at.exception]
        story(f'form_{name}', run_form)

    def json_possible():
        at = page(app_dir, 'new_application.py')
        at.text_area[0].input(json.dumps(FOIR_JSON))
        button(at, 'Submit JSON').click().run()
        button(at, 'See maximum approvable amount').click().run()
        assert not at.exception, [e.value for e in at.exception]
    story('json_max_amount_possible', json_possible)

    def json_malformed():
        at = page(app_dir, 'new_application.py')
        button(at, 'Submit JSON').click().run()                # the default JSON is the malformed demo
        assert not at.exception, [e.value for e in at.exception]
    story('json_default_malformed', json_malformed)

    def officer():
        at = page(app_dir, 'review_queue.py')
        at.text_area[0].input('call-log note')
        at.radio[0].set_value('Rejected')
        at.button[0].click().run()
        assert not at.exception, [e.value for e in at.exception]
    story('officer_record_decision', officer)

    def audit():
        at = page(app_dir, 'audit_explorer.py')
        button(at, 'Verify chain').click().run()
        assert not at.exception, [e.value for e in at.exception]
    story('audit_verify_chain', audit)

    def fairness():
        at = page(app_dir, 'fairness.py')
        button(at, 'Rerun fairness audit').click().run()
        assert not at.exception, [e.value for e in at.exception]
    story('fairness_rerun', fairness)

    def stress():
        at = page(app_dir, 'stress_twin.py')
        assert not at.exception, [e.value for e in at.exception]
    story('stress_twin_default', stress)

    for p in ('model_and_policy.py', 'model_comparison.py'):
        def render(p=p):
            at = page(app_dir, p)
            assert not at.exception, [e.value for e in at.exception]
        story(f'render_{p[:-3]}', render)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stories, indent=1, default=str), encoding='utf-8')
    print('->', out)


def new_submit(at):
    button(at, 'Submit application').click().run()


if __name__ == '__main__':
    main()
