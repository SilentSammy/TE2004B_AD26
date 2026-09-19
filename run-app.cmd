@echo off
setlocal

set "APP_PYTHON=%LOCALAPPDATA%\TE2004B_AD26\venv\Scripts\python.exe"

if not exist "%APP_PYTHON%" (
    echo The Python environment was not found.
    echo Run setup-desktop.cmd first.
    exit /b 1
)

"%APP_PYTHON%" "%~dp0main.py"
set "APP_EXIT_CODE=%ERRORLEVEL%"

if not "%APP_EXIT_CODE%"=="0" (
    echo.
    echo The application exited with code %APP_EXIT_CODE%.
)

exit /b %APP_EXIT_CODE%
