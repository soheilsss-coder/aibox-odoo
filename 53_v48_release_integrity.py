"""Compare v48 against v47 and fail if any prior file disappeared."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
OLD = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if OLD is None or not OLD.exists():
    print('Usage: python3 53_v48_release_integrity.py /path/to/v47/root')
    raise SystemExit(2)
def files(root):
    return {p.relative_to(root) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc'}}
a, b = files(OLD), files(ROOT)
missing = sorted(a-b)
print('v47 files:', len(a)); print('v48 files:', len(b)); print('MISSING:', len(missing))
for p in missing: print('MISSING -', p)
if missing: raise SystemExit(1)
print('PASS - zero v47 files deleted')
