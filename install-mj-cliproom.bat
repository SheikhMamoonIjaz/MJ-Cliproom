@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-mj-cliproom.ps1"
set "INSTALL_EXIT=%ERRORLEVEL%"
if not "%INSTALL_EXIT%"=="0" echo The installer stopped with code %INSTALL_EXIT%.
pause
exit /b %INSTALL_EXIT%
