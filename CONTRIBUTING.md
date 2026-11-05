# Contributing to CogniLend

Thanks for helping improve CogniLend. Small contributions are welcome, especially documentation updates, tests, and UI improvements that preserve the explainable decision pipeline.

## Local setup

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
```

On Windows PowerShell, use `scripts\tasks.ps1 setup` instead.

## Useful commands

```bash
make test
make app
make train
```

Run `make test` before opening a pull request. If you change model training, policy configuration, or generated reports, explain the effect in the pull request description.

## Contribution guidelines

- Keep the rule, model, audit, and fairness layers separate.
- Do not use protected attributes as model features.
- Keep the Stress Twin advisory; it must not change a loan decision.
- Add or update tests for behaviour you change.
- Avoid committing local virtual environments, database files, or generated model artifacts unless required.
- Prefer small, focused pull requests with a clear description.

## Pull requests

Please include what changed, checks performed, screenshots for UI changes, and any effect on accuracy, fairness, reproducibility, or audit behaviour.
