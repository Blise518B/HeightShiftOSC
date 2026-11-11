@echo off
setlocal enabledelayedexpansion
REM ==========================================================================
REM  Publish a release. GitHub builds it: .github/workflows/release.yml tests
REM  on Windows and Linux, builds HeightShift.exe and the Linux AppImage, and
REM  creates the release v2.0.<commits on main> with both, the VRChat menu
REM  package and the notes from CHANGELOG.md's "## [<version>]" section.
REM  Nothing is built on this PC.
REM
REM  It releases what is on GitHub's main: commit and push first. Needs the
REM  GitHub CLI (gh), signed in.
REM ==========================================================================
cd /d "%~dp0"

git fetch -q origin
if errorlevel 1 (
    echo [ERROR] Could not reach GitHub.
    exit /b 1
)
for /f %%i in ('git rev-list --count origin/main') do set COUNT=%%i
for /f "tokens=2 delims==" %%i in ('findstr /b /c:"BASE_VERSION = " version.py') do set BASE=%%~i
set BASE=!BASE: =!
set BASE=!BASE:"=!
set VERSION=!BASE!.!COUNT!

for /f %%i in ('git rev-list --count origin/main..main 2^>nul') do set AHEAD=%%i
if not "!AHEAD!"=="" if not "!AHEAD!"=="0" (
    echo [WARNING] Your main has !AHEAD! commit^(s^) GitHub doesn't: push them first, or they won't be in v!VERSION!.
)

findstr /b /c:"## [!VERSION!]" CHANGELOG.md >nul
if errorlevel 1 (
    echo [ERROR] CHANGELOG.md has no "## [!VERSION!]" section: the release notes come from it.
    exit /b 1
)

echo Releasing v!VERSION! ^(GitHub's main^) ...
gh workflow run release.yml --repo Blise518B/HeightShiftOSC --ref main -f release=true
if errorlevel 1 exit /b 1
echo.
echo Started. GitHub tests, builds and publishes it in about 10 minutes:
echo   https://github.com/Blise518B/HeightShiftOSC/actions/workflows/release.yml
echo The release appears only if every test and build passed.
