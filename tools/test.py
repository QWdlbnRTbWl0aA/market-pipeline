#!/usr/bin/env python3
"""Run components separately: test module names cannot collide across services."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
failures=0
for name in ('collector','analyzer','product','controller','studio'):
 directory=ROOT/'services'/name
 result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=directory)
 failures+=result.returncode!=0
result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=ROOT)
raise SystemExit(1 if failures or result.returncode else 0)
