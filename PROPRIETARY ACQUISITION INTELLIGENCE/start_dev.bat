@echo off
REM ============================================================
REM  Acquisition Intelligence - DEV launcher (hot reload)
REM  Serves at localhost:3000 and auto-refreshes on any edit.
REM  Use this while editing code or data/listings.ts.
REM ============================================================
cd /d "%~dp0"

if not exist "node_modules" (
  echo Installing dependencies for the first time...
  call npm install
)

echo.
echo Starting DEV server at http://localhost:3000 ^(auto-reloads on save^)
echo Close this window to stop.
start "" http://localhost:3000
call npm run dev
pause
