import logging

# Set up logging
logger = logging.getLogger(__name__)

from typing import Any
from pythonosc.udp_client import SimpleUDPClient


class OSCClient:
    """OSC client for sending height data to VRChat with OSCQuery support."""
    
    def __init__(self, ip: str = "127.0.0.1", port: int = 8042) -> None:
        """Initialize the OSC client with the given IP and port."""
        self.ip: str = ip
        self.port: int = port
        self._client: SimpleUDPClient = SimpleUDPClient(ip, port)
    
    def update_config(self, ip: Any, port: Any) -> None:
        """Update the OSC client configuration."""
        new_ip = str(ip)
        new_port = int(port)
        
        # Only recreate client if values actually changed
        if self.ip != new_ip or self.port != new_port:
            self.ip = new_ip
            self.port = new_port
            self._client = SimpleUDPClient(self.ip, self.port)
            logger.info(f"Updated config: {self.ip}:{self.port}")
    
    def send_height(self, height: float) -> None:
        """Send height value to VRChat via OSC.
        
        Args:
            height: Height in centimeters (will be converted to meters)
        """
        # Convert cm to meters (VRChat uses eyeheight in meters)
        # 1 cm = 0.01 meters, 10000 cm = 100.0 meters
        meters = height / 100.0
        
        logger.info(f"Sending height: {height} cm ({meters} m) to {self.ip}:{self.port}")
        try:
            self._client.send_message("/avatar/eyeheight", meters)
            logger.debug("Successfully sent message")
        except OSError as e:
            logger.error("Network error sending OSC message", exc_info=True)
        except Exception as e:
            logger.error("Unexpected error sending OSC message", exc_info=True)
    
    def get_port(self) -> int:
        """Get the current OSC port."""
        return self.port
    
    def set_port(self, port: int) -> None:
        """Set the OSC port."""
        self.port = int(port)
        self._client = SimpleUDPClient(self.ip, self.port)
    
    def get_ip(self) -> str:
        """Get the current OSC IP."""
        return self.ip
