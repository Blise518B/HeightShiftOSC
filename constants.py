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
# With "Unlock upper limit" ticked (Blise, 2026-11-11: "a bigger max height
# where its 1000m but you need to enable that in the settings"; it was 100 km).
# Ticking it also stretches the scale's top from 100 m to here. VRChat or the
# world may still cap the height lower.
UNLOCKED_MAX_HEIGHT_CM = 100_000      # 1000 m
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
# Where the status bar's two names lead (as in OscGoesPurrr): the app's to its
# repository, his to his GitHub profile
GITHUB_REPO = "Blise518B/HeightShiftOSC"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"
AUTHOR_URL = "https://github.com/Blise518B"
# The VRChat menu (Settings' mini guide): releases/latest/download/<fixed name>
# is always the newest release's copy, so every release must carry the package
MENU_PREFAB_URL = f"{GITHUB_URL}/releases/latest/download/HeightShift-VRCFury.unitypackage"
MENU_GUIDE_URL = f"{GITHUB_URL}/blob/main/docs/VRCHAT_MENU.md"

# --- Window Configuration ---
# The first launch opens at the size Blise picked (2026-11-11: "make the
# default app size the size i have the window now"): compact, the picture
# and the Height panel side by side, Settings folded (open, they'd need a
# wider window). After that the window reopens where it was left
# (saveGeometry/restoreGeometry).
DEFAULT_WINDOW_WIDTH = 740
DEFAULT_WINDOW_HEIGHT = 810
DEFAULT_SETTINGS_OPEN = False

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

# --- How often a moving height is sent ---
# A timed transition and a held key (hotkey or VRChat menu) send the height
# this many times a second: Settings -> Height -> Updates per second. VRChat
# documents no limit on /avatar/eyeheight (docs.vrchat.com, OSC Avatar
# Scaling); more is smoother in your own view, and other players see VRChat's
# own network smoothing either way. Fewer helps if your view jitters.
SEND_RATES = (10, 30, 60)
DEFAULT_SEND_RATE = 30

# --- Timed transition ---
TRANSITION_MIN_STEP_CM = 0.05     # skip a send that would move less than 0.5 mm
TRANSITION_MIN_DURATION_S = 1
DEFAULT_TRANSITION_TARGET_CM = 200
DEFAULT_TRANSITION_DURATION = 20   # with the unit below: grow over 20 seconds
DEFAULT_TRANSITION_UNIT = "s"      # "s" | "min" | "h"
# A first start comes with one saved height, so Load as target and the
# scale's numbered mark show what they do; the other three slots are empty.
DEFAULT_PROFILES = {"profile1": 140.0}
SAVED_SLOTS = 6                    # saved heights in the window (the VRChat menu has 1-4)
# What a click does — on a saved height (each its own), and on the height
# scale (one for all). Blise, 2026-11-11: "change the slots from the default
# select to the pink instant or the yellow timed", "above the height limit …
# select height, go instant and go timed". Select only picks the target.
CLICK_ACTIONS = ("select", "instant", "timed")
DEFAULT_CLICK_ACTION = "select"
TRANSITION_MAX_DURATION_S = 99 * 3600

# --- Hold-to-grow hotkeys ---
# Keys are polled at the send rate above, and a held key sends at most that
# often too. Speeds: % of the current height per second, or cm/s.
DEFAULT_HOTKEYS_ENABLED = True     # numpad + / − work from the first start
DEFAULT_HOTKEY_SPEED_UNIT = "cm"   # height_logic.SPEED_CM: the same cm every second
DEFAULT_HOTKEY_SPEED = 5.0         # 5 cm per second: 1.7 m -> 2.2 m in 10 s
# While no key is down the keys are polled this often (a press waits at most
# this long); while one is down, and a second after, at the send rate.
HOTKEY_IDLE_POLL_MS = 100
HOTKEY_AWAKE_S = 1.0
# The window redraws what a transition tick or VRChat's echo changes at most
# this often while another window has the focus (it may be watched in a VR
# overlay, so never frozen); not at all while minimized.
UI_UNFOCUSED_MS = 100
HOTKEY_SPEED_MIN = 0.1
HOTKEY_SPEED_MAX_PCT = 100.0       # doubling every second
HOTKEY_SPEED_MAX_CM = 1000.0       # 10 m every second

# --- In-VRChat menu (the VRCFury prefab, docs/unity/) ---
# Avatar parameters the HeightShift menu sets. VRChat streams every avatar
# parameter to this app already (it lists /avatar in OSCQuery). All of them
# are unsynced and unsaved: they only talk to this app, so they cost the
# avatar no synced memory, and they read 0 / False after every avatar load.
# tests/test_vrcf_prefab.py checks the built package against this table.
MENU_PREFIX = "HeightShift/"
MENU_GROW = "HeightShift/Grow"        # Bool, a Button: grows while held
MENU_SHRINK = "HeightShift/Shrink"    # Bool, a Button: shrinks while held
MENU_PLAY = "HeightShift/Play"        # Bool, a Button: play / pause / resume the transition
MENU_STOP = "HeightShift/Stop"        # Bool, a Button: stop the transition
MENU_LOAD = "HeightShift/Load"        # Int, Buttons 1-4: set saved height N
MENU_SAVE = "HeightShift/Save"        # Int, Buttons 1-4: save the current height as N
MENU_PARAMS = {MENU_GROW: "bool", MENU_SHRINK: "bool", MENU_PLAY: "bool", MENU_STOP: "bool",
               MENU_LOAD: "int", MENU_SAVE: "int"}
# A press this soon after an avatar change is the new avatar's load, not a
# press; a press this soon after the same button's release is the 518
# router's second copy of a packet, not a second press.
MENU_AVATAR_GUARD_S = 1.0
MENU_DEBOUNCE_S = 0.15

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
