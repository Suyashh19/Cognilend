"""Snapshot of decide_many on the full TEST split against a fresh, throwaway database (regression guard).

    python scripts/addons/decisions_snapshot.py <out.csv> <counts.json>

Writes the per-application outcome, confidence, reason and fired rules (+ <out.csv>.sha256) and the row count of
every DB table afterwards. The project database (data/processed/cognilend.db) is never touched.
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

from evaluate_pipeline import test_applications  # noqa: E402
from cognilend.db.models import Base  # noqa: E402
from cognilend.db.repository import Repository  # noqa: E402
from cognilend.pipeline import DecisionPipeline  # noqa: E402

COLS = ['loan_id', 'decision', 'confidence', 'reason', 'source', 'fired_rules']


def table_counts(repo) -> dict:
    with repo.Session() as s:
        return {name: s.execute(select(func.count()).select_from(t)).scalar_one()
                for name, t in sorted(Base.metadata.tables.items())}


def run(out_csv: Path, counts_json: Path) -> dict:
    apps, _ = test_applications()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(f'sqlite:///{Path(tmp).as_posix()}/snapshot.db')
        out = DecisionPipeline(repo=repo).decide_many(apps, batch_id='snapshot')
        counts = table_counts(repo)
        repo.engine.dispose()
    out[COLS].to_csv(out_csv, index=False, float_format='%.12g', lineterminator='\n')
    digest = hashlib.sha256(out_csv.read_bytes()).hexdigest()
    out_csv.with_name(out_csv.name + '.sha256').write_text(f'{digest}  {out_csv.name}\n', encoding='utf-8')
    counts_json.write_text(json.dumps(counts, indent=1), encoding='utf-8')
    return {'n': len(out), 'sha256': digest, 'counts': counts}


if __name__ == '__main__':
    print(json.dumps(run(Path(sys.argv[1]), Path(sys.argv[2])), indent=1))
