"""
conftest.py — adds phase-04-pulse-synthesis dir to sys.path for pytest.
"""
import sys
from pathlib import Path

_ROOT  = Path(__file__).resolve().parent.parent.parent   # project root
_PHASE = Path(__file__).resolve().parent.parent           # phase-04-pulse-synthesis

for _p in [str(_ROOT), str(_PHASE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
