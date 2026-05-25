@echo off
echo ========================================
echo   HeightShiftOSC - Build Script
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /b 1
)

echo [1/5] Checking dependencies...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

pip show PySide6 >nul 2>&1
if errorlevel 1 (
    echo Installing PySide6...
    pip install PySide6
)

pip show python-osc >nul 2>&1
if errorlevel 1 (
    echo Installing python-osc...
    pip install python-osc
)

pip show zeroconf >nul 2>&1
if errorlevel 1 (
    echo Installing zeroconf...
    pip install zeroconf
)

pip show requests >nul 2>&1
if errorlevel 1 (
    echo Installing requests...
    pip install requests
)

echo.
echo [2/5] Cleaning previous build files...
if exist build (
    rmdir /s /q build
)
if exist dist (
    rmdir /s /q dist
)
if exist *.spec (
    del *.spec
)

echo.
echo [3/5] Building executable with PyInstaller...
pyinstaller --onefile --windowed ^
    --icon="OSC_Scale.ico" ^
    --add-data "OSC_Scale.ico;." ^
    --name "HeightShiftOSC" ^
    main.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo   BUILD FAILED
    echo ========================================
    pause
    exit /b 1
)

echo.
echo [4/5] Cleaning up temporary files...
rmdir /s /q build
del *.spec

echo.
echo [5/5] Build complete!
echo.
echo ========================================
echo   Build Summary
echo ========================================
echo.
echo Executable location: dist\HeightShiftOSC.exe
echo.
echo ========================================
echo.

pause
