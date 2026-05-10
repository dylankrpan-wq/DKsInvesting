"""Streamlit Cloud entrypoint — Cloud looks for this file at the repo root.

Wraps the dashboard import in a top-level error guard so any failure
surfaces visibly in the page instead of leaving the user with a blank screen.
"""
from pathlib import Path
import sys
import traceback

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import dk.ui.dashboard  # noqa: F401
except Exception as e:
    import streamlit as st
    st.set_page_config(page_title="DK Investing — startup error", layout="wide")
    st.error(f"Dashboard failed to load: {type(e).__name__}: {e}")
    st.code(traceback.format_exc(), language="python")
    st.info("Once you (or Claude) fix the error, push to GitHub — Streamlit Cloud will auto-redeploy.")

