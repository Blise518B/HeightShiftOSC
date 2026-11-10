@echo off
title HeightShift
setlocal

:: Change to script directory so relative paths work no matter where the
:: .bat is launched from.
cd /d "%~dp0"

:: Prefer the 'py' launcher (a real python.org install) over bare
:: 'python' (often the Microsoft Store stub that builds broken venvs).
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Error: Python is not installed or not on PATH.
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

echo Starting HeightShift...
echo.

:: Validate the venv, (re)creating it if missing or broken.
set "VENV_PY=venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys" >nul 2>&1 || (
        echo Existing virtual environment is broken; recreating...
        rmdir /s /q "venv"
    )
)
if not exist "%VENV_PY%" (
    if exist "venv" rmdir /s /q "venv"
    echo Creating virtual environment...
    %PY% -m venv venv
    if errorlevel 1 (
        echo Error: Could not create virtual environment.
        pause
        exit /b 1
    )
)

echo Installing/updating dependencies...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Warning: Could not install dependencies. Trying to continue anyway...
    echo.
)

echo Launching HeightShift...
"%VENV_PY%" main.py
:: Pause only when something went wrong. The app hides this console when
:: "Hide the console window" is on and always shows it again on exit, so an
:: error stays readable; a normal exit just closes the window (the old
:: unconditional pause left an invisible cmd.exe waiting after every run).
if errorlevel 1 (
    echo.
    echo HeightShift exited with an error - see above.
    pause
)
