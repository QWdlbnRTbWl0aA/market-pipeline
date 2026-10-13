"""Saved market research to studio handoffs; no source or LLM credentials."""
from pathlib import Path
import sys
_shared=str(Path(__file__).resolve().parents[2]/'common')
if _shared not in sys.path:sys.path.insert(0,_shared)
