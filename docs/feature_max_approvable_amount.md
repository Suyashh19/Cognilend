# Add-on: Maximum Approvable Amount (FR-12)

## Purpose

When an application is **Rejected**, the officer can press **"See maximum approvable amount"** under the decision
card. The system answers either:

- **"Can be approved up to ₹X (instead of ₹Y requested)"**, with the EMI at ₹X for the same tenure, the model
  confidence at ₹X and the limit that decides the cap (`FOIR`, `LTV`, `MODEL` or `RULE:<id>`), or
- **"No lower amount can be approved"**, with the reason (for example, a rule that does not depend on the amount).

Only the loan amount changes. Income, tenure, CIBIL, collateral and every other field stay fixed. The suggestion
is **advisory**. It never creates a decision, and the applicant must submit a new application with the new
amount through the normal pipeline.

## Design: nothing existing changes

| Piece | File (all new unless stated) |
|---|---|
| Feature flag + parameters | `config/features.yaml` (`max_amount_suggestion.enabled`, `step`, `min_loan_amount`, `max_grid_points`, `log_suggestions`) |
| Side-effect-free scoring | `src/cognilend/addons/dry_run.py`: `evaluate_without_saving()` |
| Search | `src/cognilend/addons/max_amount.py`: `find_max_approvable_amount()` |
| Optional logging | `src/cognilend/addons/suggestion_store.py`: separate table `amount_suggestions` |
| UI | `app/components/max_amount_panel.py`: `render_max_amount_panel()` |
| Integration (only edit to an existing file) | `app/pages/1_New_Application.py`: **2 added lines** (import + call) after `common.decision_card(...)` |

`evaluate_without_saving` calls the existing `DecisionPipeline` with `repo=None`. That is the same code path as
`decide()` (contract → facts → rule engine → `transform_applicant` → constrained tree → Bayesian confidence → routing
with `tau`, `n_min` and SOFT rules) with the same artefacts. Without a repository it opens no DB session, takes no
lock, writes no audit event and no fallback record. No existing function was edited.

The results page only keeps the decision dict, not the application. The panel therefore reads the submitted
application back **read-only** from `loans.application_json` (or from the fallback log if the DB write failed).

## How the search works

1. **Applicability.** The application is re-scored with the dry run. If it is not Rejected, the result is
   `{applicable: False}`.
2. **Classify the rejection.** Each fired rule is checked against the fact derivation graph. A rule depends on the
   amount when its fact or threshold fact is derived (transitively) from `loan_amount`. With policy v1 this gives
   R05 (FOIR), R06 (LTV) and S03 (borderline FOIR), and the list is computed, not hand-typed. If any fired rule
   does not depend on the amount (R01 age, R02 blacklist, R03 age at maturity, R04 CIBIL, R07 income, S01/S02/S04,
   invalid input), the result is `possible: False` with that rule cited, and no search runs.
3. **Rule caps → upper bound.** These use the facts module's own EMI derivation:
   - FOIR: `max_amount_foir = ((foir_limit − borderline_margin) × total_income − existing_EMI) / EMI_per_rupee`.
     The S03 margin is included because a FOIR inside it goes to human review, not to auto-approval.
   - LTV (housing): the largest `A` with `A / collateral ≤ ltv_cap(A)`, across the RBI slabs.
   - `upper = min(largest step multiple below the requested amount, FOIR cap, LTV cap)` and
     `lower = max(min_loan_amount, contract minimum)`.
4. **Candidate amounts.** The tree is not monotonic in the amount. Every amount-dependent fact (`loan_amount`, FOIR,
   loan-to-income, collateral cover, LTV) is monotonic, though, so the outcome can only change at a
   **breakpoint**:
   - each tree split threshold on those features, converted back to rupees
   - the FOIR and LTV limits
   - the LTV slab edges

   The candidate set is the largest step multiple at or below each breakpoint (and the one below it), plus the
   whole ₹10,000 grid when the range is small. This set is exhaustive over step multiples, and a test checks it
   against a brute-force full grid.
5. **Confirmation.** All candidates are scored in one batch (`decide_many` without a repository). The highest
   Approved one is re-confirmed with `evaluate_without_saving`. Then `max + one step` is scored to name the
   **binding limit**.
6. **Nothing approves** → `possible: False`, "no amount down to ₹<lower> is auto-approved", and whether the rules
   or the model is the blocker.

## What "not possible" means

- The rejection does not depend on the amount (age, age at maturity, CIBIL, blacklist, minimum income, missing
  data, invalid input). No amount fixes it.
- The FOIR or LTV cap is below the minimum loan amount.
- No amount in range is auto-approved by the model (low-confidence or Rejected leaves all the way down).

## Limitations

- **Tenure is held fixed.** A longer tenure could allow more, but that is a possible later extension behind its own
  flag.
- **Advisory only.** The FR-10 lock check is not simulated (it needs the DB). A suggestion can still go to human
  review if the applicant or collateral already has an approved active loan.
- Non-monotonicity of the tree is handled by checking every breakpoint interval, not by binary search.
- `docs/traceability.md` is regenerated by `scripts/build_docs.py`. The appended FR-12 row must be re-appended after
  a regeneration.

## Toggling

```yaml
# config/features.yaml
max_amount_suggestion:
  enabled: false     # the app then behaves exactly as without the add-on
```

The flag is read on every render, so no restart is needed. Tests can point `COGNILEND_FEATURES_YAML` at another
file.

## Test results

| Check | Result |
|---|---|
| Dry run = baseline `decide_many` on the 1,478-application TEST split (decision, confidence, reason, rules) | 100 % match |
| Rows written by the dry run to any table (1,000 applications); DB engine creation blocked during the run | 0 |
| Rejected TEST-split cases searched | 557 (145 possible, 412 not possible) |
| Suggestions re-submitted to the **normal** `DecisionPipeline.decide` (throwaway DB) and Approved | 145 / 145 = **100 %** |
| Runtime per application | p50 ≈ 50 ms, p95 ≈ 450–500 ms (< 1 s) |
| Breakpoint candidates vs brute-force full grid (27 cases) | identical maximum |
| Protected attributes (Gender, Marital_Status) | never referenced; result unchanged when they change |
| Core table counts and `verify_chain()` after logging suggestions | unchanged / OK |

See `reports/feature_max_amount_eval.md`, `reports/feature_max_amount_regression.md` and the screenshots in
`reports/screens/max_amount/`.
