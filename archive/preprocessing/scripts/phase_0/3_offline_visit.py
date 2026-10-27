"""
Method 3: Offline / primary-data feasibility study

This script records the QUESTIONS and OUTCOME of a proposed academic
data-collection interaction. It does not fabricate bank records.

Use this as a template for documenting an actual visit/call/email.
Replace status/notes only with facts that really occurred.
"""

questions = [
    "Does the institution collect applicant income and employment information?",
    "Is credit history considered during loan processing?",
    "Is a loan approval/rejection decision recorded?",
    "Can anonymized or aggregated records be shared for academic research?",
    "What privacy/confidentiality restrictions apply to customer data?",
]

# Example documentation structure — update only with real observations.
visit_record = {
    "institution_type": "Bank/financial institution",
    "interaction_type": "Academic enquiry",
    "data_requested": "Anonymized loan application records",
    "requested_fields": [
        "income",
        "employment",
        "loan_amount",
        "credit_history",
        "dependents",
        "loan_status",
    ],
    "data_received": False,
    "reason_for_non_collection": (
        "Customer-level banking records were not available for academic "
        "collection because of confidentiality/privacy restrictions."
    ),
}

print("Questions considered:")
for number, question in enumerate(questions, start=1):
    print(f"{number}. {question}")

print("\nPrimary-data feasibility record:")
for key, value in visit_record.items():
    print(f"{key}: {value}")

print("\nConclusion:")
print("Primary/offline collection would require institutional permission")
print("and an appropriate anonymization/data-sharing process.")
print("Therefore it was not selected as the project dataset source.")
