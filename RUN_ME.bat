@echo off
rem CogniLend one-click launcher (Windows). First run creates .venv and installs requirements; later runs just start the app.
rem Each setup step runs only if its output is missing, so a run that failed halfway resumes where it stopped.
cd /d "%~dp0"
title CogniLend

echo ============================================================
echo   CogniLend launcher
echo   First run: 6 steps, about 5-10 minutes. Later runs: seconds.
echo   Keep this window open while you use the app.
echo ============================================================
echo.

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run this again.
  pause
  exit /b 1
)

if exist ".venv\Scripts\python.exe" (
  echo [1/6] Packages already installed - skipping
) else (
  echo [1/6] Installing packages into .venv ^(first run only, 3-5 minutes; pip shows a bar for each download^)...
  %PY% -m venv .venv || goto :fail
  ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
  ".venv\Scripts\python.exe" -m pip install -e . --no-deps || goto :fail
)
set "VPY=.venv\Scripts\python.exe"

if exist "artifacts\models\dt_v1.joblib" (
  echo [2/6] Decision tree already trained - skipping
) else (
  echo.
  echo [2/6] Preparing data and training the decision tree ^(about 1 minute^)...
  "%VPY%" -m cognilend.data.preprocess || goto :fail
  "%VPY%" -m cognilend.ml.tree || goto :fail
)

rem the confidence model is needed by the decision pipeline, so it must exist before seeding
if exist "artifacts\models\confidence_v1.joblib" (
  echo [3/6] Confidence model already trained - skipping
) else (
  echo.
  echo [3/6] Training the confidence model ^(a few seconds^)...
  "%VPY%" -m cognilend.ml.confidence || goto :fail
)

rem demo_cases.json is the last thing seed_demo.py writes, so it marks a completed seed
if exist "artifacts\reports\demo_cases.json" (
  echo [4/6] Database already set up - skipping
) else (
  echo.
  echo [4/6] Creating the database and running the 7 demo cases ^(under a minute^)...
  "%VPY%" scripts\seed_demo.py || goto :fail
)

if exist "artifacts\models\benchmark_models.joblib" (
  echo [5/6] Model comparison already done - skipping
) else (
  echo.
  echo [5/6] Running the model comparison ^(a few minutes; the window may look idle, it is still working^)...
  "%VPY%" -m cognilend.ml.benchmark || goto :fail
)

echo.
echo [6/6] Starting CogniLend. Your browser opens by itself; the address is printed below
echo       ^(normally http://localhost:8501^). Keep this window open - closing it stops the app.
echo.
"%VPY%" -m streamlit run app\streamlit_app.py
exit /b 0

:fail
echo.
echo Setup failed. See the error above, fix it, then double-click RUN_ME.bat again - it resumes where it stopped.
pause
exit /b 1
