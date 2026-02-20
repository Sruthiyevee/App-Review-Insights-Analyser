"""
conftest.py — adds phase-03-theme-extraction to sys.path so pytest can
import it directly without needing a package named phase_03_theme_extraction.
"""
import sys
from pathlib import Path

# Add: project root and phase dir
_ROOT  = Path(__file__).resolve().parent.parent.parent   # project root
_PHASE = Path(__file__).resolve().parent.parent           # phase-03-theme-extraction

for _p in [str(_ROOT), str(_PHASE)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
