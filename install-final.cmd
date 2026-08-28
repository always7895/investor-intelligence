@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-final.ps1" -CreateDesktopShortcut
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo Investor Intelligence installation failed with exit code %EXITCODE%.
  pause
)
exit /b %EXITCODE%
