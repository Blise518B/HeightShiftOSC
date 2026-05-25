# Build Instructions for HeightShiftOSC

## Prerequisites

1. **Python 3.9 or higher** (PySide6 requires it)
   - Download from [python.org](https://www.python.org/downloads/)
   - Add Python to your system PATH during installation
2. **PyInstaller** (the build script installs it automatically if missing)
3. **`OSC_Scale.ico`** — already shipped in the project root

## How to build

### Method 1: build.bat (recommended)

1. Open File Explorer and navigate to the project folder
2. Double-click `build.bat`
3. Wait for the build to finish (first run may take a few minutes while
   PyInstaller downloads PySide6's Qt binaries)

The script installs PyInstaller + PySide6 + python-osc + zeroconf +
requests on demand, cleans previous artefacts, and produces a windowed
single-file executable.

### Method 2: manual

```cmd
cd path\to\HeightShiftOSC

pip install -r requirements.txt pyinstaller

pyinstaller --onefile --windowed ^
    --icon="OSC_Scale.ico" ^
    --add-data "OSC_Scale.ico;." ^
    --name "HeightShiftOSC" ^
    main.py
```

## Output location

```
dist\HeightShiftOSC.exe
```

## Runtime notes

- The executable is self-contained — Python and PySide6 are bundled
- Settings live under `%APPDATA%\HeightShiftOSC\HeightShiftOSC_config.json`
- A diagnostics log is written to `%APPDATA%\HeightShiftOSC\osc_diagnostics.log`
  (rotated at ~1 MB) — handy for debugging connection issues

## Networking

The HTTP OSCQuery phonebook binds to **127.0.0.1 only**. Windows
Defender otherwise silently drops inbound traffic from VRChat to
sockets bound to `0.0.0.0` unless the user has approved a firewall
rule for the exe. Loopback-bound sockets skip firewall gating
entirely, which matches what VRCFT and VRCOSC do.

The UDP OSC listener also binds to 127.0.0.1. VRChat-to-OSC traffic is
loopback in 99% of setups; if you need LAN OSC you'll need to edit
`osc_manager.py` and add a secondary bind on `0.0.0.0` (and approve a
firewall rule).

If VRChat isn't routing packets to HeightShiftOSC even though the
mDNS handshake succeeded, try:

1. **VRChat → Settings → OSC → Reset** — clears VRChat's OSCQuery cache
2. Close other OSC tools (VRCFT, VRCOSC, OscGoesPurrr) and reconnect
3. Watch `%APPDATA%\HeightShiftOSC\osc_diagnostics.log` for the
   silent-connection warnings — the manager will eventually
   re-publish under a fresh mDNS name to self-heal
