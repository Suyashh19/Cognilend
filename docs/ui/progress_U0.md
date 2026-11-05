# U0: Baseline and feature-parity checklist

Branch `feature/ui-enhancement`, created from `main`. `main` is the project exactly as received. The folder was not
a git repository, so `git init` + one commit made `main`.

## Environment setup (before the baseline)
The ZIP had no `.venv`, no trained models (`artifacts/models/` is git-ignored) and no database, so the app could
not start. I built them with the project's own pipeline, `python scripts/run_all.py --no-tests` (deterministic,
seed 42; all 11 steps passed in 19.4 min). This is the documented first-run setup. It is not a change to the
backend. **Evidence that the rebuild is faithful:** decide_many on the test set gives sha256
`452273dea51a…330a9c`, byte-identical to the project's own earlier baseline in `reports/baseline/decisions_before.csv.sha256`.
`rule_analysis` rewrote `docs/rule_justification.md` with different line endings only. I restored the committed
bytes with `git checkout`.

The seeded DB was copied aside. Every capture below starts from that same copy, so audit-log IDs are reproducible
(auto-approve = **1492** in both the screenshot and the call log).

## Outputs
| Item | File | Result |
|---|---|---|
| Backend hashes (everything outside `app/`, `.streamlit/`) | `baseline/backend_hashes.json` | 427 source files + 43 runtime files (DB, generated reports; informational) |
| Test suite, plain `pytest` | `baseline/pytest_before.txt` | **Collection error**: `tests/test_counterfactual.py` imports `cognilend.explain.counterfactual`, which does not exist in `src/`. Pytest stops at collection. This was already broken before the redesign (backend + tests are out of scope). |
| Test suite, `--continue-on-collection-errors` | `baseline/pytest_before_full.txt` | **361 passed, 1 error** (the same collection error) in 11 min; per-test baseline for U7 |
| decide_many on the test set (fresh temp DB) | `baseline/decisions_before.csv` (+ `.sha256`, `db_row_counts_before.json`) | sha256 `452273de…330a9c` |
| Backend calls of every user story in the old UI | `baseline/calls_before.json` | 22 / 22 stories ran (7 demo links, form defaults, 6 demo applicants typed into the form, JSON max-amount, malformed JSON, officer decision, verify chain, fairness rerun, stress twin, 2 renders) |
| Screenshots (1366 px wide, tall viewport) | `baseline/screens/*.png` | 7 demo cases, max-amount possible / not possible, all 8 pages |
| Feature-parity checklist | `parity_checklist.md` | 158 / 158 `st.*` calls of the baseline UI cited (`scripts/checklist_coverage.py` → PASS) |

## Key constraint found
`tests/test_app.py` and `tests/addons/test_ui_panel.py` (cannot be edited) pin parts of the UI:
- the outcome markdown must contain `:blue[Approved]` / `:orange[Rejected]` / `:violet[Human Review]`, and the metrics `Decided by`, `Audit-log ID`, `90% credible interval` must stay;
- the New Application page must render the **same** markdown / caption / alert / metric / button / code / expander elements as the baseline page for the demo cases;
- on the review / audit pages the first text area, radio and button must stay the note, decision and Record / Verify buttons;
- the max-amount panel texts, metric labels, the `Re-apply with ₹X` expander and its JSON code block must stay.

How the redesign keeps them: the outcome headline keeps its markdown source. Its colour is set per outcome by
scoped CSS on a keyed container, so it shows green, red or amber. New visual pieces on the form page use `st.html`,
widgets, tabs and page links, which are not part of the compared element list. Shared parts (the decision card and
the panel) live in `common.py` / `components/`, which the test copies for both sides.

## Screens
Baseline (before): `baseline/screens/demo_auto_approve.png`, `baseline/screens/demo_hard_reject.png`, `baseline/screens/max_amount_possible.png`.
