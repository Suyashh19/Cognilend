@echo off
rem CogniLend one-click launcher (Windows). First run creates .venv and installs requirements; later runs just start the app.
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run this again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Creating virtual environment and installing requirements ^(first run only, a few minutes^)...
  %PY% -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
  ".venv\Scripts\python.exe" -m pip install -e . --no-deps || goto :fail
)

if not exist "artifacts\models\dt_v1.joblib" (
  echo Training models and seeding the database...
  ".venv\Scripts\python.exe" -m cognilend.data.preprocess || goto :fail
  ".venv\Scripts\python.exe" -m cognilend.ml.tree || goto :fail
  ".venv\Scripts\python.exe" scripts\seed_demo.py || goto :fail
)

if not exist "artifacts\models\benchmark_models.joblib" (
  echo Running the model comparison and confidence step ^(first run only, a few minutes^)...
  ".venv\Scripts\python.exe" -m cognilend.ml.benchmark || goto :fail
  ".venv\Scripts\python.exe" -m cognilend.ml.confidence || goto :fail
)

echo [2/2] Starting CogniLend at http://localhost:8501 ^(close this window to stop^)
".venv\Scripts\python.exe" -m streamlit run app\streamlit_app.py
exit /b 0

:fail
echo Setup failed. See the error above.
pause
exit /b 1
