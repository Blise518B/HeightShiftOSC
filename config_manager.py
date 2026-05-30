import json
import os
import tempfile
import threading
import logging

from constants import (
    DEFAULT_VRCHAT_OSC_IP,
    DEFAULT_STARTUP_HEIGHT_CM,
    DEFAULT_WINDOW_GEOMETRY,
    DEFAULT_PRESERVE_HEIGHT_ON_AVATAR,
    DEFAULT_HIDE_CONSOLE,
    MIN_HEIGHT_CM,
    MAX_HEIGHT_CM
)

from typing import Dict, Any

# Set up logging
logger = logging.getLogger(__name__)

class ConfigManager:
    """Handles loading and saving configuration data."""

    def __init__(self, config_file: str):
        """
        Initialize the ConfigManager with the config file path.

        Args:
            config_file: Path to the configuration JSON file
        """
        self.config_file: str = config_file
        self._lock = threading.Lock()
        self.config: Dict[str, Any] = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """
        Load configuration from file.

        Returns:
            dict: The loaded configuration dictionary
        """
        with self._lock:
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError, OSError):
                    return self.get_default_config()
            return self.get_default_config()

    def get_default_config(self) -> Dict[str, Any]:
        """
        Return the default configuration dictionary.

        Returns:
            dict: Default configuration with osc_ip, profiles,
                  startup_mode, startup_height, slider_min_value, slider_max_value, window_geometry,
                  and preserve_height_on_avatar_switch keys
        """
        return {
            "osc_ip": DEFAULT_VRCHAT_OSC_IP,
            "profiles": {},
            "startup_mode": "query",
            "startup_height": DEFAULT_STARTUP_HEIGHT_CM,
            "slider_min_value": MIN_HEIGHT_CM,
            "slider_max_value": MAX_HEIGHT_CM,
            "window_geometry": DEFAULT_WINDOW_GEOMETRY,
            "preserve_height_on_avatar_switch": DEFAULT_PRESERVE_HEIGHT_ON_AVATAR,
            "hide_console": DEFAULT_HIDE_CONSOLE,
        }

    def _atomic_write(self, config: Dict[str, Any]) -> None:
        """Write `config` to disk atomically.

        Serialise to a temp file in the same directory, fsync it, then
        ``os.replace`` it over the real file. ``os.replace`` is atomic on
        both Windows and POSIX, so a crash or power loss mid-write can
        never leave a truncated / half-written config behind — readers
        see either the old file or the new one.

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
            # Don't leave the temp file lying around if anything failed;
            # re-raise so the caller's error handler logs it.
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    def save_config(self, config: Dict[str, Any]) -> None:
        """
        Save configuration to file and refresh the in-memory copy.

        Args:
            config: The configuration dictionary to save
        """
        with self._lock:
            try:
                self._atomic_write(config)
                # Keep the in-memory copy in sync so it can't drift from
                # what's on disk after a full save.
                self.config = dict(config)
            except OSError as e:
                logger.error(f"IO error saving config file {self.config_file}: {e}")
            except Exception:
                logger.error("Unexpected error saving config", exc_info=True)

    def load_profiles(self) -> Dict[str, int]:
        """
        Extract profiles from configuration with thread safety.

        Returns:
            dict: The profiles dictionary (copy to prevent modification)
        """
        with self._lock:
            # Return a copy to prevent external modification
            return dict(self.config.get("profiles", {}))

    def update_config(self, updates: Dict[str, Any]) -> None:
        """
        Update configuration values and save to file.

        Args:
            updates: Dictionary of config keys and their new values
        """
        with self._lock:
            # Update the in-memory config
            for key, value in updates.items():
                self.config[key] = value
            # Save immediately
            try:
                self._atomic_write(self.config)
            except OSError as e:
                logger.error(f"IO error saving config file {self.config_file}: {e}")
            except Exception:
                logger.error("Unexpected error updating config", exc_info=True)
