"""
Constants module for HeightShiftOSC

Holds application-wide constants so magic numbers and theming live in one
place. Colours are aligned with the OscGoesPurrr palette so the two tools
look like a family.
"""

# --- VRChat OSC Configuration ---
VRCHAT_OSC_IP = "127.0.0.1"
VRCHAT_OSC_PATH = "/avatar/eyeheight"
VRCHAT_AVATAR_CHANGE_PATH = "/avatar/change"
VRC_DEFAULT_PORT = 9000

# --- Default Config Values ---
DEFAULT_VRCHAT_OSC_IP = "127.0.0.1"
DEFAULT_STARTUP_HEIGHT_CM = 170
DEFAULT_WINDOW_GEOMETRY = "560x780"
DEFAULT_PRESERVE_HEIGHT_ON_AVATAR = True
DEFAULT_HIDE_CONSOLE = True

# --- Height Configuration (in cm) ---
MIN_HEIGHT_CM = 1
MAX_HEIGHT_CM = 10000
DEFAULT_HEIGHT_CM = 170

# VRChat's officially supported range
VRCHAT_MIN_HEIGHT_CM = 10
VRCHAT_MAX_HEIGHT_CM = 10000

# Adjustment increments (in cm)
ADJUST_SMALL = 1
ADJUST_MEDIUM = 10
ADJUST_LARGE = 100

# --- Network Timeouts ---
VRCHAT_HTTP_TIMEOUT = 2.0
VRCHAT_MDNS_BROWSE_TIMEOUT = 1.5

# --- Application Identity ---
APP_NAME = "HeightShiftOSC"
CONFIG_DIR_NAME = "HeightShiftOSC"
CONFIG_FILE_NAME = "HeightShiftOSC_config.json"

# --- Window Configuration ---
DEFAULT_WINDOW_WIDTH = 560
DEFAULT_WINDOW_HEIGHT = 780

# --- Profile Configuration ---
MAX_PROFILES = 4

# --- Rapid Burst Configuration (avatar-change height preservation) ---
BURST_DURATION = 2.0
BURST_INTERVAL = 0.1

# --- OSC Manager Diagnostics Thresholds ---
DIAG_LOG_INTERVAL_S = 30.0
SILENT_THRESHOLD_S = 15.0
SILENT_REPROBE_S = 45.0
SILENT_REREGISTER_S = 75.0
BROWSER_REFRESH_S = 5.0
HEALTH_CHECK_INTERVAL_S = 5.0

LOG_FILE_NAME = "osc_diagnostics.log"
LOG_FILE_MAX_BYTES = 1_000_000

# --- Theme (matches OscGoesPurrr palette) ---
COLOR_PRIMARY = "#7C4DFF"
COLOR_PRIMARY_HOVER = "#6A3DEC"

COLOR_ALERT = "#FF1150"
COLOR_ALERT_HOVER = "#DD0E45"
COLOR_DANGER = COLOR_ALERT
COLOR_DANGER_HOVER = COLOR_ALERT_HOVER

COLOR_SUCCESS = "#07FF77"
COLOR_SUCCESS_HOVER = "#06DD66"

COLOR_LIVE = "#FF3D7F"
COLOR_LIVE_DIM = "#7A1E3F"
COLOR_WARNING = "#FF7300"
COLOR_WARNING_DIM = "#7A3700"
COLOR_SUCCESS_DIM = "#073D24"
COLOR_ALERT_DIM = "#5A0820"

COLOR_BG = "#0D0924"
COLOR_SURFACE = "#1D1553"
COLOR_SURFACE_HOVER = "#2A2070"

COLOR_BUTTON = "#3A2C8C"
COLOR_BUTTON_HOVER = "#4D3CB3"

COLOR_INPUT_BG = "#1A1240"
COLOR_INPUT_BORDER = "#3A2C8C"
COLOR_INPUT_FOCUS = "#9A7BFF"

COLOR_TEXT = "#FFFFFF"
COLOR_TEXT_MUTED = "#9A9AB8"

# Legacy names still referenced by code that hasn't migrated yet
COLOR_NOT_LOADED = COLOR_WARNING
COLOR_NORMAL_TEXT = COLOR_TEXT

# --- Logging ---
LOG_FORMAT = "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
