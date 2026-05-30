# HeightShiftOSC

A desktop application to adjust avatar height in VRChat via OSC messages, allowing real-time scaling of your character from 1 cm to 100 meters.

## Features

- Real-time height adjustment (1 cm – 100 m range)
- Quick-adjust buttons (±1 cm, ±10 cm, ±100 cm)
- Slider with a configurable min/max range
- Profile system to save/load commonly used heights (4 profiles)
- Automatic OSC/OSCQuery discovery of VRChat (manual IP override available)
- Window size persistence
- Dark-themed PySide6 (Qt) UI

### Advanced Features

- **Startup Mode Selection**: Choose between querying the current VRChat height or loading a fixed height on startup
- **Preserve Height on Avatar Switch**: Automatically restore your custom height when switching avatars in VRChat
- **Rapid Burst System**: Sends multiple OSC messages over ~2 seconds after an avatar swap to ensure the height locks in properly
- **mDNS Discovery**: Automatically discovers VRChat's OSCQuery and OSC ports via Zeroconf, with a self-healing watchdog for the "connected but no packets" failure mode
- **Hide Console**: Optionally hides the console window on Windows

## Prerequisites

- Python 3.8 or higher
- The packages listed in [`requirements.txt`](requirements.txt):
  - `PySide6` (Qt UI)
  - `python-osc` (OSC messaging)
  - `zeroconf` (mDNS/Zeroconf auto-discovery of VRChat's ports)
  - `requests` (HTTP queries to VRChat's OSCQuery API)

## Installation

1. Clone or download this repository
2. (Recommended) create and activate a virtual environment
3. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the application:
   ```bash
   python main.py
   ```

**Note:** The app looks for an optional icon file named `OSC_Scale.ico` next to `main.py`. If it isn't present, the app runs with a default window icon.

## Usage

1. **Launch the application** with `python main.py`.
2. **OSC connection** — no manual connect step is needed. The app advertises itself via OSCQuery and discovers VRChat automatically over mDNS; the **Local OSC port** and **VRChat OSC port** fields update once VRChat is found.
   - If you need to target a non-default address, type it into the **VRChat IP** field and click **Apply** (default: `127.0.0.1`).
3. **Adjust height**:
   - Use the **+/- buttons** for quick adjustments of ±1 cm, ±10 cm, and ±100 cm.
   - Drag the **slider**, or edit the **Min/Max** boxes to change its range.
   - Click **↻** to re-query VRChat for the current eye height.
4. **Save and load profiles**:
   - Click **Save** next to any profile (1–4) to store the current height.
   - Click **Load** to apply a saved profile height.

## VRChat Setup

1. In VRChat, open the **Action Menu → Options → OSC** and make sure **OSC is enabled**.
2. Leave the port at its default (`9000`) unless you have a specific reason to change it — HeightShiftOSC discovers the active port automatically via OSCQuery.
3. If discovery ever fails, you can set the target address manually with the **VRChat IP** field and **Apply** button.

### Automatic Port Discovery

The application automatically discovers VRChat's OSC and OSCQuery ports using mDNS (Zeroconf). All sockets are bound to `127.0.0.1` (loopback only), which avoids Windows Defender Firewall prompts for inbound traffic.

## Configuration

Settings are stored as JSON and written atomically (so a crash during a save can't corrupt the file). Keys:

- `osc_ip`: IP address of the VRChat OSC target
- `profiles`: Saved height profiles (`profile1`–`profile4`, in cm)
- `startup_mode`: Startup behaviour (`query` or `fixed_height`)
- `startup_height`: Height (cm) to send on startup in `fixed_height` mode
- `slider_min_value` / `slider_max_value`: Configurable slider range (cm)
- `preserve_height_on_avatar_switch`: Whether to restore height when switching avatars
- `hide_console`: Whether to hide the console window on Windows
- `window_geometry`: Last window **size** as `"WIDTHxHEIGHT"`
- `vrchat_discovered_osc_port`: The VRChat OSC port last discovered via mDNS (informational)

### File Locations

| OS | Config | Diagnostics log |
|----|--------|-----------------|
| Windows | `%APPDATA%\HeightShiftOSC\HeightShiftOSC_config.json` | `%APPDATA%\HeightShiftOSC\osc_diagnostics.log` |
| macOS | `~/Library/Application Support/HeightShiftOSC/HeightShiftOSC_config.json` | `~/Library/.../osc_diagnostics.log` |
| Linux | `~/.config/HeightShiftOSC/HeightShiftOSC_config.json` | `~/.config/.../osc_diagnostics.log` |

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

- **Minimum height**: 1 cm (0.01 m) — very small avatar
- **Maximum height**: 100 m (10,000 cm) — giant avatar
- Default height: 170 cm (1.7 m) — human average
- Default slider range: [1, 10000] cm (adjustable via the Min/Max boxes)

### VRChat Supported Range

VRChat officially supports heights between **10 cm and 100 m**. Values outside this range may show a warning on the HUD, and an avatar's Udon logic can enforce its own limits.

## Startup Mode

The **Startup Mode** card controls what the app does when it launches:

- **Query current height** — ask VRChat for the avatar's current eye height and display it.
- **Load fixed height** — send a saved fixed height on startup. Enter the value in the box next to the dropdown.

## Screenshots

![HeightShiftOSC Interface](OSC_Scale.png)

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
- Add tests if applicable (run them with `python -m unittest discover -s tests`)
- Update documentation as needed
