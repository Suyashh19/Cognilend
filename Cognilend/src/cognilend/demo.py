"""Demo applications: one per decision path. Used by the UI (?demo=<name>), scripts/seed_demo.py and the tests."""
from __future__ import annotations

BASE = dict(Age=35, Gender='Female', Marital_Status='Married', Dependents=1, Employment_Type='Salaried',
            Work_Experience=10, Monthly_Income=150000, Existing_EMI=0, CIBIL_Score=800, Loan_Type='Home',
            Loan_Amount=3_000_000, Loan_Tenure=240, Collateral_Value=5_000_000, Property_Area='Urban')

# name -> (title, applications submitted in order (the last one is shown), expected decision, expected source)
CASES = {
    'hard_reject': ('HARD rule reject (R01 minimum age)',
                    [{**BASE, 'Loan_ID': 'DEMO-HARD', 'Applicant_ID': 'DEMO-A1', 'Age': 20, 'Work_Experience': 1}],
                    'Rejected', 'RULE'),
    'auto_approve': ('Auto-approve (high-confidence leaf)',
                     [{**BASE, 'Loan_ID': 'DEMO-APPROVE', 'Applicant_ID': 'DEMO-A2'}], 'Approved', 'MODEL'),
    'auto_reject': ('Auto-reject (model, high-confidence leaf)',
                    [{**BASE, 'Loan_ID': 'DEMO-REJECT', 'Applicant_ID': 'DEMO-A3', 'CIBIL_Score': 700,
                      'Monthly_Income': 120000, 'Existing_EMI': 35000, 'Loan_Type': 'Personal', 'Loan_Amount': 500000,
                      'Loan_Tenure': 36, 'Collateral_Value': None}], 'Rejected', 'MODEL'),
    'soft_review': ('SOFT rule review (S01 new to credit)',
                    [{**BASE, 'Loan_ID': 'DEMO-SOFT', 'Applicant_ID': 'DEMO-A4', 'CIBIL_Score': -1}],
                    'Human Review', 'RULE'),
    'low_confidence': ('Low-confidence review (uncertain leaf)',
                       [{**BASE, 'Loan_ID': 'DEMO-LOWCONF', 'Applicant_ID': 'DEMO-A5', 'CIBIL_Score': 720,
                         'Work_Experience': 5, 'Monthly_Income': 80000, 'Loan_Type': 'Personal',
                         'Loan_Amount': 300000, 'Loan_Tenure': 36, 'Collateral_Value': None}], 'Human Review', 'MODEL'),
    'lock': ('Duplicate collateral (FR-10 lock)',
             [{**BASE, 'Loan_ID': 'DEMO-LOCK-1', 'Applicant_ID': 'DEMO-A6', 'Collateral_ID': 'DEMO-FLAT-101'},
              {**BASE, 'Loan_ID': 'DEMO-LOCK-2', 'Applicant_ID': 'DEMO-A7', 'Collateral_ID': 'DEMO-FLAT-101'}],
             'Human Review', 'RULE'),
    'malformed': ('Malformed input (graceful reject)',
                  [{**BASE, 'Loan_ID': 'DEMO-BAD', 'Applicant_ID': 'DEMO-A8', 'Age': 999, 'Monthly_Income': 'abc'}],
                  'Rejected', 'RULE'),
}


def clean(app: dict) -> dict:
    return {k: v for k, v in app.items() if v is not None}


def run_case(pipeline, name: str) -> dict:
    """Submit the case's applications in order; return the last decision."""
    _, apps, _, _ = CASES[name]
    out = None
    for app in apps:
        out = pipeline.decide(clean(app), batch_id='demo')
    return out
