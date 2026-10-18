# Step 02: Preprocessing as a fitted, saved pipeline

Date: 2026-10-15.

## What was built

`src/cognilend/data/preprocess.py`:

1. **Stateless cleaning.** This runs before the split and works row by row.
   - `normalise()` maps spellings to canonical values (lookup built from the documented spellings), parses `"Rs. 27,90,000"` to 2790000, and turns `"3+"` into 3.
   - `repair_invalid()` reverses sign errors in income (`abs`), multiplies home-loan tenures of 30 or less by 12, and sets values outside the contract ranges to NaN. That covers ages like 999, CIBIL like 9999 (`−1` is kept), experience greater than age − 18, and zero income.
   - Structural blanks are filled: no co-applicant becomes 0, and an unsecured loan gets collateral 0.
   - Flags for missing CIBIL, EMI, income and secured collateral are added, ready for the Step 3/4 soft rules.
   - `prepare_dataset()` also removes the 135 exact duplicates and the 18 unlabelled rows: 10,000 rows become 9,847.
2. **Split first.** `split()` makes a stratified 70/15/15 split with seed 42. The Loan_IDs of each split are saved to `data/processed/split_indices.json`.
3. **Preprocessor fitted on train only.** It is a single sklearn `Pipeline`:
   - `BankingFeatures` imputes missing values with the train median (numeric) or mode (categorical). CIBIL is imputed with the median of *scored* applicants, because `−1` is not missing. It then builds banking features from the real, uncapped values: `total_income`, `proposed_emi`, `foir`, `loan_to_income`, `collateral_coverage`, `ltv`, `age_at_maturity`, `is_new_to_credit`, `is_secured` and `has_coapplicant`.
   - A `ColumnTransformer` then applies `IQRCapper(3.0)` followed by `MinMaxScaler(clip=True)` to the 9 continuous features. `dependents` (ordinal) and the 3 binary flags pass through unscaled. `Employment_Type` and `Loan_Type` are one-hot encoded and also not scaled.
   - Result: 20 features.
4. **Protected attributes are excluded.** Gender, Marital_Status, Age, Age_Band and Property_Area are not in the feature matrix. `age_at_maturity` and `ltv` are computed but kept out of the model through config (`preprocess.facts_only`): age_at_maturity carries age, and Age_Band is protected. The side table `data/processed/protected.parquet` holds Loan_ID, Gender, Marital_Status, Age, Age_Band, Dependents, Property_Area and split.
5. **SMOTE.** `make_resampler()` returns SMOTENC, which treats the code columns as nominal, with seed 42. It is meant to run inside an imblearn `Pipeline`, so it only acts during `fit`. Before/after counts are logged.
6. **Saved and versioned.** `artifacts/encoders/preprocessor_v1.joblib` holds the version, creation time, sklearn and Python versions, the SHA-256 of the data, the feature names, the class distribution, the SMOTE counts and the fitted pipeline. `transform_applicant(dict)` takes one live application (raw or canonical spellings), validates it against the contract, and returns a one-row feature frame. Invalid input raises `ContractError` listing every violation; it is never imputed over.
7. **Loan.csv.** `prepare_loan_csv()` drops the ID, the target and the pricing columns (which leak the target). `build_generic_preprocessor()` applies median/mode imputation, IQR capping, MinMax scaling and one-hot encoding. Both are tested on a frame shaped like Loan.csv. **Running them on the real file is blocked until Loan.csv is supplied.**

## Files changed

- `src/cognilend/data/preprocess.py` (new)
- `config/settings.yaml` (new `preprocess` and `model` sections)
- `src/cognilend/data/contract.py` (error messages print plain numbers)
- `requirements.txt` (adds `pyarrow==26.0.0` and `scipy==1.18.1`)
- `tests/test_preprocess.py` (new, 24 tests)
- `Makefile` and `scripts/tasks.ps1` (`train` now runs preprocessing and then the tree)

Outputs: `data/processed/{train,val,test,clean,protected}.parquet`, `split_indices.json`, `artifacts/encoders/preprocessor_v1.joblib` and `artifacts/reports/preprocess_summary.json`.

## Commands

```
uv pip install pyarrow
python -m cognilend.data.preprocess
python -m pytest
```

## Class distributions (share Approved)

| Split | n | Approved |
|---|---|---|
| all (after cleaning) | 9,847 | 0.5855 |
| train | 6,892 | 0.5855 |
| val | 1,477 | 0.5856 |
| test | 1,478 | 0.5853 |

SMOTE on train only: before {Rejected 2,857, Approved 4,035}, after {4,035, 4,035}. Val and test are never resampled.

## Acceptance checks (pytest)

| Check | Test |
|---|---|
| Val and test class distributions are within 1 percentage point of the original | `test_class_distribution_within_one_point[val/test]`. Actual differences are 0.01 and 0.02 points. |
| SMOTE changes the row count on train only | `test_smote_changes_train_counts_only`. Resampling grows train; predictions on train, val and test keep each split's row count. |
| Fitted statistics equal the train-only statistics | `test_fitted_statistics_come_from_train_only` checks the medians, the scored-CIBIL median, the IQR bounds and the scaler min/max. `test_full_data_statistics_would_differ` confirms the check is meaningful. |
| `transform_applicant` works on a single dict and returns the right columns | `test_transform_applicant_single_dict`, `..._canonical_and_raw_spellings_agree`, `..._matches_batch_transform`, `..._rejects_invalid_input` (4 cases), `..._ignores_protected_inputs` |
| No protected attribute in the feature matrix | `test_no_protected_attribute_in_feature_matrix` checks the in-memory build, the saved bundle and all three parquet files |

## Issues found and fixed during the step

- `python -m cognilend.data.preprocess` first pickled the custom transformers as `__main__.BankingFeatures`. The saved file then failed to load from any other module with `AttributeError`. Fixed: the `__main__` block now calls the functions through the package import. The same pattern is used in `tree.py`.

## Open issues

- **Loan.csv is still not supplied**, so task 8 has only been run on a stand-in frame.
- IQR capping skips a column whose train IQR is 0. No current continuous feature has an IQR of 0. The guard prevents a zero-heavy column from being flattened to a constant.
- The engineered features use the indicative rates from `policies_v1.yaml`, so a new policy version changes FOIR. Policy versioning in Step 6 will need to record which preprocessor version goes with which policy.
