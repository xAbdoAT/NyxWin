@echo off
:: NyxWin Canonical Windows Command Wrapper
:: Usage:
::   nyx                  (Opens interactive terminal GUI menu)
::   nyx build <Project>  (Compiles & packages an iOS IPA)
::   nyx doctor           (Checks all toolchain dependencies)
::   nyx clean            (Cleans build cache)
::   nyx new <type> <name>(Creates a new iOS project)
::   nyx data paths       (Displays runtime and data paths)
::   nyx data migrate     (Safely migrates legacy data to modern layout)

setlocal
set "SCRIPT_DIR=%~dp0"

:: Set PYTHONPATH to include src/ when running from repository root
if exist "%SCRIPT_DIR%src" (
    set "PYTHONPATH=%SCRIPT_DIR%src;%PYTHONPATH%"
)

:: Check for python in PATH or common Windows install paths
set "PY_CMD="
python --version >nul 2>&1 && set "PY_CMD=python"
if "%PY_CMD%"=="" (
    for %%p in (
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Program Files\Python312\python.exe"
        "C:\Program Files\Python311\python.exe"
    ) do (
        if exist %%p (
            set "PY_CMD=%%~p"
            goto :found_python
        )
    )
)

:found_python
if "%PY_CMD%"=="" (
    echo [ERROR] Python 3.10+ not found in PATH or standard directories.
    echo Run install.bat to automatically install all dependencies!
    pause
    exit /b 1
)

:: Invoke canonical nyxwin module
"%PY_CMD%" -m nyxwin %*
exit /b %ERRORLEVEL%
