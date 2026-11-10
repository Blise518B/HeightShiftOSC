"""
Constants module for HeightShift

Holds application-wide constants so magic numbers live in one place.
Colours are NOT here: they come from `ui/theme_tokens.py`, the 518 design
system's token file (copied verbatim from `_hub\\design\\theme_tokens.py`).
"""

# --- VRChat OSC Configuration ---
VRCHAT_OSC_PATH = "/avatar/eyeheight"
VRCHAT_AVATAR_CHANGE_PATH = "/avatar/change"
VRC_DEFAULT_PORT = 9000

# --- Default Config Values ---
DEFAULT_STARTUP_HEIGHT_CM = 170
DEFAULT_PRESERVE_HEIGHT_ON_AVATAR = True
DEFAULT_HIDE_CONSOLE = True
# Subscribe the OSC receive port at the local 518 Hub (fallback for
# VRChat's dying mDNS discovery — see 518Hub/docs/STANDARD.md)
DEFAULT_OSC_ROUTER_518 = True

# --- Height limits (in cm) ---
# Every value the app SENDS is checked against these (height_logic.check_write).
# Values VRChat REPORTS are never clamped: the display always shows the truth.
MIN_HEIGHT_CM = 1            # 1 cm
MAX_HEIGHT_CM = 10_000       # 100 m — VRChat's documented ceiling
# With "Unlock upper limit" ticked. OSC carries the height as a 32-bit float
# in metres; at 100 km its step is still under a centimetre, above that the
# value starts to visibly quantise. VRChat or the world may cap it lower.
UNLOCKED_MAX_HEIGHT_CM = 10_000_000   # 100 km
DEFAULT_HEIGHT_CM = 170

# --- Network Timeouts ---
VRCHAT_HTTP_TIMEOUT = 2.0

# --- Application Identity ---
# Renamed from "HeightShiftOSC" in the family-wide naming pass. The config
# filename keeps its old name inside the renamed folder: it's user data with
# migration handling in config_manager.get_app_config_dir, and churning the filename
# too would double the migration surface for zero benefit.
APP_NAME = "HeightShift"
CONFIG_DIR_NAME = "HeightShift"
CONFIG_FILE_NAME = "HeightShiftOSC_config.json"
LEGACY_CONFIG_DIR_NAME = "HeightShiftOSC"
AUTHOR = "Blise518B"

# --- Window Configuration ---
# Compact first launch (his main display is 1707 x 912 logical px); after that
# the window reopens where it was left (saveGeometry/restoreGeometry).
DEFAULT_WINDOW_WIDTH = 940
DEFAULT_WINDOW_HEIGHT = 790

# --- Writing heights ---
# After every send, reports from VRChat are held back this long and only the
# newest is adopted afterwards. VRChat echoes the eye height it applied, so
# without the hold an echo of an older send could become the base of the next
# relative step (+1 cm pressed quickly three times would lose steps).
ECHO_HOLD_S = 1.0

# --- Rapid Burst Configuration (avatar-change height preservation) ---
BURST_DURATION = 2.0
BURST_INTERVAL = 0.1
# VRChat can report the NEW avatar's default height moments before it sends
# /avatar/change, and with the 518 router on, every packet also arrives a
# second time a little later. A report this close before the change is
# therefore never used as the height to preserve.
PRESERVE_REPORT_GUARD_S = 0.3
# If VRChat still reports a different height once the burst ends, one more
# burst is sent — never more, so the app can't fight the user.
PRESERVE_MAX_RETRIES = 1
PRESERVE_TOLERANCE_CM = 0.5

# --- Slow transition ---
TRANSITION_TICK_MS = 100          # at most 10 sends a second (same as the burst)
TRANSITION_MIN_STEP_CM = 0.05     # skip a send that would move less than 0.5 mm
TRANSITION_MIN_DURATION_S = 1
TRANSITION_MAX_DURATION_S = 99 * 3600

# --- OSC Manager Diagnostics Thresholds ---
DIAG_LOG_INTERVAL_S = 30.0
SILENT_THRESHOLD_S = 15.0
SILENT_REPROBE_S = 45.0
SILENT_REREGISTER_S = 75.0
SILENT_RETRY_INTERVAL_S = 300.0   # repeat both self-heals this often while still silent
BROWSER_REFRESH_S = 5.0
HEALTH_CHECK_INTERVAL_S = 5.0

LOG_FILE_NAME = "osc_diagnostics.log"
LOG_FILE_MAX_BYTES = 1_000_000

# --- Logging ---
LOG_FORMAT = "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
