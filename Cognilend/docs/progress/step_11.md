# Step 11: Consolidate and prove every requirement

Date: 2026-10-15.

## What was built

- **`tests/test_evidence_gates.py`** is one named test per Minimum Engineering Evidence gate, plus the extra NFR checks:
  - Gate 1, rule vs model conflict: zero overrides, and the model is never consulted after a HARD rule.
  - Gate 2, rare/edge profiles (the two least-supported leaves, new to credit, missing key data): routed to review or HARD-rejected, never auto-decided. The confusion matrix goes to `rare_subset.json`.
  - Gate 3, SMOTE train-only.
  - Gate 4, DB write failure: replay is complete.
  - Gate 5: 17 fields × 11 bad values, missing fields and non-dict input, all 100% handled.
  - Gate 6: fairness breach.
  - Gate 7: three fresh-DB runs identical.
  - Extra checks: tree caps and gap, entropy ≤ 1e-9, tamper detection, the lock load test, decision-log coverage and an end-to-end smoke test of all 7 demo cases.
- **`scripts/lock_load_test.py`** sends 500 concurrent requests (one barrier release) through the full pipeline over 50 collaterals, on a fresh DB.
- **`scripts/kpi_report.py`**:
  - runs `pytest -v` with `--junitxml` and `--cov` (pytest-cov)
  - reads totals from the JUnit XML and **asserts they equal the pytest summary line**
  - computes every KPI from artefacts. Rule-trigger precision is measured against an *independent* pandas re-implementation of every rule condition, compared with the DB `rule_results`.
  - writes `artifacts/reports/kpi_report.md`, with no hand-typed numbers
- `requirements.txt` adds `pytest-cov==7.1.0` and `coverage==7.16.2`.

## Commands

```
python scripts/lock_load_test.py 500 50     (105 s)
python scripts/kpi_report.py                (runs the whole suite: "314 passed in 129.04s")
```

## Results (`artifacts/reports/kpi_report.md`)

**Test run:** `314 passed in 129.04s`. JUnit gives 314 tests, 314 passed, 0 failed, 0 errors, 0 skipped. Line coverage of `src/cognilend` is 75.2%.

| KPI | Measured | Status |
|---|---|---|
| Validation accuracy, constrained tree (≥ 0.80) | 0.7827 | **FAIL** (cause listed) |
| Tree depth ≤ 4 / nodes ≤ 15 | 4 / 15 | PASS |
| Generalization gap ≤ 0.15 | 0.0232 | PASS |
| Entropy error ≤ 1e-9 | 0.00e+00 | PASS |
| Rule-trigger precision = 100% | 1.0000 (800/800 fired; recall also 1.0 per rule) | PASS |
| Decisions logged | 1478/1478 | PASS |
| Audit chain | OK | PASS |
| Majority auto-cleared | 0.6989 | PASS |
| None silently dropped | 0 dropped, 0 unpersisted | PASS |
| DI ≥ 0.80, every subgroup with sufficient data | min 0.366 (age ≤25) | **FAIL** (cause listed) |
| Reproducible over 3 runs | IDENTICAL | PASS |
| Lock under 500 concurrent requests | 50 approvals / 50 collaterals, max 1 each | PASS |
| Rare/edge profiles auto-decided by the model | 0 of 335 | PASS |
| SQL-queryable audit; no crash on bad input | tests pass | PASS |
| Test suite | 314/314 | PASS |

All 14 rows in the gates table pass. On the rare subset (n = 335), 175 cases went to review and 160 were HARD-rejected. The model is 0.731 accurate on the scored part of this subset, below its overall accuracy, which supports routing these cases to people.

**Load test (500 concurrent requests, 50 collaterals):**
- Correctness: exactly 50 approvals, 450 Human Review, all 500 persisted, chain OK, 0 sent to the fallback log.
- Lock latency p50 / p95 / p99: 1,225 / 4,916 / 5,617 ms. End-to-end p50 is about 102 s, and throughput is 4.7 requests/s.
- These figures are for a worst-case burst: all 500 requests are released at once inside one Python process, so they queue on the GIL (the model scoring is CPU-bound) and on SQLite's single writer. They are not steady-state latency. Uncontended single decisions take about 30–110 ms (Step 8).

## Acceptance checks

| Check | Evidence |
|---|---|
| All tests green, or failures listed with cause | 314/314 green. The two KPI FAILs (accuracy, DI) are listed with their causes in kpi_report.md. |
| Total test count and pass count match pytest exactly | `kpi_report.py` asserts that the JUnit passed count equals the "N passed" in pytest's summary line. The report quotes that line verbatim. |

## Open issues

1. **Coverage gaps:** coverage is lowest in `ml/benchmark.py` (21%), `ml/confidence.py` (27%), `fairness/disparate_impact.py` (36%) and `ml/tree.py` (44%). Their *training and report-generation* entry points (`run()`, `train()`, `render()`) run as scripts; the tests check what those scripts produce rather than re-running 60-second trainings inside pytest. The decision-path code itself is above 85% (pipeline 91%, engine 87%, preprocess 86%, db 94–100%).
2. **The two KPI failures need decisions from you and the guide.** Both are described in Steps 3/4 (accuracy) and Step 9 (DI).
