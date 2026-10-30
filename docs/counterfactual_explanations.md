# Counterfactual Explanations in CogniLend

## What it is
A counterfactual explanation answers: *"What is the smallest change to my inputs that would flip the decision?"*
Example: "Reduce your loan amount from ₹5,00,000 to ₹3,50,000 and your application would be approved."

SHAP/LIME explain **why** (feature importance). Counterfactuals explain **what to change** (actionable recourse).

## Why we need it
- **Explainability:** gives rejected applicants a concrete path, not just "score too low".
- **Regulation / right to explanation:** supports GDPR-style and fair-lending expectations.
- **Fairness auditing:** compare the *cost* of recourse across groups. Systematically larger required changes for one group is a bias signal.
- **Max-approvable:** complements the existing max-approvable-amount work.

## Properties we enforce
| Property | How |
|---|---|
| Validity | Every returned option is re-scored and must reach the threshold |
| Proximity | Cost = sum of range-normalised changes |
| Sparsity | Extra penalty per changed feature; max 2 features by default |
| Actionability | Only features in `FeatureSpec` may change; direction and bounds enforced |
| Plausibility | Bounds and step sizes per feature |
| Diversity / minimality | One best option per feature set; supersets of an already-solved set are skipped |

## Module
`src/cognilend/explain/counterfactual.py`

- `FeatureSpec(name, min_value, max_value, step, direction, integer)`
- `find_counterfactuals(predict_proba, applicant, specs, threshold, max_features, top_k)`
- `max_approvable_amount(predict_proba, applicant, amount_feature, low, high, threshold)`
- `make_predict_fn(model)` wraps a scikit-learn classifier
- `dice_counterfactuals(...)` optional Microsoft DiCE backend (`pip install dice-ml`)

```python
from cognilend.explain.counterfactual import FeatureSpec, find_counterfactuals, make_predict_fn

specs = [FeatureSpec("annual_income", 0, 5_000_000, 10_000, "increase"),
         FeatureSpec("loan_amount", 10_000, 2_000_000, 10_000, "decrease")]
res = find_counterfactuals(make_predict_fn(model), applicant_dict, specs)
for cf in res.counterfactuals:
    print(cf.to_text(), cf.probability)
```

## Hybrid system caveat
CogniLend combines rules and ML. If a hard rule rejects an applicant, changing ML features alone may not help. Pass a `predict_proba` that runs the **entire** decision pipeline (e.g. return 1.0 for approve, 0.0 for reject, or the blended score), so suggestions reflect the real final decision.

## Limitations
- Explains the model, not guaranteed outcomes; the model or policy may change.
- Grid search is bounded; very high-dimensional searches need DiCE or an optimiser.
- Features can be correlated (changing income may change debt-to-income); keep bounds realistic.
- Never include protected or immutable attributes in `FeatureSpec`.

## Testing
`pytest tests/test_counterfactual.py` checks validity, actionability, bounds/direction, minimality, ordering and the max-approvable search.

## Future work
Fairness audit comparing recourse cost across groups; causal constraints (income up implies DTI down); plausibility via nearest-neighbour checks against real data; UI export of recourse as PDF.
