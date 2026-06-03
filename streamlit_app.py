"""Streamlit Cloud / Railway entry point.

IMPORTANT: Streamlit re-runs this file top-to-bottom on EVERY interaction. If we
used `import dk.ui.dashboard`, Python would cache the module and the dashboard
body would execute only ONCE (first load) — every rerun after that would render
a blank page. That was the recurring "goes dark and blank" bug on hosted setups.

Instead we read + exec the dashboard source fresh on every run, exactly as if
Streamlit were running dashboard.py directly as the main script (which is how it
behaves locally and why local never blanked).
"""
from pathlib import Path
import sys
import traceback

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

# Page config must be the first Streamlit call. dashboard.py also calls it,
# wrapped in try/except, so the duplicate is harmless.
st.set_page_config(
    page_title="DK Investing",
    layout="wide",
    page_icon=":chart_with_upwards_trend:",
    initial_sidebar_state="collapsed",
)

_DASH = _ROOT / "dk" / "ui" / "dashboard.py"

try:
    _code = compile(_DASH.read_text(encoding="utf-8"), str(_DASH), "exec")
    # run_name "__main__" + correct __file__ so dashboard.py's path bootstrap works
    exec(_code, {"__name__": "__main__", "__file__": str(_DASH)})
except Exception as e:
    st.error(f"Dashboard failed to load: **{type(e).__name__}** — {e}")
    st.code(traceback.format_exc(), language="python")
    st.info("Copy this traceback to Claude to patch it. The page won't go blank — "
            "this error box renders even when the dashboard body fails.")
