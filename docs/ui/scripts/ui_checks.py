"""Behaviour checks of the new UI (headless, streamlit AppTest). Writes a PASS/FAIL markdown table.

    python docs/ui/scripts/ui_checks.py <out.md>

U3  live preview values == the rule engine's facts (engine.evaluate) for every demo applicant
U3  "Load demo applicant" -> the dict sent to decide() == demo.clean(<case application>)  (6 form-capable cases)
U3  double submit: a second identical click within 5 s does not call decide() again
U4  max amount: "Fill the form with ₹X" pre-fills the form amount and the JSON tab, and does NOT call decide()
U4  feature flag off -> no "See maximum approvable amount" button on any Rejected demo
U4  "Start a new application" (?new=1) clears the result and resets the form to the original defaults
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'app'))

from streamlit.testing.v1 import AppTest  # noqa: E402

from cognilend import demo  # noqa: E402
from cognilend.pipeline import DecisionPipeline  # noqa: E402
from cognilend.rules import engine  # noqa: E402

PAGE = str(ROOT / 'app' / 'pages' / '1_New_Application.py')
CALLS = []
_orig = DecisionPipeline.decide


def _spy(self, application, batch_id=None):
    if self.repo is not None:
        CALLS.append(json.loads(json.dumps(application, default=str)))
    return _orig(self, application, batch_id)


DecisionPipeline.decide = _spy
RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append((name, bool(ok), detail))
    print('PASS' if ok else 'FAIL', name, detail, flush=True)


def fresh(**qp):
    at = AppTest.from_file(PAGE, default_timeout=300)
    for k, v in qp.items():
        at.query_params[k] = v
    return at.run()


def button(at, label_start):
    return next(b for b in at.button if b.label.startswith(label_start))


def load(at, name):
    next(w for w in at.button_group if w.key == 'cl_demo_pick').set_value(name).run()


FORM_CASES = ['hard_reject', 'auto_approve', 'auto_reject', 'soft_review', 'low_confidence', 'lock']

# --- U3: demo loader -> identical dict; live preview == engine facts ---
for name in FORM_CASES:
    expected = demo.clean(demo.CASES[name][1][-1])
    at = fresh()
    load(at, name)
    facts = engine.evaluate(expected)['facts']
    html = ' '.join(str(getattr(h, 'proto', h)) for h in at.get('html'))
    from ui import format as fmt
    want = [fmt.rupee(facts['proposed_emi']), fmt.pct(facts['foir']), fmt.years(facts['age_at_maturity'])]
    if facts.get('ltv') is not None:
        want.append(fmt.pct(facts['ltv']))
    check(f'U3 live preview = backend facts ({name})', all(w in html for w in want), ', '.join(want))
    CALLS.clear()
    button(at, 'Submit application').click().run()
    check(f'U3 demo loader dict == baseline dict ({name})', CALLS == [expected],
          'identical' if CALLS == [expected] else json.dumps(CALLS)[:300])

# --- U3: double submit ---
at = fresh()
CALLS.clear()
button(at, 'Submit application').click().run()
button(at, 'Submit application').click().run()
check('U3 double click submits once', len(CALLS) == 1, f'decide() calls: {len(CALLS)}')

# --- U4: re-apply pre-fill, no auto-submit ---
foir = {**demo.clean({**demo.BASE, 'Monthly_Income': 60000, 'Loan_Amount': 6_000_000, 'Collateral_Value': 9_000_000}),
        'Loan_ID': 'CHK-FOIR', 'Applicant_ID': 'CHK-A1'}
at = fresh()
at.text_area[0].input(json.dumps(foir))
button(at, 'Submit JSON').click().run()
button(at, 'See maximum approvable amount').click().run()
suggested = json.loads(at.code[0].value)['Loan_Amount']
CALLS.clear()
button(at, 'Fill the form with').click().run()
ok = at.session_state['f_amount'] == suggested and json.loads(at.session_state['json_raw'])['Loan_Amount'] == suggested
check('U4 Re-apply pre-fills form + JSON with the suggested amount', ok, f'₹{suggested:,}')
check('U4 Re-apply does not submit', CALLS == [], f'decide() calls: {len(CALLS)}')
check('U4 result still shown after pre-fill', any(':orange[Rejected]' in m.value for m in at.markdown))

# --- U4: flag off -> no button ---
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp) / 'features.yaml'
    p.write_text('max_amount_suggestion: {enabled: false}\n', encoding='utf-8')
    os.environ['COGNILEND_FEATURES_YAML'] = str(p)
    for name in ('hard_reject', 'auto_reject', 'malformed'):
        at = fresh(demo=name)
        check(f'U4 flag off -> no max-amount button ({name})',
              not [b for b in at.button if b.label == 'See maximum approvable amount'])
    os.environ.pop('COGNILEND_FEATURES_YAML')

# --- U4: start a new application ---
at = fresh(demo='auto_approve')
had = 'result' in at.session_state
del at.query_params['demo']             # the link opens New_Application?new=1 (it replaces the query string)
at.query_params['new'] = '1'
at.run()
check('U4 "Start a new application" clears result and resets form',
      had and 'result' not in at.session_state and at.session_state['f_loan_id'] == '' and
      at.session_state['f_amount'] == 3_000_000)

lines = ['# UI behaviour checks', '', 'Generated by `docs/ui/scripts/ui_checks.py` (streamlit AppTest).', '',
         '| Check | Result | Detail |', '|---|---|---|']
lines += [f'| {n} | {"PASS" if ok else "FAIL"} | {d} |' for n, ok, d in RESULTS]
allok = all(ok for _, ok, _ in RESULTS)
lines += ['', f'**Overall: {"PASS" if allok else "FAIL"}** ({sum(ok for _, ok, _ in RESULTS)}/{len(RESULTS)})']
Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
Path(sys.argv[1]).write_text('\n'.join(lines) + '\n', encoding='utf-8')
raise SystemExit(0 if allok else 1)
