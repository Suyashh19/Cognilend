# U3: New Application form

- Steps **1 Applicant · 2 Employment & Income · 3 Credit · 4 Loan & Collateral · 5 Review & Submit**. They are
  styled tabs, so every widget stays mounted and you can go back and forth without losing anything (values in
  `st.session_state`, keys `f_*`).
- Plain-language help on every field; ranges are read from `config/data_contract.yaml` (`contract.FIELDS`).
  Widget bounds, defaults and types are **unchanged** from the original form.
- Inline validation uses `contract.validate()` (the backend's own check), shown next to the step's fields and
  summarised on step 5. Submitting is never blocked, so invalid input still reaches the backend's graceful
  rejection. The Raw JSON tab keeps accepting anything.
- **Live preview** on step 5: proposed EMI (with the indicative rate), FOIR vs its limit, LTV vs the RBI cap, and age
  at maturity. All values come from `engine.evaluate(app)['facts']`, the rule engine's fact base (read-only,
  nothing stored). No formula is re-implemented.
- **Load a demo applicant** picker (one per demo case, from `cognilend.demo.CASES`). Malformed goes to the JSON tab,
  because its values cannot be typed into the form.
- Submit shows a spinner. An identical second click within 5 s does not submit again.

Checks (`regression/ui_checks.md`, all PASS):
- for all 6 form-capable demo cases, the dict sent to `decide()` is **identical** to the baseline dict;
- the live preview shows exactly the backend facts;
- a double click calls `decide()` once.

Old vs new call logs (`regression/calls/diff.md`): the same 6 applicants entered in the old form and through the new
picker produce identical `decide()` calls (args, decision, confidence, reason, audit ID).

Before / after: `baseline/screens/new_application_form.png` → `after/screens/new_application_form.png`.
