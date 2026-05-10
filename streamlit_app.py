"""Streamlit Cloud entrypoint — Cloud looks for this file at the repo root.

Just imports and runs the real dashboard module.
"""
from pathlib import Path
import sys

# Make the project root importable
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Import the dashboard — it registers all Streamlit calls at import time
import dk.ui.dashboard  # noqa: F401
