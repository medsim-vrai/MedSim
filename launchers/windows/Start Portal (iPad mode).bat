@echo off
REM medsim portal -- Windows launcher (LAN mode, 0.0.0.0).
REM Use this to access the portal from an iPad/iPhone on the same Wi-Fi.
REM First time only: SmartScreen may warn -- click "More info" then "Run anyway".
REM Windows Firewall will prompt on first run -- allow access on "Private networks".

setlocal enabledelayedexpansion
cd /d "%~dp0..\..\"

REM ---------------------------------------------------------------------------
REM Find a Python 3.11+ interpreter. See the local launcher for the rationale.
REM ---------------------------------------------------------------------------
set "PY="
for %%V in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V --version >nul 2>&1
    if not errorlevel 1 set "PY=py -%%V"
  )
)

if not defined PY (
  py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  echo.
  echo   Error: Python 3.11 or newer is required but was not found.
  echo.
  echo   Install Python 3.11+ from https://www.python.org/downloads/
  echo   ^(check "Add Python to PATH" during installation^), then run
  echo   this launcher again.
  echo.
  pause
  exit /b 1
)

echo Using !PY!
!PY! --version

if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
  if errorlevel 1 (
    echo Existing .venv uses too-old Python -- recreating...
    rmdir /s /q .venv
  )
)

if not exist ".venv\" (
  echo Creating virtual environment with !PY!...
  !PY! -m venv .venv
)

call .venv\Scripts\activate.bat

python -c "import portal.server" 2>nul
if errorlevel 1 (
  echo Installing dependencies ^(one-time, ~30 seconds^)...
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -e ".[serve]"
)

set MEDSIM_HOST=0.0.0.0
python run_portal.py

echo.
pause
endlocal
