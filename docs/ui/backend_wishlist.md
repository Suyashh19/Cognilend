# Backend wishlist (UI ideas that need a backend change — NOT implemented)

The redesign is frontend-only. These would improve the UI but need changes in `src/` and were therefore left out.

| # | Wish | Why the UI needs it | Backend change needed |
|---|---|---|---|
| W1 | **Applications today** tile on Home | The spec asks for "applications today"; `Repository.summary()` returns all-time counts by outcome only. The Home page shows all-time Approved / Rejected / Human Review / Open reviews instead. | `summary(since: datetime)` or a `decisions_per_day()` query. |
| W2 | Per-day decision trend chart on Home | A sparkline of decisions per day would make the demo livelier. | Same as W1. |
| W3 | Review Queue: full rule evaluations of the original decision | The queue row has the reason, model recommendation and confidence; the full explanation drawer reads `decision_history` + the audit payload. Rule-by-rule pass/fail is not in `list_reviews()`. | Join `rule_results` in `list_reviews()` (or a `rule_results(decision_id)` read). |
| W4 | Review Queue: server-side filters (reason, date) | Filters are applied in the UI to the ≤ 200 rows `list_reviews()` returns. With a large queue older cases would not be filterable. | `list_reviews(status, since, until, reason_like, limit, offset)`. |
| W5 | Audit Explorer: search beyond 500 rows / pagination | `decision_history(term)` caps at 500 rows, oldest first. | `offset` / `order` parameters. |
| W6 | Fairness "last run" per run id with the policy / model versions used | Shown from `fairness_runs()`; the versions are stored as JSON per row but there is no typed accessor. | Expose `versions` in `fairness_runs()`. |
| W7 | Decision summary download as PDF | The "Download summary" button produces a self-contained HTML file (printable to PDF from the browser) from the result already on screen. A server-side PDF with a signature/hash of the audit record would be stronger evidence. | A `summary_pdf(decision_id)` endpoint that signs the record. |
| W8 | Live preview of the *decision* before submitting | The Review step previews EMI, FOIR, LTV and age at maturity from the rule engine's fact base. Showing a predicted outcome before submit would need the dry-run scorer, and it does not model the FR-10 lock, so it could disagree with the real decision. Not shown on purpose. | A documented "pre-check" API that includes the lock pre-check. |
| W9 | Header model version from a single "active model" field | The header picks the most recently registered `dt_*` model from `versions()`; there is no explicit "active" flag. | `ModelRegistry.active` column / accessor. |
