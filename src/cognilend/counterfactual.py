"""Counterfactual explanations for CogniLend.

Answers: "What is the smallest realistic change to the applicant's
actionable inputs that would flip a rejection into an approval?"

Design notes
------------
* Model-agnostic: you pass a ``predict_proba`` callable (DataFrame -> array of
  approval probabilities). To explain the FULL hybrid decision (rules + ML),
  wrap your decision pipeline in that callable, not only the ML model.
* Only features listed in ``FeatureSpec`` can change. Never include protected
  or immutable attributes (age, gender, caste, religion, ...).
* Search is a bounded grid search over 1..max_features features, evaluated in
  batches. Results are minimal (no result's feature set contains another's)
  and diverse (one best option per feature set).
* ``max_approvable_amount`` answers "what is the largest loan I'd get?".
* ``dice_counterfactuals`` is an optional wrapper around Microsoft DiCE.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

PredictFn = Callable[[pd.DataFrame], np.ndarray]

SPARSITY_PENALTY = 0.05  # extra cost per changed feature -> prefers fewer changes


@dataclass(frozen=True)
class FeatureSpec:
    """An actionable feature the applicant is allowed to change."""

    name: str
    min_value: float
    max_value: float
    step: float
    direction: str = "both"  # "increase" | "decrease" | "both"
    integer: bool = False

    def __post_init__(self) -> None:
        if self.direction not in {"increase", "decrease", "both"}:
            raise ValueError(f"Bad direction for {self.name}: {self.direction}")
        if self.step <= 0 or self.max_value < self.min_value:
            raise ValueError(f"Bad range/step for {self.name}")

    @property
    def span(self) -> float:
        return (self.max_value - self.min_value) or 1.0

    def candidates(self, current: float, max_candidates: int = 25) -> np.ndarray:
        """Allowed alternative values for this feature, excluding ``current``."""
        values = np.arange(self.min_value, self.max_value + self.step / 2, self.step)
        if self.integer:
            values = np.unique(np.round(values))
        if self.direction == "increase":
            values = values[values > current]
        elif self.direction == "decrease":
            values = values[values < current]
        values = values[values != current]
        if len(values) > max_candidates:
            # Keep the values closest to the current one (cheapest changes).
            order = np.argsort(np.abs(values - current))[:max_candidates]
            values = np.sort(values[order])
        return values


@dataclass
class Counterfactual:
    changes: dict  # feature -> (old, new)
    cost: float
    probability: float  # approval probability after the change

    def to_text(self, labels: Optional[Mapping[str, str]] = None,
                formatters: Optional[Mapping[str, Callable[[float], str]]] = None) -> str:
        labels = labels or {}
        formatters = formatters or {}
        parts = []
        for feat, (old, new) in self.changes.items():
            fmt = formatters.get(feat, lambda v: f"{v:,.2f}".rstrip("0").rstrip("."))
            verb = "increase" if new > old else "reduce"
            parts.append(f"{verb} {labels.get(feat, feat)} from {fmt(old)} to {fmt(new)}")
        return " and ".join(parts)


@dataclass
class CounterfactualResult:
    original_probability: float
    threshold: float
    counterfactuals: list = field(default_factory=list)
    already_approved: bool = False


def make_predict_fn(model, positive_class=1) -> PredictFn:
    """Wrap a scikit-learn style classifier into a ``PredictFn``."""
    idx = list(model.classes_).index(positive_class)

    def _predict(df: pd.DataFrame) -> np.ndarray:
        return np.asarray(model.predict_proba(df))[:, idx]

    return _predict


def find_counterfactuals(
    predict_proba: PredictFn,
    applicant: Mapping,
    specs: Sequence[FeatureSpec],
    threshold: float = 0.5,
    max_features: int = 2,
    top_k: int = 3,
    max_candidates: int = 25,
) -> CounterfactualResult:
    """Find up to ``top_k`` minimal, diverse changes that flip rejection -> approval."""
    row = pd.DataFrame([dict(applicant)])
    base_p = float(predict_proba(row)[0])
    result = CounterfactualResult(original_probability=base_p, threshold=threshold)
    if base_p >= threshold:
        result.already_approved = True
        return result

    found: list[Counterfactual] = []
    solved: list[frozenset] = []

    for k in range(1, max_features + 1):
        for combo in itertools.combinations(specs, k):
            names = frozenset(s.name for s in combo)
            if any(prev <= names for prev in solved):  # keep results minimal
                continue
            grids = [s.candidates(float(row.at[0, s.name]), max_candidates) for s in combo]
            if any(len(g) == 0 for g in grids):
                continue
            mesh = np.meshgrid(*grids, indexing="ij")
            flat = [m.ravel() for m in mesh]
            n = len(flat[0])
            batch = row.loc[row.index.repeat(n)].reset_index(drop=True)
            for s, col in zip(combo, flat):
                batch[s.name] = col
            probs = np.asarray(predict_proba(batch))
            ok = probs >= threshold
            if not ok.any():
                continue
            cost = sum(
                np.abs(col - float(row.at[0, s.name])) / s.span for s, col in zip(combo, flat)
            ) + SPARSITY_PENALTY * k
            best = int(np.argmin(np.where(ok, cost, np.inf)))
            changes = {
                s.name: (float(row.at[0, s.name]), float(col[best]))
                for s, col in zip(combo, flat)
            }
            found.append(Counterfactual(changes, float(cost[best]), float(probs[best])))
            solved.append(names)

    found.sort(key=lambda c: c.cost)
    result.counterfactuals = found[:top_k]
    return result


def max_approvable_amount(
    predict_proba: PredictFn,
    applicant: Mapping,
    amount_feature: str,
    low: float,
    high: float,
    threshold: float = 0.5,
    tolerance: float = 1000.0,
) -> Optional[float]:
    """Largest loan amount in [low, high] that is still approved.

    Assumes approval probability does not increase as the amount grows.
    Returns None if even ``low`` is rejected.
    """

    def approved(amount: float) -> bool:
        row = pd.DataFrame([{**dict(applicant), amount_feature: amount}])
        return float(predict_proba(row)[0]) >= threshold

    if not approved(low):
        return None
    if approved(high):
        return high
    lo, hi = low, high
    while hi - lo > tolerance:
        mid = (lo + hi) / 2
        if approved(mid):
            lo = mid
        else:
            hi = mid
    return lo


def dice_counterfactuals(model, train_df: pd.DataFrame, target: str, continuous: list,
                         applicant_df: pd.DataFrame, features_to_vary: list,
                         permitted_range: Optional[dict] = None, total_cfs: int = 3):
    """Optional: diverse counterfactuals via Microsoft DiCE (pip install dice-ml)."""
    import dice_ml  # lazy import so the rest of the module has no extra dependency

    data = dice_ml.Data(dataframe=train_df, continuous_features=continuous, outcome_name=target)
    wrapped = dice_ml.Model(model=model, backend="sklearn")
    explainer = dice_ml.Dice(data, wrapped, method="random")
    return explainer.generate_counterfactuals(
        applicant_df, total_CFs=total_cfs, desired_class="opposite",
        features_to_vary=features_to_vary, permitted_range=permitted_range,
    )
