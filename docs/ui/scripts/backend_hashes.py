"""sha256 of every file OUTSIDE app/ and .streamlit/ (UI-redesign regression guard).

    python docs/ui/scripts/backend_hashes.py write   docs/ui/baseline/backend_hashes.json
    python docs/ui/scripts/backend_hashes.py compare docs/ui/baseline/backend_hashes.json

Excluded: the UI itself (app/, .streamlit/), this redesign's own outputs (docs/ui/, requirements-ui.txt), and
tool folders that are not project files (.git, .venv, caches).

Files are split into two groups:
  source   - everything git tracks, plus trained model artefacts. These must be byte-identical after the redesign.
  runtime  - files the app writes while it is used (the SQLite DB, the fallback log, screenshots, the fairness
             report that the "Rerun fairness audit" button regenerates). They change whenever anyone uses the app
             or runs the test suite (tests write to the project DB), with or without a UI change, so they are
             listed for information only and are not part of the PASS/FAIL check.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXCLUDE_TOP = {'app', '.streamlit', '.git', '.venv', 'requirements-ui.txt'}
EXCLUDE_PARTS = {'__pycache__', '.pytest_cache', '.ipynb_checkpoints'}
RUNTIME_PREFIXES = ('data/processed/', 'artifacts/fallback/', 'artifacts/reports/', 'evidence/max_amount/screens/')
RUNTIME_SUFFIXES = ('.db', '.db-journal', '.db-wal', '.db-shm')
# Model artefacts live in artifacts/reports too (metrics json); they are written only by training, never by the UI.
TRAINED = ('artifacts/models/', 'artifacts/encoders/')


def classify(rel: str) -> str:
    if rel.startswith(TRAINED):
        return 'source'
    if rel.startswith(RUNTIME_PREFIXES) or rel.endswith(RUNTIME_SUFFIXES):
        return 'runtime'
    return 'source'


def hashes() -> dict:
    out = {'source': {}, 'runtime': {}}
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        parts = rel.split('/')
        if parts[0] in EXCLUDE_TOP or rel.startswith('docs/ui/') or EXCLUDE_PARTS & set(parts):
            continue
        out[classify(rel)][rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main():
    mode, path = sys.argv[1], Path(sys.argv[2])
    now = hashes()
    if mode == 'write':
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(now, indent=1, sort_keys=True), encoding='utf-8')
        print(f'{len(now["source"])} source files + {len(now["runtime"])} runtime files hashed -> {path}')
        return
    base = json.loads(path.read_text(encoding='utf-8'))
    b, n = base['source'], now['source']
    changed = sorted(k for k in b if k in n and b[k] != n[k])
    missing = sorted(set(b) - set(n))
    added = sorted(set(n) - set(b))
    print(json.dumps({'source_files_checked': len(b), 'changed': changed, 'missing': missing, 'added': added,
                      'runtime_files_changed (informational)': sorted(
                          k for k in base['runtime'] if now['runtime'].get(k) != base['runtime'][k])},
                     indent=1))
    ok = not (changed or missing or added)
    print('PASS' if ok else 'FAIL')
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
