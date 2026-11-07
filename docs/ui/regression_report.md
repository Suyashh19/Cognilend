# U7: Regression report (backend untouched, features intact)

Branch `feature/ui-enhancement` vs `main`. All runs used the same rebuilt models. UI comparisons started from the
same seeded DB copy.

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | sha256 of every file outside `app/`, `.streamlit/` (427 source files) identical to U0 | **PASS** (0 changed, 0 missing, 0 added; only the runtime SQLite DB differs, which the app and tests write by design) | `regression/backend_hashes_compare.txt` |
| 2 | Full test suite = baseline | **PASS**: plain `pytest` gives the same single collection error as before (`tests/test_counterfactual.py` imports the non-existent `cognilend.explain`; pre-existing, backend/tests out of scope). With `--continue-on-collection-errors`: **361 passed, 1 error** before and after, and the per-test outcome list is identical | `baseline/pytest_before*.txt`, `regression/pytest_after*.txt` |
| 3 | `decide_many` on the test set byte-identical | **PASS**: sha256 `452273dea51a2b56959aa204812e694544e5a4e900260d0ced627cbbcf330a9c` both (`cmp`: identical) | `reports/baseline/decisions_before.csv`, `regression/decisions_after.csv` |
| 4a | Every demo case through the new UI: decision, confidence, reason, fired rules, audit ID | **PASS**: identical to the old UI in the same run, and the decisions + audit IDs are identical to the U0 baseline log (e.g. auto-approve Approved 0.967 audit 1492; hard reject Rejected 1.00 audit 1491) | `regression/calls/diff.md`, `baseline/calls_before.json`, `regression/calls/new.json` |
| 4b | Audit chain status | **PASS**: verify_chain OK in both (`audit_verify_chain` story) | `regression/calls/diff.md` |
| 4c | Max-amount result | **PASS**: possible case ₹31,60,000 (same explanation, EMI, binding limit); auto-reject "No lower amount can be approved" | `regression/calls/diff.md`, `after/screens/max_amount_*.png` |
| 4d | Real-browser run of every demo and page (Playwright, Chrome) | **PASS**: 17 targets captured with the same flow as U0 | `after/screens/*.png` vs `baseline/screens/*.png` |
| 4e | Behaviour checks (form dict parity, live preview = facts, double submit, re-apply pre-fill without submit, flag off → no button, start new) | **PASS** 20/20 | `regression/ui_checks.md` |
| 5 | Parity checklist | **PASS**: 118/118 items ticked with evidence; 158/158 baseline `st.*` calls covered | `parity_checklist.md` |
| 6 | `git diff --stat main...feature/ui-enhancement` touches only `app/`, `.streamlit/`, `requirements-ui.txt`, `docs/ui/` | **PASS** (65 files; none outside those paths) | `git diff --name-only main` |
| — | Contrast (U6) | **PASS** | `regression/contrast_report.md` |
| — | Responsive grid, no horizontal scroll (U6) | **PASS** (88 / 88) | `after/grid/` |
| — | Load time (U6) | **PASS** (total −26 %, no page > +0.04 s) | `regression/load_times.md` |

## Things to know
- **Setup:** the ZIP had no venv, models or DB, so I ran the project's own `scripts/run_all.py --no-tests` once
  before U0. The rebuilt models reproduce the project's earlier recorded decisions exactly (same sha256 as
  `reports/baseline/`).
- **Pre-existing test breakage:** `tests/test_counterfactual.py` (and the unused `app/counterfactual_section.py`)
  import `cognilend.explain.counterfactual`, which does not exist. It was not fixed: that needs a backend change.
- **Streamlit behaviours worked around in the UI only:** style-only `st.html` is not applied (CSS goes through
  `st.markdown`); a deep link as the first request after server start is served in legacy `pages/` mode (the menu is
  drawn by each page).
- Backend ideas not implemented: `backend_wishlist.md`.
- `plotly==7.1.0` (was `requirements-ui.txt`) is now part of `requirements.txt`: `pip install -r requirements.txt`.
