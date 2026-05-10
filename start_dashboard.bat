@echo off
REM Launch the DK Investing dashboard. Opens at http://localhost:8501
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
uv run streamlit run dk/ui/dashboard.py
pause
