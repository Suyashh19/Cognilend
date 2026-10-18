"""F1: evaluate_without_saving reproduces pipeline.decide with no side effects."""
import math
import sqlite3

import pandas as pd
import pytest
import sqlalchemy

from conftest import BASELINE, ROOT
from cognilend import config, demo
from cognilend.addons import dry_run
from cognilend.addons.dry_run import evaluate_without_saving


def _db_counts() -> dict:
    url = config.load('settings')['paths']['database_url']
    path = config.ROOT / url.replace('sqlite:///', '', 1)
    con = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
    try:
        names = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        return {n: con.execute(f'select count(*) from "{n}"').fetchone()[0] for n in names}
    finally:
        con.close()


def test_matches_baseline_decisions_for_every_test_application(test_set_apps):
    base = pd.read_csv(BASELINE / 'decisions_before.csv', keep_default_na=False)
    assert len(base) == len(test_set_apps)
    mismatches = []
    for app, (_, b) in zip(test_set_apps, base.iterrows()):
        d = evaluate_without_saving(app)
        same = (d['decision'] == b['decision'] and math.isclose(d['confidence'], float(b['confidence']),
                                                                 rel_tol=1e-9, abs_tol=1e-12)
                and ','.join(d['fired_rules']) == b['fired_rules'] and d['source'] == b['source']
                and d['reason'] == b['reason'])
        if not same:
            mismatches.append((b['loan_id'], b['decision'], d['decision']))
    assert not mismatches, f'{len(mismatches)} / {len(base)} differ: {mismatches[:5]}'


def test_no_db_session_no_rows_no_files(test_set_apps, monkeypatch):
    before = _db_counts()
    fallback = ROOT / config.load('settings')['paths']['fallback_log']
    fb_before = fallback.read_bytes() if fallback.exists() else None

    def forbidden(*a, **k):
        raise AssertionError('dry run must not open a database engine')
    monkeypatch.setattr(sqlalchemy, 'create_engine', forbidden)
    monkeypatch.setattr('cognilend.db.repository.create_engine', forbidden)
    apps = test_set_apps[:1000]
    for app in apps:
        evaluate_without_saving(app)
    assert len(apps) == 1000
    assert _db_counts() == before
    assert (fallback.read_bytes() if fallback.exists() else None) == fb_before


@pytest.mark.parametrize('name', list(demo.CASES))
def test_deterministic(name):
    app = demo.clean(demo.CASES[name][1][-1])
    assert evaluate_without_saving(app) == evaluate_without_saving(app)


def test_input_is_not_mutated():
    app = demo.clean(demo.CASES['auto_reject'][1][0])
    snapshot = dict(app)
    evaluate_without_saving(app)
    assert app == snapshot


def test_pipeline_has_no_repository():
    assert dry_run.pipeline().repo is None
