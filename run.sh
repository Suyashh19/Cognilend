#!/usr/bin/env bash
# CogniLend one-click launcher (macOS / Linux). First run creates .venv and installs requirements; later runs just start the app.
# Each setup step runs only if its output is missing, so a run that failed halfway resumes where it stopped.
# Run with:  ./run.sh   (or: bash run.sh)
set -e
cd "$(dirname "$0")"

trap 'echo; echo "Setup failed. See the error above, fix it, then run ./run.sh again - it resumes where it stopped."' ERR

echo "============================================================"
echo "  CogniLend launcher"
echo "  First run: 6 steps, about 5-10 minutes. Later runs: seconds."
echo "  Keep this terminal open while you use the app."
echo "============================================================"
echo

PY=python3
command -v python3 >/dev/null || PY=python
$PY -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || { echo "Python 3.11 or newer is required."; exit 1; }

if [ -x .venv/bin/python ]; then
  echo "[1/6] Packages already installed - skipping"
else
  echo "[1/6] Installing packages into .venv (first run only, 3-5 minutes; pip shows a bar for each download)..."
  $PY -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python -m pip install -e . --no-deps
fi
VPY=.venv/bin/python

if [ -f artifacts/models/dt_v1.joblib ]; then
  echo "[2/6] Decision tree already trained - skipping"
else
  echo
  echo "[2/6] Preparing data and training the decision tree (about 1 minute)..."
  $VPY -m cognilend.data.preprocess
  $VPY -m cognilend.ml.tree
fi

# the confidence model is needed by the decision pipeline, so it must exist before seeding
if [ -f artifacts/models/confidence_v1.joblib ]; then
  echo "[3/6] Confidence model already trained - skipping"
else
  echo
  echo "[3/6] Training the confidence model (a few seconds)..."
  $VPY -m cognilend.ml.confidence
fi

# demo_cases.json is the last thing seed_demo.py writes, so it marks a completed seed
if [ -f artifacts/reports/demo_cases.json ]; then
  echo "[4/6] Database already set up - skipping"
else
  echo
  echo "[4/6] Creating the database and running the 7 demo cases (under a minute)..."
  $VPY scripts/seed_demo.py
fi

if [ -f artifacts/models/benchmark_models.joblib ]; then
  echo "[5/6] Model comparison already done - skipping"
else
  echo
  echo "[5/6] Running the model comparison (a few minutes; the terminal may look idle, it is still working)..."
  $VPY -m cognilend.ml.benchmark
fi

trap - ERR
echo
echo "[6/6] Starting CogniLend. Your browser opens by itself; the address is printed below"
echo "      (normally http://localhost:8501). Keep this terminal open - Ctrl+C stops the app."
echo
$VPY -m streamlit run app/streamlit_app.py
