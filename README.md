# HeightShiftOSC

A desktop application to adjust avatar height in VRChat via OSC messages, allowing real-time scaling of your character from 1 cm to 100 meters.

## Features

- Real-time height adjustment (1 cm - 100 m range)
- Quick-adjust buttons (±1 cm, ±10 cm, ±100 cm)
- Profile system to save/load commonly used heights (4 profiles)
- OSC connection to VRChat (auto-discovered or configurable IP/Port)
- Window geometry persistence
- Dark-themed modern UI

### Advanced Features

- **Startup Mode Selection**: Choose between querying current VRChat height or loading a fixed height on startup
- **Preserve Height on Avatar Switch**: Automatically restore your custom height when switching avatars in VRChat
- **Rapid Burst System**: Sends multiple OSC messages over 2 seconds after avatar swap to ensure height locks properly
- **mDNS Discovery**: Automatically discovers VRChat's OSCQuery and OSC ports via Zeroconf

## Prerequisites

- Python 3.x (3.7 or higher recommended)
- customtkinter
- python-osc package
- zeroconf (for mDNS/Zeroconf auto-discovery of VRChat OSC ports)
- requests (for HTTP queries to VRChat's OSCQuery API)

## Installation

1. Clone or download this repository
2. Install the required Python packages:
   ```bash
   pip install customtkinter python-osc zeroconf requests
   ```
3. Place your custom .ico file (`HeightShiftOSC.ico`) in the project directory
4. Run the application:
   ```bash
   python main.py
   ```

**Note:** The application now uses a provided .ico file instead of automatically converting PNG to ICO. If you don't have a custom icon file, the app will run with a default Windows icon.

## Usage

1. **Launch the application** with `python main.py`
2. **Configure OSC connection**:
   - Enter your VRChat OSC server IP address (default: `127.0.0.1`)
   - Enter the OSC port number (default: `9000`)
   - Click **Connect** to establish the connection
3. **Adjust height**:
   - Use the +/- buttons on the left/right sides for quick adjustments
   - Adjustments are: ±1 cm, ±10 cm, ±100 cm
4. **Save and load profiles**:
    - Click **Save** next to any profile (1-4) to save the current height
    - Click **Load** to restore a saved profile height

## VRChat Setup

1. Open VRChat and go to **Settings** (gear icon)
2. Navigate to the **Network** tab
3. Enable **OSC Server**
4. Configure the port (default is `9000`)
5. Ensure your computer's firewall allows incoming connections on this port

### Automatic Port Discovery

The application automatically discovers VRChat's OSC and OSCQuery ports using mDNS (Zeroconf). If auto-discovery fails, you can manually enter the VRChat IP address and configure the port in the app.

## Configuration

The application stores settings in `HeightShiftOSC_config.json`:
- `osc_ip`: IP address of the VRChat OSC server
- `osc_port`: Port number for OSC communication (auto-discovered via mDNS)
- `height_range`: Minimum and maximum height (in cm)
- `profiles`: Saved height profiles (Profile 1-4)
- `startup_height`: Default height to load on startup (for "Load Fixed Height" mode)
- `startup_mode`: Startup behavior (`query` or `fixed_height`)
- `preserve_height_on_avatar_switch`: Whether to restore height when switching avatars
- `window_geometry`: Window position and size

### Config File Location
- Windows: `%APPDATA%\HeightShiftOSC\HeightShiftOSC_config.json`
- macOS: `~/Library/Application Support/HeightShiftOSC/HeightShiftOSC_config.json`
- Linux: `~/.config/HeightShiftOSC/HeightShiftOSC_config.json`

## OSC Message Details

The application sends OSC messages to VRChat using the following address:

| Field | Value |
|-------|-------|
| **Address** | `/avatar/eyeheight` |
| **Value** | Height in meters (cm ÷ 100) |

### Examples:
| Displayed Height | OSC Value (meters) |
|-----------------|-------------------|
| 1 cm | 0.01 m |
| 100 cm (1 m) | 1.0 m |
| 170 cm (1.7 m) | 1.7 m |
| 10,000 cm (100 m) | 100.0 m |

## Range Notes

- **Minimum height**: 1 cm (0.01 m) - Very small avatar
- **Maximum height**: 100 m (10,000 cm) - Giant avatar
- Default height: 170 cm (1.7 m) - Human average
- Default range in config: [1, 10000] cm (can be modified)

### VRChat Supported Range

VRChat officially supports heights between **10 cm and 100 m**. Values outside this range will show a warning on the HUD.
- **Below 10 cm**: Shows warning, Udon may enforce limits (default min: 20 cm)
- **Above 100 m**: Shows warning, Udon may enforce limits (default max: 5 m)

## Startup Default Size

The application supports saving a default height that loads automatically when the app starts:
- Click **Save** to save the current height as the startup height
- Click **Load** to restore the saved startup height

## Screenshots

![HeightShiftOSC Interface](HeightShiftOSC.png)

## License

This project is licensed under the **GNU GPL v3** (General Public License).

### What this means:
- You can freely use, modify, and distribute this software
- If you distribute modifications or use parts of this code in your own work, you must also release your work under the same GPL v3 license
- Source code must be made available to anyone who receives your modified version

See the `LICENSE` file for the full license text.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

Please ensure all pull requests adhere to the following:
- Follow existing code style
- Add tests if applicable
- Update documentation as needed
