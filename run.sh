#!/usr/bin/env bash
# CogniLend one-click launcher (macOS / Linux). First run creates .venv and installs requirements; later runs just start the app.
set -e
cd "$(dirname "$0")"

PY=python3
command -v python3 >/dev/null || PY=python
$PY -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || { echo "Python 3.11 or newer is required."; exit 1; }

if [ ! -x .venv/bin/python ]; then
  echo "[1/2] Creating virtual environment and installing requirements (first run only)..."
  $PY -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python -m pip install -e . --no-deps
fi

if [ ! -f artifacts/models/dt_v1.joblib ]; then
  echo "Training models and seeding the database..."
  .venv/bin/python -m cognilend.data.preprocess
  .venv/bin/python -m cognilend.ml.tree
  .venv/bin/python scripts/seed_demo.py
fi

echo "[2/2] Starting CogniLend at http://localhost:8501 (Ctrl+C to stop)"
.venv/bin/python -m streamlit run app/streamlit_app.py
