import numpy as np
import pandas as pd
import pytest

from cognilend.explain.counterfactual import (
    FeatureSpec, find_counterfactuals, max_approvable_amount,
)


def fake_model(df: pd.DataFrame) -> np.ndarray:
    """Approval prob rises with income, falls with debt and loan amount."""
    z = (df["income"] - 0.6 * df["debt"] - 0.3 * df["loan_amount"]) / 100_000
    return 1 / (1 + np.exp(-z))


APPLICANT = {"income": 300_000, "debt": 200_000, "loan_amount": 800_000, "age": 30}
SPECS = [
    FeatureSpec("income", 300_000, 1_200_000, 25_000, "increase"),
    FeatureSpec("debt", 0, 200_000, 10_000, "decrease"),
    FeatureSpec("loan_amount", 50_000, 800_000, 25_000, "decrease"),
]


def test_already_approved_returns_nothing():
    rich = {**APPLICANT, "income": 2_000_000}
    res = find_counterfactuals(fake_model, rich, SPECS)
    assert res.already_approved and res.counterfactuals == []


def test_counterfactuals_flip_decision():
    res = find_counterfactuals(fake_model, APPLICANT, SPECS)
    assert res.original_probability < 0.5
    assert res.counterfactuals
    for cf in res.counterfactuals:
        row = {**APPLICANT, **{k: v[1] for k, v in cf.changes.items()}}
        assert fake_model(pd.DataFrame([row]))[0] >= 0.5


def test_only_actionable_features_change():
    res = find_counterfactuals(fake_model, APPLICANT, SPECS)
    allowed = {s.name for s in SPECS}
    for cf in res.counterfactuals:
        assert set(cf.changes) <= allowed
        assert "age" not in cf.changes


def test_direction_and_bounds_respected():
    res = find_counterfactuals(fake_model, APPLICANT, SPECS)
    for cf in res.counterfactuals:
        for feat, (old, new) in cf.changes.items():
            spec = next(s for s in SPECS if s.name == feat)
            assert spec.min_value <= new <= spec.max_value
            if spec.direction == "increase":
                assert new > old
            if spec.direction == "decrease":
                assert new < old


def test_results_are_minimal_and_sorted():
    res = find_counterfactuals(fake_model, APPLICANT, SPECS, max_features=3, top_k=5)
    sets = [frozenset(c.changes) for c in res.counterfactuals]
    for i, a in enumerate(sets):
        for j, b in enumerate(sets):
            assert i == j or not a < b
    costs = [c.cost for c in res.counterfactuals]
    assert costs == sorted(costs)


def test_max_approvable_amount():
    amt = max_approvable_amount(fake_model, APPLICANT, "loan_amount", 50_000, 800_000)
    assert amt is not None
    ok = pd.DataFrame([{**APPLICANT, "loan_amount": amt}])
    over = pd.DataFrame([{**APPLICANT, "loan_amount": amt + 5_000}])
    assert fake_model(ok)[0] >= 0.5 > fake_model(over)[0]


def test_max_approvable_none_when_impossible():
    poor = {**APPLICANT, "income": 0, "debt": 900_000}
    assert max_approvable_amount(fake_model, poor, "loan_amount", 50_000, 800_000) is None


def test_bad_spec_rejected():
    with pytest.raises(ValueError):
        FeatureSpec("income", 0, 10, 1, "sideways")
