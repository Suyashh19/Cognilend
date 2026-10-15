# Step 06: Forward-chaining rule engine

Date: 2026-10-15.

There is no teammate rule-engine code (Step 0 inventory), so the engine was built here. The R1–R7 parameters and the review triggers from the legacy prototype were carried over.

## What was built

- **`config/policies_v1.yaml`, restructured.** Each rule has `id`, `type` (HARD/SOFT), `name`, `condition` (readable), a machine-readable `fact` / `op` / `threshold` or `threshold_fact` (plus optional `unless` / `applies_when`), a `reason` template, a `rationale` and a `source`.
  - HARD rules R01–R07: minimum age 21, fraud registry, age at maturity ≤ 65, CIBIL ≥ 650 (unless new to credit), FOIR by income slab, RBI LTV tiers for home loans, minimum income ₹15,000.
  - SOFT rules S01–S04: new to credit, experience below minimum, borderline FOIR (within 5 points of the limit), and missing key information (CIBIL, EMI, experience, or collateral on a secured loan).
  - The spec's "S03 borderline FOIR / missing optional docs" is split into S03 and S04, so the review reason is specific.
- **`config/fraud_registry.yaml`**: demo IDs for R02. The registry is a file, so it can be updated without a code change. `Applicant_ID` (optional, for example a PAN) was added to the data contract. R02 is *not evaluated* when no ID is given.
- **`rules/facts.py`**: base facts, plus 16 derivations. They cover total income, rate, proposed EMI (annuity formula), FOIR, FOIR limit, borderline flag, loan-to-income, secured flag, LTV, LTV cap, age at maturity, new to credit, minimum experience, blacklist hit, missing fields and missing key data.
- **`rules/rules.py`**: the `Rule` dataclass and a YAML loader with schema checks. `Rule.evaluate` returns one of fired / passed / exempt / not_applicable / not_evaluated.
- **`rules/engine.py`**: `evaluate(application)`.
  1. Normalise the application and validate it against the contract. Invalid input returns a graceful REJECT (`invalid input: <field>: <message>`), and values that cannot be parsed are reported as such.
  2. Forward chaining: fire derivations until a fixpoint is reached.
  3. Evaluate every rule and record each one for the audit trail.
  4. Outcome: any HARD → REJECT, else any SOFT → REVIEW, else PASS. HARD reasons are listed first.
  
  It never raises. `evaluate_clean()` is a faster path for batch analysis of rows that are already clean.
- **`pipeline.py`**: a first `decide()`, written now so the rule-vs-model conflict can be tested end to end.
  - Rules run first. REJECT returns `Rejected` and the ML layer is **not called**.
  - REVIEW returns `Human Review`, with the tree's recommendation attached.
  - PASS goes to the tree plus confidence routing.
  - `audit_log_id` is `None` until the audit layer exists.
- **`scripts/rule_analysis.py`** generates `docs/rule_justification.md`. For every rule it reports firing counts on the training split, the label approval rate when the rule fires and when it does not, the approval rate either side of each numeric cutoff, an R03 cutoff sweep, and the rationale and source from the YAML.

## Files changed

- New: `rules/{facts,rules,engine}.py`, `config/fraud_registry.yaml`, `scripts/rule_analysis.py`, `docs/rule_justification.md`, `tests/test_rules.py`
- Changed: `config/policies_v1.yaml`, `config/data_contract.yaml`, `pipeline.py`
- `config/synthetic.yaml`: the old R1–R7 parameters were frozen under `diagnostic_rules`, so the Step 1 profile is unchanged. Re-running it produces a byte-identical `synthetic_profile.json`.
- `tests/test_smoke.py` was updated for the new policy layout.
- **`preprocess.py` bug fix (from Step 2):** `repair_invalid(historical=False)` is now used on the live path, together with the new `live_errors()`.

## Commands

```
python scripts/rule_analysis.py       (6.7 s)
python -m pytest                      -> 221 passed in 52.85s (71 in test_rules.py)
```

## Rule analysis (training split, n = 6,892)

| Outcome | n | share | historical approval |
|---|---|---|---|
| REJECT, invalid input (required field missing after cleaning) | 336 | 0.049 | 0.568 |
| REJECT, HARD rule | 1,997 | 0.290 | 0.256 |
| REVIEW, SOFT rule | 917 | 0.133 | 0.557 |
| PASS | 3,642 | 0.528 | 0.775 |

R03 sweep: the cap rejects 331 applicants at 60, 112 at 65 and 38 at 70. **The data does not support R03.** Applicants it rejects were historically approved at 0.705, against 0.584 for those it passes, because the label does not depend on age. The generated document says this plainly. It keeps 65 as a policy constraint and recommends either confirming it with the guide or making the 65–70 band SOFT.

## Acceptance checks

| Check | Evidence |
|---|---|
| ≥ 20 tests, one positive and one negative per rule | 22 test functions (30 cases), every rule from R01 to S04 covered both ways. These include the RBI LTV tiers (6 cases), FOIR slabs (4), the NTC exemption and income clubbing |
| Model would approve but a HARD rule fires → REJECT in 100% of cases | `test_rule_vs_model_conflict_hard_rule_always_wins`. It covers every test-split applicant the tree predicts Approved and a HARD rule rejects (the test asserts there are more than 50 such cases). With ML disabled (it raises if called), all of them end Rejected. `test_hard_reject_never_calls_ml` |
| Null, wrong-type and out-of-range fields 100% handled without exceptions | `test_malformed_fields_are_handled_without_exceptions`: all 17 input fields × 12 bad values (None, '', 'abc', ±huge, [], {}, object(), NaN, inf, True). Also `test_required_field_missing_gives_graceful_reject` (6), `test_non_mapping_or_empty_input` (6), `test_out_of_range_reports_field` |

## Bugs found and fixed

- **Live home-loan tenures were rescaled.** Since Step 2, the live path applied the historical "home-loan tenure ≤ 30 means years" repair, so a genuine 24-month home loan became 288 months. Fixed: that repair and the sign-error repair now run only for historical data. Covered by `test_live_home_loan_tenure_is_not_rescaled`.
- **Invalid input was mixed into REJECT.** The first analysis output counted 336 invalid-input rows inside REJECT, which made R02 look as if it had been evaluated on 336 rows. They are now a separate bucket.
- **The R03 conclusion was wrong.** My first draft said rejected applicants had approval "close to the overall rate". The data shows it is higher, and the text was rewritten to say so.

## Open issues / decisions for you

1. **R03:** keep the HARD cap at 65, or make maturity ages 65–70 SOFT? (See `docs/rule_justification.md`.)
2. **Applicant_ID:** the historical file has none, so R02 is exercised only by tests and live input. The lock layer (FR-10) will also need this ID and a collateral identifier.
3. **Engine scope:** the engine evaluates *all* rules even after a HARD rule fires, so every violation is reported. "Short-circuit" is enforced where it matters: the ML layer is never called.
