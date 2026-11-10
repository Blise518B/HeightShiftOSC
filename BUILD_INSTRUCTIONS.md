# Build Instructions for HeightShift

## Prerequisites

1. **Python 3.10 or higher**
   - Download from [python.org](https://www.python.org/downloads/)
   - Add Python to your system PATH during installation
2. **PyInstaller** (the build script installs it automatically if missing)
3. **`OSC_Scale.ico`** in the project root. Note: `.gitignore` excludes `*.ico`, so a fresh clone
   doesn't have it — copy it in before building.

## How to build

### Method 1: build.bat (recommended)

1. Open File Explorer and navigate to the project folder
2. Double-click `build.bat`
3. Wait for the build to finish (first run may take a few minutes while
   PyInstaller downloads PySide6's Qt binaries)

The script creates / repairs `venv`, installs PyInstaller and `requirements.txt`, bakes the version
(`_version_baked.py`, removed again afterwards), cleans previous artefacts, and produces a windowed
single-file executable.

### Method 2: manual

```cmd
cd path\to\HeightShift

venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller

venv\Scripts\python.exe -m PyInstaller --onefile --windowed ^
    --icon "OSC_Scale.ico" ^
    --add-data "OSC_Scale.ico;." ^
    --add-data "fonts;fonts" ^
    --name "HeightShift" ^
    main.py
```

`osc/` and `ui/` are ordinary packages; PyInstaller follows the imports from `main.py`.

## Output location

```
dist\HeightShift_<version>.exe      (build.bat)
dist\HeightShift.exe                (manual)
```

## Runtime notes

- The executable is self-contained — Python and PySide6 are bundled
- Settings live in `%APPDATA%\HeightShift\HeightShiftOSC_config.json` (an old `HeightShiftOSC`
  folder is adopted automatically)
- A diagnostics log is written next to it, `%APPDATA%\HeightShift\osc_diagnostics.log`
  (rotated at ~1 MB) — handy for debugging connection issues

## Networking

The HTTP OSCQuery phonebook binds to **127.0.0.1 only**. Windows
Defender otherwise silently drops inbound traffic from VRChat to
sockets bound to `0.0.0.0` unless the user has approved a firewall
rule for the exe. Loopback-bound sockets skip firewall gating
entirely, which matches what VRCFT, VRCOSC and OscGoesPurrr do.

The UDP OSC listener also binds to 127.0.0.1. VRChat-to-OSC traffic is
loopback in 99% of setups; LAN OSC would need a second bind on `0.0.0.0`
in `osc/manager.py` (and an approved firewall rule).

If VRChat isn't routing packets to HeightShift even though the
mDNS handshake succeeded, try:

1. **VRChat → Settings → OSC → Reset** — clears VRChat's OSCQuery cache
2. Close other OSC tools (VRCFT, VRCOSC, OscGoesPurrr) and reconnect
3. Turn on the OSC Router 518 fallback in Settings → Connection
4. Watch `%APPDATA%\HeightShift\osc_diagnostics.log` for the
   silent-connection warnings — the app pings again and re-publishes
   under a fresh mDNS name to self-heal, every 5 minutes while it stays silent
