import threading
import logging

# Set up logging
logger = logging.getLogger(__name__)

from pythonosc import dispatcher, osc_server

class LoggingDispatcher(dispatcher.Dispatcher):
    """Custom dispatcher that logs every incoming message before dispatching it."""
    
    # Use INFO level to make all OSC messages visible
    def dispatch(self, address, *args):
        logger.info(f"CATCH-ALL Received: {address} args={args}")
        return super().dispatch(address, *args)


from typing import Callable, Any, Optional

class OSCReceiver:
    """OSC receiver for receiving height data from VRChat."""
    
    def __init__(self, ip: str = "127.0.0.1", port: int = 8042, callback: Optional[Callable] = None) -> None:
        """
        Initialize the OSC receiver.
        
        Args:
            ip: IP address to bind to
            port: Port to listen on
            callback: Function to call when receiving OSC messages
        """
        self.ip: str = ip
        self.port: int = port
        self.callback: Optional[Callable] = callback
        
        # Create dispatcher and map OSC paths to callbacks
        self.dispatcher = LoggingDispatcher()
        self.dispatcher.map("/avatar/eyeheight", self._on_receive)
        self.dispatcher.map("/avatar/change", self._on_receive)
        
        # Force bind to 0.0.0.0 to catch packets sent to any network interface (both localhost and physical IPs)
        self.server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", self.port), self.dispatcher)
        self.thread: Optional[threading.Thread] = None
        self.is_running: bool = False
        
        logger.info(f"Initialized on all interfaces, Port={self.port}")
    
    def _on_receive(self, address: str, *args: Any) -> None:
        """
        Internal callback when receiving an OSC message.
        
        Args:
            address: The OSC address path
            args: The OSC message arguments
        """
        logger.info(f"[_on_receive] Received from server: address={address} args={args}")
        if self.callback:
            self.callback(address, *args)
    
    def start(self) -> None:
        """Start the OSC receiver in a background thread."""
        if self.is_running:
            logger.info("Already running, skipping start")
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"Started listening on all interfaces, Port={self.port}")
    
    def stop(self) -> None:
        """Stop the OSC receiver."""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # Shutdown the server (this will unblock serve_forever)
        try:
            self.server.shutdown()
        except OSError as e:
            logger.error("OS error shutting down OSC receiver server", exc_info=True)
        except Exception as e:
            logger.error("Unexpected error shutting down OSC receiver server", exc_info=True)
        
        # Wait for thread to finish - give it enough time to complete naturally
        if self.thread:
            was_alive_before_join = self.thread.is_alive()
            if was_alive_before_join:
                self.thread.join(timeout=2)  # Increased timeout for graceful shutdown
        
        # Close the server socket
        try:
            self.server.server_close()
        except OSError as e:
            logger.error("OS error closing OSC receiver server", exc_info=True)
        except Exception as e:
            logger.error("Unexpected error closing OSC receiver server", exc_info=True)
        
        self.thread = None
    
    def update_port(self, port: int) -> None:
        """Update the receiver port (requires restart)."""
        self.port = port
    
    def get_port(self) -> int:
        """Get the current receiver port."""
        return self.port
