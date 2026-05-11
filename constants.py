"""
Constants module for HeightShiftOSC

This module contains all application-wide constants to avoid magic numbers
and hardcoded values scattered throughout the code.
"""

VRCHAT_OSC_IP = "127.0.0.1"

# VRChat OSC Configuration
VRCHAT_OSC_PATH = "/avatar/eyeheight"

# Default Config Values
DEFAULT_VRCHAT_OSC_IP = "127.0.0.1"
DEFAULT_STARTUP_HEIGHT_CM = 170
# Default window geometry (loaded from config if available, otherwise fallback)
# Current value from config: 500x715
DEFAULT_WINDOW_GEOMETRY = "500x715"
DEFAULT_PRESERVE_HEIGHT_ON_AVATAR = True
DEFAULT_HIDE_CONSOLE = True

# Height Configuration (in cm)
MIN_HEIGHT_CM = 1
MAX_HEIGHT_CM = 10000
DEFAULT_HEIGHT_CM = 170

# VRChat officially supported range (in cm)
VRCHAT_MIN_HEIGHT_CM = 10
VRCHAT_MAX_HEIGHT_CM = 10000

# Adjustment increments (in cm)
ADJUST_SMALL = 1      # 1 cm
ADJUST_MEDIUM = 10    # 10 cm
ADJUST_LARGE = 100    # 100 cm

# VRChat HTTP Query
VRCHAT_HTTP_TIMEOUT = 2  # seconds
VRCHAT_MDNS_BROWSE_TIMEOUT = 1.5  # seconds

# OSCQuery Configuration
OSCQUERY_APP_NAME = "HeightShiftOSC"

# Application Configuration
APP_NAME = "HeightShiftOSC"
CONFIG_DIR_NAME = "HeightShiftOSC"
CONFIG_FILE_NAME = "HeightShiftOSC_config.json"

# Window Configuration
# Values from config: 500x715
DEFAULT_WINDOW_WIDTH = 500
DEFAULT_WINDOW_HEIGHT = 715

# Profile Configuration
MAX_PROFILES = 4

# Timing Configuration (milliseconds)
VRCHAT_QUERY_DELAY = 100  # ms after UI creation - NOT USED (left for backwards compatibility)

# Rapid Burst Configuration (for avatar change height preservation)
BURST_DURATION = 2.0  # seconds
BURST_INTERVAL = 0.1  # seconds between sends

# Color Configuration (hex)
COLOR_NOT_LOADED = "#ff9900"  # Orange
COLOR_NORMAL_TEXT = "#ffffff"
COLOR_SUCCESS = "#218838"
COLOR_SUCCESS_HOVER = "#1e7e34"
COLOR_PRIMARY = "#0069d9"
COLOR_PRIMARY_HOVER = "#005cbf"
COLOR_DANGER = "#dc3545"
COLOR_DANGER_HOVER = "#c82333"

# Logging Configuration
LOG_FORMAT = "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"