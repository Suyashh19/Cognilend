param([Parameter(Mandatory)][ValidateSet('setup','all','test','train','reports','seed','app','screens','kpi')][string]$Task)
$py = ".venv\Scripts\python.exe"
switch ($Task) {
  'setup' { python -m venv .venv; & $py -m pip install -r requirements.txt; & $py -m pip install -e . --no-deps }
  'all'   { & $py scripts/run_all.py }
  'test'  { & $py -m pytest }
  'train' { & $py -m cognilend.data.preprocess; if ($?) { & $py -m cognilend.ml.tree } }
  'reports' { & $py -m cognilend.ml.benchmark; & $py -m cognilend.ml.confidence; & $py -m cognilend.ml.explain; & $py scripts/rule_analysis.py; & $py scripts/evaluate_pipeline.py; & $py scripts/reproducibility.py; & $py -m cognilend.fairness.disparate_impact }
  'seed'  { & $py scripts/seed_demo.py }
  'app'   { & $py -m streamlit run app/streamlit_app.py }
  'screens' { & $py scripts/screenshots.py }
  'kpi'   { & $py scripts/lock_load_test.py; & $py scripts/kpi_report.py }
}
