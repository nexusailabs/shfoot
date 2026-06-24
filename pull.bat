@echo off
REM Pull Claude's latest reply and print it.
cd /d "%~dp0"
git pull --no-edit
echo.
echo ===================== _chat\REPLY.md =====================
type _chat\REPLY.md
echo ==========================================================
pause
