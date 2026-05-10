"""Streamlit Cloud entrypoint.

Strategy: set page config + render a visible breadcrumb FIRST, then attempt
to import the dashboard. If anything goes wrong, the breadcrumb persists and
the full traceback renders in the page so we can see what broke.
"""
from pathlib import Path
import sys
import traceback

# Bootstrap project root onto sys.path BEFORE any dk.* imports
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Streamlit must be the very first thing we touch so set_page_config works
import streamlit as st

st.set_page_config(
    page_title="DK Investing",
    layout="wide",
    page_icon=":chart_with_upwards_trend:",
    initial_sidebar_state="collapsed",
)

# Visible breadcrumb so we always see SOMETHING even if dashboard import fails
_status = st.empty()
_status.info("Loading DK Investing dashboard...")

try:
    import dk.ui.dashboard  # noqa: F401
    _status.empty()
except Exception as e:
    _status.empty()
    st.error(f"Dashboard failed to load: **{type(e).__name__}** — {e}")
    st.code(traceback.format_exc(), language="python")
    st.markdown(
        "### What to do\n"
        "Copy the traceback above and paste it back to Claude — they'll patch the issue.\n\n"
        "Most common causes on Streamlit Cloud:\n"
        "- A Python package is missing from `requirements.txt`\n"
        "- A Python 3.14 compatibility issue with one of the dependencies\n"
        "- Read/write permission to `data/dk.db` (Cloud's filesystem is partly read-only)\n"
    )
