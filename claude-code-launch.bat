@echo off
setlocal EnableExtensions

rem Project root for this Remote Control session.
set "PROJECT_DIR=C:\DIY-Projects\VRC-Coding\HeightShift"

rem Session name includes the machine name so sessions from different machines
rem are easy to tell apart in the Claude Code browser session list.
set "SESSION_NAME=%COMPUTERNAME%-HeightShift"

rem Locate the Claude desktop app's bundled CLI. It is NOT on PATH and lives in a
rem version-numbered folder that changes on every app update, so resolve the
rem newest one at run time (no dependency on PATH).
set "CLAUDE_BASE=%APPDATA%\Claude\claude-code"
set "CLAUDE_EXE="
for /f "delims=" %%D in ('dir /b /ad /o-d "%CLAUDE_BASE%" 2^>nul') do (
    if not defined CLAUDE_EXE if exist "%CLAUDE_BASE%\%%D\claude.exe" set "CLAUDE_EXE=%CLAUDE_BASE%\%%D\claude.exe"
)
if not defined CLAUDE_EXE (
    echo ERROR: Could not find claude.exe under "%CLAUDE_BASE%".
    echo Is the Claude desktop app installed?
    pause
    exit /b 1
)

rem Move into the project root.
cd /d "%PROJECT_DIR%"
if errorlevel 1 (
    echo ERROR: Could not cd into "%PROJECT_DIR%"
    pause
    exit /b 1
)

rem Open the Claude Code web UI.
start "" "https://claude.ai/code"

rem Start the interactive Remote Control session.
"%CLAUDE_EXE%" --remote-control "%SESSION_NAME%"

pause