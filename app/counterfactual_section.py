"""Streamlit snippet: drop into the decision-result page of the app.

Adapt FEATURE_SPECS to CogniLend's real column names and ranges, and make
`predict_fn` call the full hybrid decision (rules + ML), not just the ML model.
"""
import streamlit as st

from cognilend.explain.counterfactual import (
    FeatureSpec, find_counterfactuals, max_approvable_amount,
)

FEATURE_SPECS = [  # TODO: replace with real column names / realistic bounds
    FeatureSpec("annual_income", 0, 5_000_000, 10_000, "increase"),
    FeatureSpec("existing_debt", 0, 2_000_000, 5_000, "decrease"),
    FeatureSpec("loan_amount", 10_000, 2_000_000, 10_000, "decrease"),
    FeatureSpec("loan_term_months", 6, 84, 6, "both", integer=True),
]
LABELS = {
    "annual_income": "annual income", "existing_debt": "existing debt",
    "loan_amount": "loan amount", "loan_term_months": "loan term (months)",
}
FORMATTERS = {
    "annual_income": lambda v: f"₹{v:,.0f}", "existing_debt": lambda v: f"₹{v:,.0f}",
    "loan_amount": lambda v: f"₹{v:,.0f}", "loan_term_months": lambda v: f"{v:.0f}",
}


def render_counterfactual_section(predict_fn, applicant: dict, threshold: float = 0.5):
    st.subheader("What would get you approved?")
    with st.spinner("Searching for the smallest changes..."):
        res = find_counterfactuals(predict_fn, applicant, FEATURE_SPECS, threshold)
    if res.already_approved:
        st.success("Approved. No changes needed.")
    elif not res.counterfactuals:
        st.warning("No realistic change to the adjustable inputs flips this decision.")
    else:
        st.caption(f"Current approval score: {res.original_probability:.0%} (needs {threshold:.0%})")
        for i, cf in enumerate(res.counterfactuals, 1):
            st.markdown(f"**Option {i}:** {cf.to_text(LABELS, FORMATTERS)}  \n"
                        f"→ approval score {cf.probability:.0%}")
    cap = max_approvable_amount(predict_fn, applicant, "loan_amount", 10_000,
                                applicant["loan_amount"], threshold)
    if not res.already_approved:
        st.info(f"Largest amount likely to be approved: ₹{cap:,.0f}" if cap
                else "No loan amount in the allowed range is currently approvable.")
    st.caption("Suggestions are explanations of the model, not a guarantee of approval.")
