"""Shared fixtures for the max-approvable-amount add-on tests."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / 'scripts', ROOT / 'scripts' / 'addons'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

BASELINE = ROOT / 'reports' / 'baseline'


@pytest.fixture(scope='session')
def test_set_apps() -> list[dict]:
    """TEST-split applications exactly as decide_many sees them (NaN fields dropped)."""
    from evaluate_pipeline import test_applications
    df, _ = test_applications()
    return [{k: v for k, v in r.items() if not (v is None or (isinstance(v, float) and np.isnan(v)))}
            for r in df.to_dict('records')]
