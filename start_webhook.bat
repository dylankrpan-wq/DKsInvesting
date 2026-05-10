@echo off
REM TradingView webhook receiver. Listens on port 8502.
REM Expose to TradingView via:  ngrok http 8502   then use https://xxxx.ngrok-free.app/tv-alert
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
uv run python -m dk.server.webhook
pause
