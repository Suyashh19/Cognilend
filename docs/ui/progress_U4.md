# U4: Decision result

- **Decision card** (`common.decision_card`): a coloured top bar, round icon and large headline per outcome:
  green ✓ Approved, red ✕ Rejected, amber ⚑ Human Review (colour + icon + text). Underneath: a one-sentence
  plain-language summary, tiles (Confidence, 90% credible interval, Audit-log ID, Decided by), the confidence
  meter with its interval band, and the audit ID with a **copy** button.
  - The headline keeps its markdown source (`## :blue[Approved]` etc., which the tests check). Scoped CSS on a
    keyed container recolours it to the outcome colour.
- **Why this decision**: the backend reason first, then every policy rule as a pass/fail chip (fired first), then
  the tree path as a trail, e.g. `CIBIL 800 > 742 ✓ → FOIR 0.174 ≤ 0.458 ✓ → CIBIL 800 > 777 ✓ → Model: Approved`.
- Expanders: the tree image with this applicant's path highlighted (the existing `draw_tree`, rendered once per path),
  raw values (rule evaluations, path steps, full result JSON), model and policy version.
- **Download summary**: a self-contained HTML file built from the result already on screen (no new backend data).
  **Start a new application** clears the result and the form.
- **Maximum approvable amount** (`components/max_amount_panel.py`): the button stays directly below the Rejected
  card. Result box: the amount in large ₹ text, requested-vs-suggested bars, binding-limit badge, the same metrics
  (Requested / Reduction / EMI at ₹X / Confidence at max), the "Suggestion only" note, and **Re-apply with ₹X**
  (the JSON as before, plus *Fill the form with ₹X*, which pre-fills the form and the JSON tab and does not submit).
  Feature flag off → no button.

Checks:
- `tests/test_app.py` (17) and `tests/addons/test_ui_panel.py` (11, which also compares the page with `main`): pass.
- `regression/ui_checks.md`: Re-apply pre-fills and does not call `decide()`; flag off → no button on
  hard_reject / auto_reject / malformed; Start-new resets. PASS.
- Same seeded DB, same order: every demo shows the same decision, confidence, reason and **audit ID** as the
  baseline (e.g. auto-approve 0.97 / 0.96–0.97 / 1492). Max amount ₹31,60,000 and "No lower amount" match
  (`regression/calls/diff.md`, `after/screens/demo_*.png` vs `baseline/screens/demo_*.png`).

One bug found and fixed along the way: the raw-values table mixed booleans and numbers in one column, which Arrow
cannot serialise, so those columns are shown as text.
