@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   HeightShiftOSC - PyInstaller Build Script
echo ========================================
echo.

REM Resolve the dynamic version (commit count on main + optional branch suffix)
echo Resolving version from Git...
for /f "usebackq tokens=*" %%i in (`python -c "from version import __version__; print(__version__)"`) do set BUILD_VERSION=%%i
echo Building version: !BUILD_VERSION!
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python and try again.
    pause
    exit /b 1
)

echo [1/5] Checking for PyInstaller...
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install PyInstaller.
        pause
        exit /b 1
    )
) else (
    echo PyInstaller already installed.
)
echo.

echo [2/5] Installing project dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] Some dependencies may have failed to install. Continuing anyway...
)
echo.

echo [3/5] Cleaning previous build artefacts...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
for %%f in (*.spec) do if exist "%%f" del /q "%%f"
echo.

REM Bake the resolved version into _version_baked.py so the frozen exe does
REM not shell out to git at startup. Each subprocess.run from a --windowed
REM build pops a brief console window per call, which is what we are avoiding.
REM repr() handles any special characters in the branch suffix safely.
echo [4/5] Baking version into _version_baked.py...
python -c "from version import __version__ as v, _SHORT_HASH as h; open('_version_baked.py','w',encoding='utf-8').write('VERSION = ' + repr(v) + '\nSHORT_HASH = ' + repr(h) + '\n')"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to bake version.
    if exist "_version_baked.py" del /q "_version_baked.py"
    pause
    exit /b 1
)

echo Building standalone executable with PyInstaller...
set EXE_NAME=HeightShiftOSC_!BUILD_VERSION!

pyinstaller --noconfirm ^
    --onefile ^
    --windowed ^
    --icon "OSC_Scale.ico" ^
    --add-data "OSC_Scale.ico;." ^
    --name "!EXE_NAME!" ^
    main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] PyInstaller build failed!
    echo Temporary files have been preserved for debugging.
    if exist "_version_baked.py" del /q "_version_baked.py"
    pause
    exit /b 1
)

echo.
echo [5/5] Cleaning up temporary files...

REM Delete the baked version file so source-tree runs go back to live git lookups
if exist "_version_baked.py" (
    echo Deleting _version_baked.py...
    del /q "_version_baked.py"
)

REM Delete .spec files (PyInstaller build blueprints)
for %%f in (*.spec) do (
    if exist "%%f" (
        echo Deleting %%f...
        del /q "%%f"
    )
)

REM Delete the build directory (PyInstaller temp files)
if exist "build" (
    echo Deleting build directory...
    rmdir /s /q build
)

REM Delete __pycache__ directories
for /d %%f in (__pycache__) do (
    if exist "%%f" rmdir /s /q "%%f"
)
for /d %%d in (*) do (
    if exist "%%d\__pycache__" rmdir /s /q "%%d\__pycache__"
)

echo.
echo ========================================
echo   Build Complete!
echo ========================================
echo.
echo Executable location: dist\!EXE_NAME!.exe
echo.

if exist "dist\!EXE_NAME!.exe" (
    echo [SUCCESS] !EXE_NAME!.exe created successfully!
) else (
    echo [WARNING] Executable not found in dist folder.
)

echo.
pause
