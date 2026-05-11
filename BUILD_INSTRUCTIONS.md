# Build Instructions for HeightShiftOSC

## Prerequisites

Before building the executable, ensure you have the following installed:

1. **Python** (version 3.7 or higher)
   - Download from [python.org](https://www.python.org/downloads/)
   - Make sure Python is added to your system PATH during installation

2. **PyInstaller** (installed automatically by build.bat)
   - This build script will install PyInstaller if not already present

3. **Your custom .ico file**
   - Place your high-quality `OSC_Scale.ico` file in the project directory before building
   - The app uses your provided `.ico` file for the executable icon

## How to Build

### Method 1: Using the Build Script (Recommended)

1. Open File Explorer and navigate to the project folder
2. Double-click `build.bat`
3. Wait for the build to complete (this may take a few minutes)

The build script will:
- Check if Python is installed
- Install required dependencies (PyInstaller, customtkinter, python-osc, zeroconf)
- Clean previous build files
- Create the standalone executable with your custom icon
- Remove temporary build files

### Method 2: Manual Build

If you prefer to build manually, run these commands in Command Prompt:

```cmd
cd path\to\project

# Install dependencies
pip install pyinstaller customtkinter python-osc zeroconf requests

# Build the executable
pyinstaller --onefile --windowed ^
    --icon="OSC_Scale.ico" ^
    --name "HeightShiftOSC" ^
    main.py
```

## Output Location

The final executable will be located at:
```
dist\HeightShiftOSC.exe
```

## Notes

- The first build may take longer as dependencies are downloaded
- The executable is self-contained and doesn't require Python to be installed on the target machine
- The config file will be created in `%APPDATA%\HeightShiftOSC\` on first run

## Firewall Configuration

To allow VRChat OSC communication, ensure your firewall permits:
- **UDP outbound** to VRChat's OSC port (commonly 9000)
- **UDP inbound** on a random high port for receiving OSC messages (auto-discovered via mDNS)

The application automatically discovers VRChat's OSC and OSCQuery ports using mDNS. If auto-discovery fails, ensure your firewall allows outbound connections to common VRChat ports.

If VRChat cannot connect to your computer, check your firewall settings.
