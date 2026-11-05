# U5: Officer, Audit, Model and Fairness pages

- **Review Queue**: reason and date filters (applied to the rows `list_reviews()` already returns), a queue table
  (₹ amounts, confidence bars, "why here" tag), a case detail card with a *Full decision explanation* drawer
  (`decision_history` + `audit_event`, read-only), and a form with officer ID, Approved / Rejected and a required
  note. It makes the same `complete_review(review_id, officer, outcome, notes)` call. Empty state: "No open reviews."
- **Audit Explorer**: a prominent **Verify chain** card (green OK, or a red alert plus the broken record via
  `audit_event(first_broken_seq)`), prefix search, a per-applicant timeline, the full table, and decision detail
  with hashes and the payload.
- **Model & Policy**: metric tiles, a zoomable tree image, a Plotly benchmark chart (table in an expander), policy
  rules as cards with HARD / SOFT badges, condition, rationale and source (table in an expander), versions in force.
- **Fairness**: tiles (last run, subgroups, below 0.80, lowest DI among subgroups with enough data), a DI bar chart
  per group with the 0.80 line, below-threshold bars in red, n in every label, insufficient data hatched; the
  original three-mode figure, table, evidence-gate caption and full report are kept. *Rerun fairness audit*
  unchanged.
- **Stress Twin / Model Comparison**: restyled; same inputs, same calls.
- Loading spinners on every action; empty states; friendly errors.

Checks (`regression/calls/diff.md`): officer decision, verify chain, fairness rerun, stress test and every page
render make the **same action calls with the same arguments** as the old UI (22/22 stories PASS). Extra calls
are read-only drawing queries only. Numbers on the pages match the baseline screenshots (same DB).

Before / after: `baseline/screens/{review_queue,audit_explorer,model_and_policy,fairness_dashboard}.png` →
`after/screens/…`.
