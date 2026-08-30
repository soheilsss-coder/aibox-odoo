"""Compare a v47 tree against the supplied v46 tree.
Usage: python3 49_v47_release_integrity.py /path/to/v46/root
"""
from pathlib import Path
import hashlib, sys
ROOT = Path(__file__).resolve().parent
OLD = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if OLD is None or not OLD.exists():
    print("Usage: python3 49_v47_release_integrity.py /path/to/v46/root")
    raise SystemExit(2)

def files(root):
    return {p.relative_to(root) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc'} }
a, b = files(OLD), files(ROOT)
missing = sorted(a-b)
print('v46 files:', len(a)); print('v47 files:', len(b)); print('MISSING:', len(missing))
for p in missing: print('MISSING -', p)
if missing: raise SystemExit(1)
print('PASS - zero v46 files deleted')
