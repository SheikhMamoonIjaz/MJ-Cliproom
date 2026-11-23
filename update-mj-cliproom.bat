@echo off
setlocal
title MJ Cliproom 2.0.0 Updater
cd /d "%~dp0"
echo Updating MJ Cliproom to the latest 2.0.0 release...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0update-mj-cliproom.ps1"
set "UPDATE_EXIT=%ERRORLEVEL%"
if not "%UPDATE_EXIT%"=="0" echo The update helper stopped with code %UPDATE_EXIT%.
pause
exit /b %UPDATE_EXIT%
