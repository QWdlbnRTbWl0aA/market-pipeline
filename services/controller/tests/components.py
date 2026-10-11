from pathlib import Path
import sys
BASE=Path(__file__).resolve().parents[2]
ROOTS={name:BASE/name for name in ('collector','analyzer','product')}
for root in ROOTS.values():sys.path.insert(0,str(root))
