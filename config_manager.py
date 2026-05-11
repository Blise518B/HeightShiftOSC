import json
import os
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

from typing import Dict, Any, Optional

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
                    with open(self.config_file, "r") as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError):
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
             "hide_console": DEFAULT_HIDE_CONSOLE
         }
    
    def save_config(self, config: Dict[str, Any]) -> None:
        """
        Save configuration to file.
        
        Args:
            config: The configuration dictionary to save
        """
        try:
            with self._lock:
                with open(self.config_file, "w") as f:
                    json.dump(config, f, indent=2)
        except IOError as e:
            logger.error(f"IO error saving config file {self.config_file}: {e}")
        except Exception as e:
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
                with open(self.config_file, "w") as f:
                    json.dump(self.config, f, indent=2)
            except IOError as e:
                logger.error(f"IO error saving config file {self.config_file}: {e}")
            except Exception as e:
                logger.error("Unexpected error updating config", exc_info=True)
