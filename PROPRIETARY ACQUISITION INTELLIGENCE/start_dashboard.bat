@echo off
REM ============================================================
REM  Acquisition Intelligence - PRODUCTION launcher
REM  Builds the latest code/data, then serves at localhost:3000
REM  Use this for day-to-day use (fast, stable).
REM ============================================================
cd /d "%~dp0"

if not exist "node_modules" (
  echo Installing dependencies for the first time...
  call npm install
)

echo Building latest version ^(picks up any data/code changes^)...
call npm run build
if errorlevel 1 (
  echo.
  echo BUILD FAILED - see errors above. Not starting the server.
  pause
  exit /b 1
)

echo.
echo Starting dashboard at http://localhost:3000
echo Close this window to stop the dashboard.
start "" http://localhost:3000
call npm run start
pause
