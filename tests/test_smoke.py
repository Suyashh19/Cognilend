import importlib

import pytest

from cognilend import config

MODULES = [
    "cognilend", "cognilend.config", "cognilend.pipeline",
    "cognilend.data.contract", "cognilend.data.loaders", "cognilend.data.synthetic", "cognilend.data.preprocess",
    "cognilend.rules.facts", "cognilend.rules.rules", "cognilend.rules.engine",
    "cognilend.ml.entropy", "cognilend.ml.tree", "cognilend.ml.benchmark", "cognilend.ml.confidence",
    "cognilend.ml.explain",
    "cognilend.db.models", "cognilend.db.repository", "cognilend.db.audit", "cognilend.db.lock",
    "cognilend.fairness.disparate_impact",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_configs_load_with_required_keys():
    s = config.load("settings")
    assert s["seed"] == 42
    assert s["split"]["train"] == 0.70
    assert s["tree"] == {"criterion": "entropy", "max_depth": 4, "max_total_nodes": 15,
                         "max_generalization_gap": 0.15, "entropy_tolerance": 1e-9}
    rules = config.load("policies_v1")["rules"]
    assert {r["id"] for r in rules if r["type"] == "HARD"} == {f"R0{i}" for i in range(1, 8)}
    assert {r["id"] for r in rules if r["type"] == "SOFT"} >= {"S01", "S02", "S03"}
    assert config.load("fairness")["min_disparate_impact"] == 0.80
