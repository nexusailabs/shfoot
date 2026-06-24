@echo off
REM ============================================================
REM  shfoot one-shot setup for WINDOWS (Command Prompt).
REM  Double-click this file, or run:  setup.bat
REM  Safe to re-run. Core sanity checks ALWAYS run, even if the
REM  strands/boto3 install fails (the win-core is pure stdlib).
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ============================================
echo  [shfoot] Windows setup
echo ============================================

REM --- locate Python (py launcher preferred, else python) ---
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo [FATAL] Python not found. Install Python 3.11+ from https://python.org
  echo         ^(check "Add python.exe to PATH" during install^), then re-run.
  pause & exit /b 1
)
echo Using Python: %PY%
%PY% --version

REM --- create venv if missing ---
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual env .venv ...
  %PY% -m venv .venv || ( echo [FATAL] venv creation failed & pause & exit /b 1 )
)
set "VPY=.venv\Scripts\python.exe"

REM --- install deps (warn-and-continue: core does not need them) ---
echo Installing deploy deps ^(strands-agents, boto3^)...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [WARN] dep install FAILED ^(network/proxy/pin?^). squad.py deploy will not work
  echo        until fixed, but the decision CORE below still runs. Try later:
  echo            .venv\Scripts\python -m pip install strands-agents boto3
  echo.
)

REM --- sanity checks: ALWAYS run, pure stdlib ---
echo ============================================
echo  Sanity checks ^(must say GREEN / OK^)
echo ============================================
"%VPY%" reconcile.py
"%VPY%" -m unittest test_policy

echo.
echo ============================================
echo  DONE.
echo  Activate later:   .venv\Scripts\activate
echo  Schema-check a portal observation from the clipboard ^(PowerShell^):
echo      Get-Clipboard ^| .venv\Scripts\python reconcile.py -
echo ============================================
pause
