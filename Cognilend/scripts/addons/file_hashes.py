"""sha256 of every file under src/, config/, artifacts/, tests/, app/ (regression guard for the max-amount add-on).

    python scripts/addons/file_hashes.py <out.json>
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIRS = ('src', 'config', 'artifacts', 'tests', 'app')
SKIP = ('__pycache__', '.pytest_cache')


def hashes() -> dict:
    out = {}
    for d in DIRS:
        for p in sorted((ROOT / d).rglob('*')):
            if p.is_file() and not any(s in p.parts for s in SKIP):
                out[p.relative_to(ROOT).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


if __name__ == '__main__':
    h = hashes()
    Path(sys.argv[1]).write_text(json.dumps(h, indent=1, sort_keys=True), encoding='utf-8')
    print(f'{len(h)} files hashed -> {sys.argv[1]}')
