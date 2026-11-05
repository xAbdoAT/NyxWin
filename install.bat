@echo off
:: NyxWin - One-Click Windows Installer & Environment Setup
:: Strictly Native Windows (No macOS / No WSL)

setlocal

echo.
echo   ====================================================
echo     NyxWin - One-Click Installer ^& Environment Setup
echo   ====================================================
echo.

:: Check PowerShell availability
powershell -Command "exit 0" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PowerShell is required to run this installer.
    pause
    exit /b 1
)

:: Launch install.ps1 with ExecutionPolicy Bypass from the script's directory
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Setup encountered an issue. See details above.
    pause
    exit /b 1
)

exit /b 0
