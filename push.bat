@echo off
REM Push your _chat files to GitHub so Claude can read them.
cd /d "%~dp0"
set "MSG=%*"
if "%MSG%"=="" set "MSG=ask"
git add -A
git commit -m "%MSG%" 2>nul
echo Syncing...
git pull --rebase --no-edit
git push
echo.
echo Pushed. Wait ~1-5 min, then run pull.bat for the reply.
pause
