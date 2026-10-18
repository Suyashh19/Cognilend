# Unix / Git Bash. On Windows PowerShell use scripts/tasks.ps1 <setup|test|train|reports|seed|app|screens|kpi>.
PY ?= .venv/Scripts/python
.PHONY: setup all test train reports seed app screens kpi
setup:
	python -m venv .venv && $(PY) -m pip install -r requirements.txt && $(PY) -m pip install -e . --no-deps
all:
	$(PY) scripts/run_all.py
test:
	$(PY) -m pytest
train:
	$(PY) -m cognilend.data.preprocess && $(PY) -m cognilend.ml.tree
reports:
	$(PY) -m cognilend.ml.benchmark && $(PY) -m cognilend.ml.confidence && $(PY) -m cognilend.ml.explain && $(PY) scripts/rule_analysis.py \n		&& $(PY) scripts/evaluate_pipeline.py && $(PY) scripts/reproducibility.py && $(PY) -m cognilend.fairness.disparate_impact
seed:
	$(PY) scripts/seed_demo.py
app:
	$(PY) -m streamlit run app/streamlit_app.py
screens:
	$(PY) scripts/screenshots.py
kpi:
	$(PY) scripts/lock_load_test.py && $(PY) scripts/kpi_report.py
