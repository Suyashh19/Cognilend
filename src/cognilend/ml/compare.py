"""Advisory predictions from the benchmark models (Random Forest, XGBoost, Gradient Boosting).

The decision tree stays the only decision-maker; these outputs are shown next to its decision for comparison and are
never written to the audit log. Needs artifacts/models/benchmark_models.joblib (python -m cognilend.ml.benchmark).
"""
from __future__ import annotations

import joblib
import pandas as pd

from cognilend.data import preprocess
from cognilend.ml import tree

NAMES = {'random_forest': 'Random Forest', 'xgboost': 'XGBoost', 'gradient_boosting': 'Gradient Boosting'}


def bundle_path():
    return tree.model_path().with_name('benchmark_models.joblib')


def available() -> bool:
    return bundle_path().exists()


def advise(explainer, application: dict) -> list[dict]:
    """One row per benchmark model: predicted outcome and P(approved) for this application."""
    b = joblib.load(bundle_path())
    row = preprocess.repair_invalid(preprocess.normalise(pd.DataFrame([dict(application)])), historical=False)
    scaled, _ = explainer.matrices(row)
    X = scaled[b['features']]
    out = []
    for name, m in b['models'].items():
        p = float(m.predict_proba(X)[:, 1][0])
        out.append({'model': NAMES.get(name, name), 'prediction': 'Approved' if p >= 0.5 else 'Rejected',
                    'p_approved': p})
    return out
