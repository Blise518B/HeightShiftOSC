import ctypes
import json
import os
import sys
import time
import threading
import logging
import customtkinter as ctk
import requests
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
from ui import create_ui, refresh_profile_display, update_display
from config_manager import ConfigManager
from osc_client import OSCClient
from oscquery_server import OSCQueryServer
from osc_receiver import OSCReceiver
from utils import round_height_cm
from constants import (
    MIN_HEIGHT_CM,
    MAX_HEIGHT_CM,
    DEFAULT_HEIGHT_CM,
    DEFAULT_STARTUP_HEIGHT_CM,
    DEFAULT_HIDE_CONSOLE,
    VRCHAT_MDNS_BROWSE_TIMEOUT,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
    APP_NAME,
    CONFIG_FILE_NAME,
    VRCHAT_HTTP_TIMEOUT,
    DEFAULT_WINDOW_WIDTH,
    DEFAULT_WINDOW_HEIGHT,
    VRCHAT_OSC_PATH,
    BURST_DURATION,
    BURST_INTERVAL
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT
)
logger = logging.getLogger(__name__)


def get_app_config_dir():
    """
    Get the application config directory based on the operating system.
    
    Returns:
        str: Path to the config directory
    """
    if sys.platform == "win32":
        # Windows: %APPDATA%\HeightShiftOSC
        config_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "HeightShiftOSC")
    elif sys.platform == "darwin":
        # macOS: ~/Library/Application Support/HeightShiftOSC
        config_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "HeightShiftOSC")
    else:
        # Linux: ~/.config/HeightShiftOSC
        config_dir = os.path.join(os.path.expanduser("~"), ".config", "HeightShiftOSC")
    
    # Create directory if it doesn't exist
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def get_config_file():
    """
    Get the full path to the config file.
    
    Returns:
        str: Path to the config JSON file
    """
    config_dir = get_app_config_dir()
    return os.path.join(config_dir, "HeightShiftOSC_config.json")


# Configuration file path
CONFIG_FILE = get_config_file()


def discover_vrchat_oscquery_port(timeout=VRCHAT_MDNS_BROWSE_TIMEOUT):
    """
    Discover VRChat's OSCQuery HTTP port using mDNS.
    
    Args:
        timeout: Time to wait for mDNS discovery (seconds)
    
    Returns:
        int or None: VRChat's HTTP port if found, None otherwise
    """
    class VRChatListener(ServiceListener):
        def __init__(self):
            self.vrchat_http_port = None
        
        def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            if "VRChat" in name:
                info = zc.get_service_info(type_, name)
                if info:
                    self.vrchat_http_port = info.port
                    logger.info(f"VRChat OSCQuery HTTP port discovered: {self.vrchat_http_port}")
        
        def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            pass
        
        def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            pass
    
    logger.info("Discovering VRChat OSCQuery server via mDNS...")
    zc = Zeroconf()
    listener = VRChatListener()
    
    browser = ServiceBrowser(zc, "_oscjson._tcp.local.", listener)
    time.sleep(timeout)
    zc.close()
    
    return listener.vrchat_http_port


def discover_vrchat_osc_port(timeout=VRCHAT_MDNS_BROWSE_TIMEOUT):
    """
    Discover VRChat's OSC UDP port using mDNS.
    
    Args:
        timeout: Time to wait for mDNS discovery (seconds)
    
    Returns:
        int or None: VRChat's OSC port if found, None otherwise
    """
    class VRChatOSCListener(ServiceListener):
        def __init__(self):
            self.vrchat_osc_port = None
        
        def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            if "VRChat" in name and "_osc._udp" in type_:
                info = zc.get_service_info(type_, name)
                if info:
                    self.vrchat_osc_port = info.port
                    logger.info(f"VRChat OSC UDP port discovered: {self.vrchat_osc_port}")
        
        def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            pass
        
        def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            pass
    
    logger.info("Discovering VRChat OSC UDP port via mDNS...")
    zc = Zeroconf()
    listener = VRChatOSCListener()
    
    browser = ServiceBrowser(zc, "_osc._udp.local.", listener)
    time.sleep(timeout)
    zc.close()
    
    return listener.vrchat_osc_port


class HeightScalerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("HeightShiftOSC")
        self.default_geometry = f"{DEFAULT_WINDOW_WIDTH}x{DEFAULT_WINDOW_HEIGHT}"
        
        # Height values (in cm)
        self.current_height = ctk.IntVar(value=DEFAULT_HEIGHT_CM)
        self.height_loaded = False  # Track if height has been received from VRChat
        
        # Store target height for auto-restore after avatar swap
        self.saved_target_height = None  # None until we receive /avatar/change event
        
        # Track last user-set height (for restoring after avatar change)
        self.last_user_set_height = DEFAULT_HEIGHT_CM
        self._height_lock = threading.Lock()  # Lock for thread-safe height access
        
        # Initialize ConfigManager first to get config
        self.config_manager = ConfigManager(CONFIG_FILE)
        self.config = self.config_manager.config
        
        # Preserve height on avatar switch feature
        self.preserve_height_on_avatar = self.config.get("preserve_height_on_avatar_switch", True)
        
        # Hide console feature
        self.hide_console = self.config.get("hide_console", DEFAULT_HIDE_CONSOLE)
        self.hide_console_var = ctk.BooleanVar(value=self.hide_console)
        
        # Startup mode (query or fixed_height) - map config values to UI display format
        saved_mode = self.config.get("startup_mode", "query")
        if saved_mode == "fixed_height":
            self.startup_mode = "Load Fixed Height"
        else:
            self.startup_mode = "Query Current Height"
        
        # Startup height (for fixed_height mode)
        self.startup_height = int(self.config.get("startup_height", DEFAULT_STARTUP_HEIGHT_CM))
        
        # Slider min/max values (load from config with defaults)
        self.slider_min_value = int(self.config.get("slider_min_value", MIN_HEIGHT_CM))
        self.slider_max_value = int(self.config.get("slider_max_value", MAX_HEIGHT_CM))
        
        # Window geometry from config
        self.window_geometry = self.config.get("window_geometry", self.default_geometry)
        
        # Apply window geometry before creating UI
        self.root.geometry(self.window_geometry)
        
        # Profile variables (get a copy to avoid external modification)
        self.profiles = self.config_manager.load_profiles()
        
        # Initialize UI variables with defaults first (before connection setup)
        self.osc_ip_str = "127.0.0.1"
        self.vrchat_discovered_osc_port = None
        
        # Initialize StringVars with default values (UI will be updated later when connection is ready)
        self.osc_ip = ctk.StringVar(value=self.osc_ip_str)
        self.osc_port = ctk.StringVar(value="N/A")  # Will be updated after OSCQuery server starts
        self.vrchat_port = ctk.StringVar(value="")
        
        # Create UI immediately - this shows the interface right away with placeholders
        create_ui(root, self)
        
        # Hide console if default setting is enabled (after UI is created so window is visible first)
        if self.hide_console and sys.platform == "win32":
            self.root.after(50, lambda: self._toggle_console_visibility())
        
        # Now set up connection in background (after UI is created) to not block UI startup
        self.root.after(10, self._setup_connections_in_background)
        
        # Initialize OSC client with placeholder port (empty string means no port configured yet)
        vrchat_port_str = self.vrchat_port.get()
        vrchat_port = int(vrchat_port_str) if vrchat_port_str else 8042
        self.osc_client = OSCClient(self.osc_ip.get(), vrchat_port)
        
        # Handle startup based on mode (run in background to not block UI)
        # Use longer delay to ensure connection setup completes first
        if self.startup_mode == "Load Fixed Height":
            # Load with fixed height from config (in background thread)
            self.root.after(2000, lambda: self._load_fixed_height_startup())
        else:
            # Query VRChat for current height on startup (default behavior)
            # Run in background thread to not block UI
            self.root.after(2000, self.query_vrchat_height_non_blocking)
        
        # Bind window close event
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def _setup_connections_in_background(self):
        """
        Set up connection in background thread (after UI is created).
        This ensures the UI appears immediately without waiting for network operations.
        """
        def setup():
            """Run connection setup in background thread."""
            # Start OSCQuery server (for local port assignment)
            try:
                self.oscquery_server = OSCQueryServer()
                self.oscquery_server.start()
            except OSError as e:
                logger.error(f"Failed to start OSCQuery server: {e}")
                print(f"[ERROR] Failed to start OSC server - port may be in use. Please check your network configuration.")
                sys.exit(1)
            except Exception as e:
                logger.error("Unexpected error starting OSCQuery server", exc_info=True)
                print(f"[ERROR] Unexpected error starting OSC server: {e}")
                sys.exit(1)
            
            # Get dynamic OSC port from server
            self.osc_port_value = self.oscquery_server.get_osc_port()
            
            # Update local OSC port display
            self.root.after(0, lambda: self.osc_port.set(str(self.osc_port_value)))
            
            # Discover VRChat OSC port via mDNS (runs in background thread)
            self.vrchat_discovered_osc_port = discover_vrchat_osc_port(timeout=VRCHAT_MDNS_BROWSE_TIMEOUT)
            
            # Update VRChat port on main thread
            if self.vrchat_discovered_osc_port is not None:
                logger.info(f"Using discovered VRChat OSC port: {self.vrchat_discovered_osc_port}")
                self.root.after(0, lambda: self.vrchat_port.set(str(self.vrchat_discovered_osc_port)))
            
            # Initialize OSC client with the determined port
            vrchat_port_str = self.vrchat_port.get()
            if vrchat_port_str:
                vrchat_port = int(vrchat_port_str)
                self.osc_client = OSCClient(self.osc_ip.get(), vrchat_port)
            else:
                logger.warning(f"VRChat OSC port not discovered and no port configured")
            
            # Start OSC receiver (may block briefly if port is in use)
            try:
                self.osc_receiver = OSCReceiver(self.osc_ip_str, self.osc_port_value, self.on_osc_receive)
                self.osc_receiver.start()
            except OSError as e:
                logger.error(f"Failed to start OSC receiver: {e}")
                print(f"[ERROR] Failed to start OSC receiver - port may be in use.")
            except Exception as e:
                logger.error("Unexpected error starting OSC receiver", exc_info=True)
                print(f"[ERROR] Unexpected error starting OSC receiver: {e}")
        
        # Run setup in background thread
        thread = threading.Thread(target=setup, daemon=True)
        thread.start()
    
    def _load_fixed_height_startup(self):
        """
        Load fixed height from config on startup (run in background).
        Updates UI when complete.
        """
        import time
        
        # Small delay to let UI render first
        time.sleep(0.1)
        
        # Load with fixed height from config
        self.current_height.set(self.startup_height)
        self.height_loaded = True  # Mark as loaded since we're setting it manually
        update_display(self)
        # Send OSC message to VRChat so the height is actually applied
        self.send_height(self.startup_height)
    
    def on_osc_receive(self, address, *args):
        """
        Callback when receiving an OSC message.
        
        Args:
            address: The OSC address path
            args: The OSC message arguments
        """
        # Log all OSC messages at INFO level so user can see what's happening
        logger.info(f"[on_osc_receive] Called with address={address} args={args}")
        if address == "/avatar/eyeheight" and args:
            # Convert meters from VRChat to cm for display
            meters = args[0]
            height_cm = round_height_cm(meters * 100)
            # Clamp to valid range using constants
            height_cm = max(MIN_HEIGHT_CM, min(MAX_HEIGHT_CM, height_cm))
            # Only log at INFO when the height is successfully loaded (initial setup)
            if not self.height_loaded:
                logger.info(f"Received initial eyeheight: {meters}m = {height_cm}cm")
            else:
                logger.debug(f"Received eyeheight update: {meters}m = {height_cm}cm")
            # Schedule UI updates on the main thread for thread safety
            self.root.after(0, lambda h=height_cm, loaded=True: self._update_height_ui(h, loaded))
        elif address == "/avatar/change":
            # Event-driven UDP callback: avatar swap detected by VRChat via UDP packet
            if self.preserve_height_on_avatar:
                logger.info("Avatar change detected. Preserving height - initiating auto-restore rapid burst.")
                burst_thread = threading.Thread(target=self._rapid_burst_on_avatar_change, daemon=True)
                burst_thread.start()
            else:
                logger.info("Avatar change detected but 'Preserve Height' is disabled. Querying current avatar's height.")
                query_thread = threading.Thread(target=self._query_current_height_on_avatar_change, daemon=True)
                query_thread.start()

    def _update_height_ui(self, height_cm: int, height_loaded: bool):
        """
        Update height UI elements (must be called from main thread).
        
        Args:
            height_cm: Height in centimeters
            height_loaded: Whether the initial height has been loaded
        """
        self.current_height.set(height_cm)
        if height_loaded:
            self.height_loaded = True
        update_display(self)

    def _rapid_burst_on_avatar_change(self):
        """
        Rapid Burst function executed when /avatar/change event is received.
        
        VRChat discards /avatar/eyeheight messages sent immediately after avatar change
        because the new avatar's parameter system hasn't initialized yet.
        
        This function fires 20 OSC messages over 2 seconds (0.1s intervals) to "spam"
        the client and guarantee we catch the exact frame when VRChat's parameter
        system initializes, locking in the custom scale with minimal visual jumping.
        
        Args:
            target_height: Height in cm to restore after avatar swap
        """
        # Read last_user_set_height under lock to prevent race condition
        with self._height_lock:
            if self.last_user_set_height is None:
                logger.warning("No saved target height for auto-restore")
                return
            target_height = self.last_user_set_height
        
        num_sends = int(BURST_DURATION / BURST_INTERVAL)  # Calculate number of sends from constants
        
        logger.info(f"Starting rapid burst: {num_sends} sends at {BURST_INTERVAL}s intervals ({BURST_DURATION}s total)")
        
        for i in range(num_sends):
            self.send_height(target_height)
            time.sleep(BURST_INTERVAL)
        
        logger.info("Rapid burst complete. Auto-restore finished.")

    def update_osc_client(self):
        """Update OSC client with current IP and VRChat port values."""
        vrchat_port_str = self.vrchat_port.get()
        if vrchat_port_str:
            vrchat_port = int(vrchat_port_str)
            self.osc_client.update_config(self.osc_ip.get(), vrchat_port)

    def save_config_immediate(self):
        """Save configuration to file immediately."""
        with self._height_lock:
            profiles_copy = dict(self.profiles)
        
        config_to_save = {
            "osc_ip": self.osc_ip.get(),
            "profiles": profiles_copy,
            "startup_mode": "fixed_height" if self.startup_mode == "Load Fixed Height" else "query",
            "startup_height": int(self.fixed_height_var.get()) if hasattr(self, 'fixed_height_var') else DEFAULT_HEIGHT_CM,
            "slider_min_value": int(self.slider_min_var.get()),
            "slider_max_value": int(self.slider_max_var.get()),
            "preserve_height_on_avatar_switch": self.preserve_height_var.get(),
            "hide_console": self.hide_console_var.get()
        }
        # Also save the discovered port separately for reference
        if self.vrchat_discovered_osc_port is not None:
            config_to_save["vrchat_discovered_osc_port"] = self.vrchat_discovered_osc_port
        
        config_to_save["window_geometry"] = self.root.geometry()
        self.config_manager.save_config(config_to_save)
    
    def apply_ip_change(self):
        """Apply VRChat IP change - validates and updates OSC client with new IP."""
        new_ip = self.osc_ip.get().strip()
        
        # Basic validation: check for valid IP format (contains dots, not empty)
        if new_ip and '.' in new_ip:
            vrchat_port_str = self.vrchat_port.get()
            if vrchat_port_str:
                try:
                    vrchat_port = int(vrchat_port_str)
                    self.osc_client.update_config(new_ip, vrchat_port)
                    logger.info(f"VRChat IP updated to: {new_ip}:{vrchat_port}")
                except ValueError:
                    logger.warning(f"Invalid VRChat port: {vrchat_port_str}")
            else:
                logger.warning("VRChat port not available")
        else:
            logger.warning(f"Invalid IP address format: {new_ip}")
        
        # Always save to config (even if validation fails)
        self.save_config_immediate()
    
    def on_config_change(self, *args):
        """Callback when IP or port changes - update client and save config."""
        self.update_osc_client()
        self.save_config_immediate()
    
    
    def save_profile(self, profile_num):
        """Save current height to a profile."""
        profile_key = f"profile{profile_num}"
        # Validate height is within valid range before saving
        height = self.current_height.get()
        if MIN_HEIGHT_CM <= height <= MAX_HEIGHT_CM:
            self.profiles[profile_key] = height
        else:
            logger.warning(f"Profile {profile_num} height {height} out of valid range [{MIN_HEIGHT_CM}, {MAX_HEIGHT_CM}], clamping")
            self.profiles[profile_key] = max(MIN_HEIGHT_CM, min(MAX_HEIGHT_CM, height))
        self.save_config_immediate()
        refresh_profile_display(self)
    
    def load_profile(self, profile_num):
        """Load a profile and set current height."""
        profile_key = f"profile{profile_num}"
        if profile_key in self.profiles:
            height = self.profiles[profile_key]
            # Validate height is within valid range before loading
            if MIN_HEIGHT_CM <= height <= MAX_HEIGHT_CM:
                self.current_height.set(height)
                update_display(self)
                self.send_height(height)
            else:
                logger.warning(f"Profile {profile_num} saved height {height} out of valid range [{MIN_HEIGHT_CM}, {MAX_HEIGHT_CM}], using default")
                # Load default instead
                self.current_height.set(DEFAULT_HEIGHT_CM)
                update_display(self)
                self.send_height(DEFAULT_HEIGHT_CM)
        else:
            logger.debug(f"Profile {profile_key} not found in saved profiles")
    
    def send_height(self, height):
        """Send height value to VRChat via OSC."""
        with self._height_lock:
            self.saved_target_height = height  # For rapid burst on avatar change
            self.last_user_set_height = height  # Track last user-set height for avatar restore
        self.osc_client.send_height(height)
    
    def adjust_height(self, amount):
        """Adjust height by the given amount."""
        new_height = round_height_cm(self.current_height.get() + amount)
        
        # Clamp to valid range (using constants from constants.py)
        new_height = max(MIN_HEIGHT_CM, min(MAX_HEIGHT_CM, new_height))
        
        self.current_height.set(new_height)
        update_display(self)
        self.send_height(new_height)
    
    def _toggle_console_visibility(self):
        """Toggle the visibility of the console window."""
        try:
            if sys.platform == "win32":
                # Windows: Use ctypes to call WinAPI
                kernel32 = ctypes.WinDLL('kernel32')
                user32 = ctypes.WinDLL('user32')
                
                # Get the console window handle
                hwnd = kernel32.GetConsoleWindow()
                
                if hwnd != 0:
                    # Get the current show state
                    if self.hide_console_var.get():
                        # Hide the console window
                        user32.ShowWindow(hwnd, 0)  # SW_HIDE = 0
                        logger.info("Console window hidden")
                    else:
                        # Show the console window
                        user32.ShowWindow(hwnd, 5)  # SW_SHOW = 5 (restores and shows)
                        logger.info("Console window shown")
            elif sys.platform == "darwin":
                # macOS: Use AppleScript to toggle Terminal/Console visibility
                import subprocess
                script = '''
                tell application "Terminal"
                    if front window is miniaturized then
                        setminiaturized of front window to false
                    else
                        setminiaturized of front window to true
                    end if
                end tell
                '''
                subprocess.run(['osascript', '-e', script], capture_output=True)
            elif sys.platform == "linux":
                # Linux: Use xdotool if available, otherwise minimize
                import subprocess
                try:
                    result = subprocess.run(['xdotool', 'search', '--name', 'HeightShiftOSC'], 
                                          capture_output=True, text=True)
                    if result.returncode == 0 and result.stdout.strip():
                        window_id = result.stdout.strip().split('\n')[0]
                        if self.hide_console_var.get():
                            subprocess.run(['xdotool', 'windowminimize', window_id])
                        else:
                            subprocess.run(['xdotool', 'windowactivate', window_id])
                except Exception as e:
                    logger.warning(f"Could not toggle console visibility: {e}")
            # Update the stored hide_console state
            self.hide_console = self.hide_console_var.get()
        except Exception as e:
            logger.error("Error toggling console visibility", exc_info=True)
    
    def query_vrchat_height_non_blocking(self):
        """
        Query VRChat's current eyeheight in a background thread (non-blocking).
        Updates UI when complete.
        """
        import threading
        
        def run_query():
            """Run the height query in a background thread."""
            vrchat_port = discover_vrchat_oscquery_port(timeout=VRCHAT_MDNS_BROWSE_TIMEOUT)
            
            # Schedule the HTTP query and UI update on the main thread
            self.root.after(100, lambda: self._complete_height_query(vrchat_port))
        
        # Run in background thread
        thread = threading.Thread(target=run_query, daemon=True)
        thread.start()
    
    def _query_current_height_on_avatar_change(self):
        """
        Query VRChat for current height when avatar changes and preserve is OFF.
        Updates UI with the new avatar's actual height.
        """
        vrchat_port = discover_vrchat_oscquery_port(timeout=VRCHAT_MDNS_BROWSE_TIMEOUT)
        
        # Schedule the HTTP query on the main thread
        self.root.after(100, lambda port=vrchat_port: self._complete_height_query(port))
    
    def _complete_height_query(self, vrchat_port):
        """Complete the height query via HTTP (runs on main thread)."""
        if vrchat_port is None:
            print("[VRChat] Could not find VRChat's OSCQuery port via mDNS")
            print("[VRChat] Height display will show 'Not Loaded' until VRChat sends /avatar/eyeheight")
            return

        url = f"http://127.0.0.1:{vrchat_port}/avatar/eyeheight"
        
        try:
            print(f"[VRChat] Querying height from {url}.")
            # Use VRCHAT_HTTP_TIMEOUT constant for HTTP request timeout
            response = requests.get(url, timeout=VRCHAT_HTTP_TIMEOUT)
            response.raise_for_status()
            
            try:
                data = response.json()
            except json.JSONDecodeError as e:
                print(f"[VRChat] JSON parsing error: {e}")
                logger.error("Failed to parse VRChat HTTP response as JSON", exc_info=True)
                return
            
            if "VALUE" in data and data["VALUE"]:
                meters = data["VALUE"][0]
                height_cm = round_height_cm(meters * 100)
                print(f"[VRChat] Current height is {meters}m ({height_cm}cm)")
                
                self.current_height.set(height_cm)
                self.height_loaded = True
                update_display(self)
                # Send height to VRChat so last_user_set_height is properly set for avatar change preservation
                self.send_height(height_cm)
            else:
                print("[VRChat] No value found in response")
        except requests.exceptions.ConnectionError:
            print("[VRChat] Could not connect to VRChat HTTP endpoint")
        except requests.exceptions.HTTPError as e:
            print(f"[VRChat] HTTP Error: {e}")
        except Exception as e:
            print(f"[VRChat] Error querying height: {e}")
            logger.error("Error querying VRChat height", exc_info=True)
    
    def on_closing(self):
        """Handle window close event - save geometry and cleanup."""
        self.save_config_immediate()
        
        # Stop OSC receiver
        if hasattr(self, 'osc_receiver') and self.osc_receiver:
            self.osc_receiver.stop()
        
        # Stop OSCQuery server (unregisters mDNS services)
        if hasattr(self, 'oscquery_server') and self.oscquery_server:
            self.oscquery_server.stop()
        
        self.root.destroy()


def main():
    root = ctk.CTk()
    
    # Set window icon using the provided .ico file
    def get_resource_path(relative_path):
        """Get absolute path to resource, works for development and PyInstaller bundled app."""
        if hasattr(sys, '_MEIPASS'):
            # Running in a PyInstaller bundle
            return os.path.join(sys._MEIPASS, relative_path)
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)
    
    ico_path = get_resource_path("OSC_Scale.ico")
    
    if os.path.exists(ico_path):
        try:
            root.iconbitmap(ico_path)
            print(f"Icon set successfully from {ico_path}")
        except Exception as e:
            print(f"Could not set window icon: {e}")
    else:
        print(f"Warning: Icon file not found at {ico_path}")
    
    app = HeightScalerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()