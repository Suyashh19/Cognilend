# Step 10: Streamlit UI on top of `pipeline.decide`

Date: 2026-10-15.

## What was built

The UI contains no business logic. Pages only call `DecisionPipeline.decide / complete_review`, the read-only `Repository` queries (new: `list_reviews`, `decision_history`, `audit_event`, `versions`, `fairness_runs`, `fairness_rows`, `summary`), `disparate_impact.run / figure`, `tree_plot.draw_tree` and the stress twin.

| Page | What it does |
|---|---|
| `streamlit_app.py` (home) | Decision counts, open reviews, live audit-chain status |
| 1 New Application | Validated form (₹ amounts, tenure in months, ranges from the data contract) plus a raw-JSON tab for any input, including malformed input. The decision card shows: outcome, confidence with its 90% credible interval, the reason sentence, every rule (red = HARD fired, orange = SOFT fired, green = passed, grey = n/a), the tree with this applicant's path in bold (thresholds in original units), and the audit-log ID. `?demo=<case>` runs a demo case. |
| 2 Officer Review Queue | Open cases with their reasons. The officer approves or rejects with a required note; this records a HUMAN decision with a `human_review_completed` audit event. An approval must still pass the FR-10 lock. |
| 3 Audit Explorer | Prefix search by loan or applicant id, decision history, the audit event with its hashes and payload, and a **Verify chain** button that shows OK or the first broken row |
| 4 Model & Policy | Policy and model versions with SHA-256, tree metrics, the tree drawn in original units, the benchmark table, the routing threshold, and the rules table with rationale and source |
| 5 Fairness Dashboard | Verdict, DI per subgroup with the 0.80 line and CIs for the three layers, last run time, a rerun button, the breach-test result and the full fairness report |
| 6 Stress Twin | Advisory panel (Step 12) |

New support code:
- `cognilend/demo.py`: the 7 demo cases with their expected outcomes
- `ml/tree_plot.py`: path-highlighted tree drawing
- `scripts/seed_demo.py`: fresh DB, full test set, fairness run, demo cases (expected vs actual checked)
- `scripts/screenshots.py`: starts the app headless and captures every page with Playwright driving the installed Chrome
- `tests/test_app.py`: Streamlit `AppTest`
- `pipeline.decide` output gained `confidence_ci`, `leaf`, `leaf_support`, `rule_evaluations` and `invalid_fields`

## Commands

```
python scripts/seed_demo.py                # fresh DB + test set + fairness + 7 demo cases
streamlit run app/streamlit_app.py         # one command
python scripts/screenshots.py              # 13 screenshots -> artifacts/reports/screens/
python -m pytest tests/test_app.py         # 16 passed
```

## Demo cases (`seed_demo.py` output; `artifacts/reports/demo_cases.json`)

| Case | Expected | Actual | Screenshot |
|---|---|---|---|
| HARD reject (R01 minimum age) | Rejected / RULE | Rejected / RULE | `demo_hard_reject.png` |
| Auto-approve | Approved / MODEL (confidence 0.97) | same | `demo_auto_approve.png` |
| Auto-reject | Rejected / MODEL (confidence 0.85) | same | `demo_auto_reject.png` |
| SOFT review (S01 new to credit) | Human Review / RULE | same | `demo_soft_review.png` |
| Low-confidence review | Human Review / MODEL (0.63 < τ) | same | `demo_low_confidence.png` |
| Duplicate collateral (FR-10) | Human Review / RULE, "Lock (FR-10)" | same | `demo_lock.png` |
| Malformed input (Age 999, income "abc") | Rejected / RULE, invalid fields listed | same | `demo_malformed.png` |

Page screenshots: `home.png`, `review_queue.png`, `audit_explorer.png`, `model_and_policy.png`, `fairness_dashboard.png` and `stress_twin.png`. I inspected several (hard reject, lock, fairness dashboard, stress twin).

## Acceptance checks

| Check | Evidence |
|---|---|
| App starts with one command on a fresh DB seeded by a script | `seed_demo.py`, then `streamlit run app/streamlit_app.py`. `screenshots.py` does exactly this headless and waits on `/_stcore/health`. |
| Each demo produces the expected screen; screenshots saved | `test_demo_case_shows_expected_decision_card` (7 cases) checks the outcome badge, the source, the audit-ID and case-specific text. 13 PNGs are in `artifacts/reports/screens/`. |

Also tested: every page renders without exception (`test_every_page_renders_without_exception`, 7 pages); an officer decision recorded through the UI; the Verify chain button.

## Issues found and fixed

- **Dependents selectbox:** `format_func` returned an int, which Streamlit rejects, so the New Application page crashed. Caught by AppTest.
- **Stress-twin form:** its key collided with the session-state key that holds its results.
- **Blank screenshots:** headless Chrome `--screenshot` captured only Streamlit's loading skeleton, because the virtual-time budget doesn't wait for the websocket render. Switched to Playwright with explicit waits. I opened the images to confirm.
- **Raw numbers on the card:** rule values printed as raw floats (`0.17356464667310678`, `1.5e+05`). They are now formatted.

## Open issues

- The sidebar's first entry is labelled "streamlit app" (Streamlit's default name for the entry file). This is cosmetic.
- Playwright is pinned for screenshots only. It uses the installed Chrome or Edge, so no browser download is needed.
