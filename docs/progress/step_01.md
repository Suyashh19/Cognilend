# Step 01: Dataset decision and data contract

Date: 2026-10-15.

## What was built

- **Decision:** the primary dataset is the newly generated synthetic Indian dataset. Loan.csv is the secondary dataset, used as an ML benchmark only, and is **not supplied yet**. Full rationale is in `docs/data_decision.md`.
- `src/cognilend/data/synthetic.py`: a deterministic generator (seed 42) in three stages: clean applicants, then a label drawn from a latent repayment-risk score plus noise (policy rules play no part), then the documented defects with exact counts.
- `src/cognilend/data/contract.py` with `config/data_contract.yaml`: the FR-1 input schema. It provides `validate()` (never raises), `validate_frame()`, `age_band()`, and the lists `PROTECTED` and `MODEL_ELIGIBLE`.
- `src/cognilend/data/loaders.py`: `load_synthetic_raw()`, `load_loan_csv()` (gives a clear error when the file is absent), and the Loan.csv target-investigation tools `target_investigation()` and `pricing_explains_target()`.
- `scripts/describe_synthetic.py`: writes the dataset profile to `artifacts/reports/synthetic_profile.json`.

## Files changed

| File | Change |
|---|---|
| `config/synthetic.yaml` | new: every generator parameter |
| `config/data_contract.yaml` | new: the schema |
| `config/settings.yaml` | `paths.synthetic_raw` now points to `loans_raw.csv`; the team file is listed as `team_synthetic_raw` |
| `src/cognilend/data/{synthetic,contract,loaders}.py` | implemented (they were stubs) |
| `data/synthetic/loans_raw.csv` | new, generated |
| `scripts/describe_synthetic.py` | new |
| `tests/test_synthetic.py`, `tests/test_contract.py`, `tests/test_loaders.py` | new |
| `.gitattributes` | new: `data/synthetic/*.csv -text`, so git line-ending conversion cannot change the hash on checkout (`core.autocrlf=true` on this machine) |
| `docs/data_decision.md` | new |

The project `.venv` now has the pinned requirements and the package installed in editable mode. Its existing Jupyter packages were left in place.

## Commands run

```
uv pip install --python .venv/Scripts/python.exe -r requirements.txt && uv pip install -e . --no-deps
python -m cognilend.data.synthetic        (run twice)
python scripts/describe_synthetic.py
python -m pytest
```

## Output

Generator, two runs (final parameters):
```
wrote ...\data\synthetic\loans_raw.csv  sha256=084ecd3ca85b3cd788e7f282a1293fbb978d7265ad2141880e7ae1ca06ea39a7
wrote ...\data\synthetic\loans_raw.csv  sha256=084ecd3ca85b3cd788e7f282a1293fbb978d7265ad2141880e7ae1ca06ea39a7
```
(The first parameter set gave hash `528aeb17…` on both runs, which was also deterministic. It was superseded by the calibration described in data_decision.md §3.)

pytest:
```
91 passed in 7.53s
```
These comprise 21 smoke tests, 33 synthetic-data tests, 34 contract tests and 3 loader tests.

## Acceptance checks

| Check | Evidence |
|---|---|
| Generator is deterministic with seed 42 | `test_generator_is_deterministic` (two writes give the same SHA-256). `test_committed_file_matches_generator` (a fresh write equals the committed file). A different seed gives a different hash. |
| The raw file contains each documented defect type | Exact-count tests for duplicates, unlabelled rows, text amounts and the `Rs.` prefix, impossible ages, negative/zero income, invalid CIBIL, impossible experience, and tenures keyed in years. Presence tests for whitespace and spelling variants in all 5 text columns, `3+`, the NTC `−1`, random missing values in 10 columns (within ±35% of the configured rate), and structural missing values. |
| Contract rejects age = 999 and accepts a clean row | `test_age_999_is_rejected`, `test_clean_row_is_accepted`. In addition, 14 invalid cases are rejected and 5 garbage inputs return errors without raising. |

## Metrics (dataset profile)

The approval rate is 0.585. Rule violators are approved 27.2% of the time and compliant applicants 74.9%. Predicting with the rules alone reaches 0.742 accuracy. The noise-free ceiling is 0.902. As crude sanity checks only, an entropy tree of depth 4 reaches 0.803 in 5-fold CV and a Random Forest reaches 0.863. Label DI against Male applicants is 0.957 for Female and 0.856 for Transgender (n=67).

## Open issues

1. **Loan.csv is still missing.** Task 1 (target investigation) is blocked. The tooling is ready and tested on a toy frame that mimics the reported pattern.
2. With a depth-4 tree on crude features, accuracy (0.803) is only just above the 80% KPI. Step 4's engineered features (real FOIR, coverage, headroom) should help, and the result will be reported honestly either way.
3. `age_at_maturity` carries age information. Step 2 must decide whether it can be a model feature, given that Age_Band is protected.
4. Coapplicant income is missing in 57.6% of rows, against 67.9% in the team file. This is a minor difference from the team's documented spec and was left as is.
5. Nothing has been committed to git yet.
