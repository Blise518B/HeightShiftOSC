"""Settings file for HeightShift: atomic writes, defensive reads.

A config file that can't be used (broken JSON, not an object) is renamed to
`*.corrupt-<time>.json` before the defaults take over — so a bad file never
silently destroys the user's saved profiles on the next save. Every value is
read through a typed getter that falls back to the default when the stored
value has the wrong type or is out of range.
"""

import json
import logging
import math
import os
import sys
import tempfile
import threading
import time
from typing import Any, Dict, Iterable

from constants import (
    APP_NAME,
    DEFAULT_HIDE_CONSOLE,
    DEFAULT_HOTKEY_SPEED,
    DEFAULT_HOTKEY_SPEED_UNIT,
    DEFAULT_HOTKEYS_ENABLED,
    DEFAULT_OSC_ROUTER_518,
    DEFAULT_PRESERVE_HEIGHT_ON_AVATAR,
    DEFAULT_PROFILES,
    DEFAULT_SETTINGS_OPEN,
    DEFAULT_STARTUP_HEIGHT_CM,
    DEFAULT_TRANSITION_DURATION,
    DEFAULT_TRANSITION_TARGET_CM,
    DEFAULT_TRANSITION_UNIT,
    LEGACY_CONFIG_DIR_NAME,
    MAX_HEIGHT_CM,
    MIN_HEIGHT_CM,
    SAVED_SLOTS,
)

logger = logging.getLogger(__name__)

PROFILE_COUNT = SAVED_SLOTS


def get_app_config_dir() -> str:
    """The per-user folder for the config file and osc_diagnostics.log."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        config_dir = os.path.join(base, APP_NAME)
        # The app was called HeightShiftOSC before the family-wide naming pass.
        # Adopt the old folder wholesale so profiles and settings survive the
        # rename on any machine this build lands on.
        legacy_dir = os.path.join(base, LEGACY_CONFIG_DIR_NAME)
        if not os.path.isdir(config_dir) and os.path.isdir(legacy_dir):
            try:
                os.rename(legacy_dir, config_dir)
            except OSError:
                pass    # locked or cross-volume: fall through, a fresh dir is made
    elif sys.platform == "darwin":
        config_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support",
                                  APP_NAME)
    else:
        config_dir = os.path.join(os.path.expanduser("~"), ".config", APP_NAME)
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def default_config() -> Dict[str, Any]:
    return {
        "profiles": dict(DEFAULT_PROFILES),
        "startup_mode": "query",
        "startup_height": DEFAULT_STARTUP_HEIGHT_CM,
        "slider_min_value": MIN_HEIGHT_CM,
        "slider_max_value": MAX_HEIGHT_CM,
        "preserve_height_on_avatar_switch": DEFAULT_PRESERVE_HEIGHT_ON_AVATAR,
        "hide_console": DEFAULT_HIDE_CONSOLE,
        "osc_router_518": DEFAULT_OSC_ROUTER_518,
        "unlock_upper_limit": False,
        "transition_target_cm": DEFAULT_TRANSITION_TARGET_CM,
        "transition_duration": DEFAULT_TRANSITION_DURATION,
        "transition_unit": DEFAULT_TRANSITION_UNIT,
        "transition_curve": "linear",
        "ui_mode": "neon",
        "text_scale": 1.0,
        "settings_open": DEFAULT_SETTINGS_OPEN,
        "hotkeys_enabled": DEFAULT_HOTKEYS_ENABLED,
        "hotkeys_vrchat_only": True,
        "hotkey_grow": {"vk": 0x6B, "mods": 0},      # numpad +
        "hotkey_shrink": {"vk": 0x6D, "mods": 0},    # numpad -
        "hotkey_reset": {"vk": 0x6A, "mods": 0},     # numpad *: the avatar's own height
        "hotkey_speed": DEFAULT_HOTKEY_SPEED,
        "hotkey_speed_unit": DEFAULT_HOTKEY_SPEED_UNIT,
    }


class ConfigManager:
    """Handles loading and saving configuration data."""

    def __init__(self, config_file: str):
        self.config_file: str = config_file
        self._lock = threading.Lock()
        # a first install, not an update: What's new stays quiet for it
        self.created_fresh: bool = not os.path.exists(config_file)
        self.config: Dict[str, Any] = self.load_config()

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_config(self) -> Dict[str, Any]:
        with self._lock:
            merged = default_config()
            if not os.path.exists(self.config_file):
                return merged
            try:
                # utf-8-sig: a file saved by Notepad or PowerShell starts with a
                # BOM, which plain utf-8 json.load rejects as broken.
                with open(self.config_file, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                self._quarantine(f"unreadable JSON ({e})")
                return merged
            except OSError as e:
                # Locked / permission problem: use defaults for this run but
                # leave the file alone — it may be perfectly fine.
                logger.error(f"Could not read config {self.config_file}: {e}")
                return merged
            if not isinstance(data, dict):
                self._quarantine(f"top level is {type(data).__name__}, not an object")
                return merged
            merged.update(data)
            return merged

    def _quarantine(self, reason: str) -> None:
        """Move a broken config aside so the next save can't overwrite it."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base, ext = os.path.splitext(self.config_file)
        target = f"{base}.corrupt-{stamp}{ext or '.json'}"
        try:
            os.replace(self.config_file, target)
            logger.error(f"Config file was broken ({reason}); kept it as {target} "
                         "and started from defaults.")
        except OSError as e:
            logger.error(f"Config file was broken ({reason}) and could not be moved "
                         f"aside: {e}")

    # ------------------------------------------------------------------
    # Typed getters
    # ------------------------------------------------------------------

    def get_bool(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        return value if isinstance(value, bool) else default

    def get_number(self, key: str, default: float, lo: float = -math.inf,
                   hi: float = math.inf) -> float:
        value = self.config.get(key, default)
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and lo <= value <= hi):
            return float(value)
        return float(default)

    def get_choice(self, key: str, default: str, choices: Iterable[str]) -> str:
        value = self.config.get(key, default)
        return value if value in tuple(choices) else default

    def get_str(self, key: str, default: str = "") -> str:
        value = self.config.get(key, default)
        return value if isinstance(value, str) else default

    def load_profiles(self) -> Dict[str, float]:
        """Saved profiles, keeping only real positive heights under the
        expected keys (`profile1`..`profile4`)."""
        with self._lock:
            raw = self.config.get("profiles", {})
        if not isinstance(raw, dict):
            return {}
        out: Dict[str, float] = {}
        for i in range(1, PROFILE_COUNT + 1):
            key = f"profile{i}"
            value = raw.get(key)
            if (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value) and value > 0):
                out[key] = float(value)
        return out

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _atomic_write(self, config: Dict[str, Any]) -> None:
        """Write `config` to disk atomically (temp file + fsync + os.replace),
        so a crash mid-write leaves either the old file or the new one.

        The caller must already hold ``self._lock``.
        """
        directory = os.path.dirname(self.config_file) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".cfg-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.config_file)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    def save_config(self, config: Dict[str, Any]) -> None:
        """Replace the whole config (and the in-memory copy)."""
        with self._lock:
            try:
                self._atomic_write(config)
                self.config = dict(config)
            except OSError as e:
                logger.error(f"IO error saving config file {self.config_file}: {e}")
            except Exception:
                logger.error("Unexpected error saving config", exc_info=True)

    def update_config(self, updates: Dict[str, Any]) -> None:
        """Merge `updates` into the config and save. Keys not mentioned are
        kept, so settings added by a newer version survive an older one."""
        with self._lock:
            self.config.update(updates)
            try:
                self._atomic_write(self.config)
            except OSError as e:
                logger.error(f"IO error saving config file {self.config_file}: {e}")
            except Exception:
                logger.error("Unexpected error updating config", exc_info=True)
