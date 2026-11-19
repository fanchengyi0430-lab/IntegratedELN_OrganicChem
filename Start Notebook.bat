@echo off
setlocal
cd /d "%~dp0"
title Integrated Notebook for Organic Chemistry

if not exist "nbapp\runtime\python.exe" goto setup
if not exist "nbapp\runtime\RUNTIME.json" goto setup
if exist "nbapp\sketcher\ketcher\index.html" goto run

:setup
echo Setting up the chemistry tools for this copy. The first setup may take a few minutes.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "nbapp\packaging\setup_windows.ps1"
if errorlevel 1 goto failed

:run
echo Starting the notebook. Keep this window open while you work.
"nbapp\runtime\python.exe" -B "nbapp\run.py" %*
if not errorlevel 1 exit /b 0

:failed
echo.
echo The notebook could not start. See the message above.
pause
exit /b 1
