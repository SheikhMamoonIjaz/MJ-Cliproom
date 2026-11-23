@echo off
setlocal
title MJ Cliproom 2.0.0
set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "PYTHON=%APP_DIR%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%LOCALAPPDATA%\Programs\MJ Cliproom\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%LOCALAPPDATA%\Programs\PeakCut\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
if not defined PEAKCUT_HOST set "PEAKCUT_HOST=127.0.0.1"
if not defined PEAKCUT_PORT set "PEAKCUT_PORT=8766"
set "URL=http://127.0.0.1:%PEAKCUT_PORT%"
set "BROWSER_URL=http://localhost:%PEAKCUT_PORT%"
if not defined PEAKCUT_PUBLIC_URL set "PEAKCUT_PUBLIC_URL=%URL%"
set "PEAKCUT_AUTO_RELOAD=0"

pushd "%APP_DIR%" || exit /b 1
powershell.exe -NoProfile -Command "try { $r=Invoke-RestMethod -Uri '%URL%/healthz' -TimeoutSec 2; if ($r.app -eq 'mj-cliproom') { exit 0 } else { exit 1 } } catch { exit 1 }"
if %ERRORLEVEL% EQU 0 (
  echo MJ Cliproom 2.0.0 is already running. Opening the local workstation...
  start "" "%BROWSER_URL%/app/overview"
  popd
  exit /b 0
)
echo ============================================================
echo   Starting MJ Cliproom 2.0.0 Supervised Workstation
echo   URL: %BROWSER_URL%
echo ============================================================
echo Keep this window open while you use the app. Press Ctrl+C here to stop the server.
start "" /b powershell.exe -NoProfile -WindowStyle Hidden -Command "$until=(Get-Date).AddSeconds(60); do { try { $r=Invoke-RestMethod -Uri '%URL%/healthz' -TimeoutSec 2; if ($r.app -eq 'mj-cliproom') { Start-Process '%BROWSER_URL%/app/overview'; exit 0 } } catch { }; Start-Sleep -Milliseconds 500 } while ((Get-Date) -lt $until); exit 1"
"%PYTHON%" -m studio.launcher
set "SERVER_EXIT=%ERRORLEVEL%"
echo MJ Cliproom 2.0.0 stopped with exit code %SERVER_EXIT%.
pause
popd
exit /b %SERVER_EXIT%
