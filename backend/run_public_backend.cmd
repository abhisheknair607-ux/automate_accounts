@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_ROOT%\run-logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

cd /d "%SCRIPT_DIR%"
"C:\Users\itsab\anaconda3\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> "%LOG_DIR%\backend-public.log" 2>&1
