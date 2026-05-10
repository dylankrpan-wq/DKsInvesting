@echo off
REM Run DK Investing data poller every 15 minutes. Keep this window open.
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
uv run python -m dk.jobs.scheduler
pause
