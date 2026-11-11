@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   HeightShift - PyInstaller Build Script
echo ========================================
echo.

REM ------------------------------------------------------------------
REM Resolve a Python launcher (prefer the 'py' launcher over the
REM Microsoft Store 'python' stub) and build / validate a venv. Every
REM python / pip / PyInstaller call below runs through the venv so the
REM build never touches system Python.
REM ------------------------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python not found. Install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

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
        echo [ERROR] Could not create virtual environment.
        pause
        exit /b 1
    )
)

REM Resolve the dynamic version (commit count on main + optional branch suffix)
echo Resolving version from Git...
for /f "usebackq tokens=*" %%i in (`"%VENV_PY%" -c "from version import __version__; print(__version__)"`) do set BUILD_VERSION=%%i
echo Building version: !BUILD_VERSION!
echo.

echo [1/5] Checking for PyInstaller...
"%VENV_PY%" -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller not found. Installing...
    "%VENV_PY%" -m pip install pyinstaller
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
"%VENV_PY%" -m pip install -r requirements.txt
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
"%VENV_PY%" -c "from version import __version__ as v, _SHORT_HASH as h, __build__ as b; open('_version_baked.py','w',encoding='utf-8').write('VERSION = ' + repr(v) + '\nSHORT_HASH = ' + repr(h) + '\nBUILD = ' + repr(b) + '\n')"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to bake version.
    if exist "_version_baked.py" del /q "_version_baked.py"
    pause
    exit /b 1
)

echo Building standalone executable with PyInstaller...
set EXE_NAME=HeightShift_!BUILD_VERSION!

"%VENV_PY%" -m PyInstaller --noconfirm ^
    --onefile ^
    --windowed ^
    --icon "OSC_Scale.ico" ^
    --add-data "OSC_Scale.ico;." ^
    --add-data "fonts;fonts" ^
    --add-data "assets;assets" ^
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
    REM The release asset keeps one name, so the updater (updater.py) and the
    REM links in the README always find it. A release = tag v!BUILD_VERSION!
    REM with dist\HeightShift-Windows.exe and docs\unity\HeightShift-VRCFury.unitypackage.
    copy /y "dist\!EXE_NAME!.exe" "dist\HeightShift-Windows.exe" >nul
    echo Release copy: dist\HeightShift-Windows.exe
) else (
    echo [WARNING] Executable not found in dist folder.
)

echo.
pause
