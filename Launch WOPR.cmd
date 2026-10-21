@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0WOPR.exe" (
    "%~dp0WOPR.exe" %*
    if errorlevel 1 pause
    exit /b
)
if exist "%~dp0dist\WOPR\WOPR.exe" (
    "%~dp0dist\WOPR\WOPR.exe" %*
    if errorlevel 1 pause
    exit /b
)
rem Source checkout: obey the user's PowerShell policy; never bypass it.
powershell.exe -NoProfile -File "%~dp0windows\Launch-WOPR.ps1" %*
if errorlevel 1 (
    echo.
    echo Source launch failed. See README Windows setup or use the portable ZIP.
    pause
)
