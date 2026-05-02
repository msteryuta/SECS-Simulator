"""Pytest configuration — adds SECS_Simulator root to sys.path."""
import sys
from pathlib import Path

# Allow bare imports like `from core.secs_codec import ...`
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
