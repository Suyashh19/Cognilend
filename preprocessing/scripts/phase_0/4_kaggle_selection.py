"""
Method 4: Final public-dataset selection

After evaluating multiple collection routes, we selected a publicly
available Kaggle loan dataset for the ML project.

IMPORTANT:
    Replace DATASET_PATH with the exact CSV downloaded for the project.
    Update the expected target column after inspecting the dataset.
"""

import pandas as pd

DATASET_PATH = "loan_dataset.csv"

df = pd.read_csv(DATASET_PATH)

print("Dataset shape:", df.shape)
print("\nColumns:")
print(df.columns.tolist())

print("\nFirst 5 records:")
print(df.head())

print("\nMissing values:")
print(df.isnull().sum())

print("\nData types:")
print(df.dtypes)

# Replace "Loan_Status" with the actual target column in your dataset.
if "Loan_Status" in df.columns:
    print("\nTarget distribution:")
    print(df["Loan_Status"].value_counts(dropna=False))
else:
    print(
        "\nTarget column not found yet. Inspect the column list and "
        "set the correct approval/rejection column."
    )

print("\nFinal source decision:")
print("Kaggle public dataset selected because it contains the required")
print("loan-related applicant features and an approval/rejection target")
print("without requiring access to confidential bank records.")
