import socket
import json
import threading
import time
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from zeroconf import ServiceInfo, Zeroconf

from constants import APP_NAME

# Set up logging
logger = logging.getLogger(__name__)

# Use 0.0.0.0 to bind to all interfaces, which works better with mDNS discovery
MY_IP = "0.0.0.0"

def get_free_port(protocol: str = "TCP") -> int:
    """Ask the OS for a random open port (dynamic port assignment)."""
    sock_type = socket.SOCK_STREAM if protocol == "TCP" else socket.SOCK_DGRAM
    with socket.socket(socket.AF_INET, sock_type) as s:
        s.bind(('', 0))  # Port 0 tells the OS to pick one for us
        return s.getsockname()[1]


class OSCQueryHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OSCQuery JSON phonebook."""
    
    def __init__(self, *args, osc_data=None, **kwargs):
        self.osc_data = osc_data
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """Handle GET requests - serve the OSCQuery JSON."""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(self.osc_data).encode('utf-8'))
    
    def log_message(self, format, *args):
        """Suppress HTTP server logging."""
        pass


def create_zeroconf_services(zc: Zeroconf, app_name: str, http_port: int, osc_port: int) -> tuple[ServiceInfo, ServiceInfo]:
    """Create and return mDNS service info objects.
    
    Args:
        zc: Zeroconf instance to use (caller is responsible for lifecycle)
        app_name: Name of the application
        http_port: HTTP port for OSCQuery JSON
        osc_port: UDP port for OSC messages
    """
    # Service info for OSCQuery JSON HTTP service
    json_info = ServiceInfo(
        "_oscjson._tcp.local.",
        f"{app_name}._oscjson._tcp.local.",
        addresses=[socket.inet_aton("127.0.0.1")],
        port=http_port,
        server=f"{app_name.lower()}.local.",
        properties={"version": "1.0".encode('utf-8')}
    )
    
    # Service info for OSC UDP service
    osc_info = ServiceInfo(
        "_osc._udp.local.",
        f"{app_name}._osc._udp.local.",
        addresses=[socket.inet_aton("127.0.0.1")],
        port=osc_port,
        server=f"{app_name.lower()}.local.",
        properties={"version": "1.0".encode('utf-8')}
    )
    
    return json_info, osc_info


def register_services(zc: Zeroconf, json_info: ServiceInfo, osc_info: ServiceInfo) -> None:
    """Register mDNS services."""
    zc.register_service(json_info)
    zc.register_service(osc_info)


def unregister_services(zc: Zeroconf, json_info: ServiceInfo, osc_info: ServiceInfo) -> None:
    """Unregister mDNS services for graceful shutdown."""
    try:
        if json_info and zc:
            zc.unregister_service(json_info)
    except Exception as e:
        logger.debug(f"Error unregistering JSON service: {e}")
    try:
        if osc_info and zc:
            zc.unregister_service(osc_info)
    except Exception as e:
        logger.debug(f"Error unregistering OSC service: {e}")


from typing import Optional, Dict, Any

class OSCQueryServer:
    """Main OSCQuery server class that manages HTTP and mDNS services."""
    
    def __init__(self) -> None:
        self.http_port: Optional[int] = None
        self.osc_port: Optional[int] = None
        self.http_thread: Optional[threading.Thread] = None
        self.http_server: Optional[HTTPServer] = None
        self.zc: Optional[Zeroconf] = None
        self.json_info: Optional[ServiceInfo] = None
        self.osc_info: Optional[ServiceInfo] = None
        self.osc_data: Optional[Dict[str, Any]] = None
    
    def start(self) -> None:
        """Start the OSCQuery server."""
        # Get dynamic ports
        self.osc_port = get_free_port("UDP")
        self.http_port = get_free_port("TCP")
        
        # Create OSCQuery data with dynamic ports
        self.osc_data = {
            "NAME": APP_NAME,
            "OSC_IP": MY_IP,
            "OSC_PORT": self.osc_port,
            "OSC_TRANSPORT": "UDP",
            "CONTENTS": {
                "avatar": {
                    "FULL_PATH": "/avatar",
                    "CONTENTS": {
                        "eyeheight": {
                            "FULL_PATH": "/avatar/eyeheight",
                            "TYPE": "f",
                            "ACCESS": 3  # 1 = Read, 2 = Write, 3 = Read/Write
                        },
                          "change": {
                              "FULL_PATH": "/avatar/change",
                              "TYPE": "s",  # String: VRChat sends the Avatar ID as a string
                              "ACCESS": 3   # Read/Write: VRChat can send UDP events to us
                          }
                    }
                }
            }
        }
        
        logger.info("Starting OSCQuery server...")
        logger.info(f"Dynamic ports - HTTP: {self.http_port}, OSC: {self.osc_port}")
        
        # Create and store HTTP server
        self.http_server = HTTPServer(
            (MY_IP, self.http_port),
            lambda *args, **kwargs: OSCQueryHandler(*args, osc_data=self.osc_data, **kwargs)
        )
        
        # Start HTTP server in background thread
        self.http_thread = threading.Thread(
            target=self.http_server.serve_forever,
            daemon=True
        )
        self.http_thread.start()
        
        # Wait briefly for HTTP server to start
        time.sleep(0.1)
        
        # Initialize zeroconf (create once per start, not reused between starts)
        self.zc = Zeroconf()
        
        # Create and register service info using the shared zc instance
        self.json_info, self.osc_info = create_zeroconf_services(
            self.zc, APP_NAME, self.http_port, self.osc_port
        )
        
        # Register services with mDNS
        register_services(self.zc, self.json_info, self.osc_info)
        
        logger.info("OSCQuery server started:")
        logger.info(f"  - HTTP JSON: http://{MY_IP}:{self.http_port}")
        logger.info(f"  - OSC UDP: {MY_IP}:{self.osc_port}")
    
    def stop(self) -> None:
        """Stop the OSCQuery server and unregister services."""
        # Unregister mDNS services first
        if self.zc and self.json_info and self.osc_info:
            unregister_services(self.zc, self.json_info, self.osc_info)
        
        # Stop HTTP server
        if self.http_server:
            try:
                self.http_server.shutdown()
            except OSError as e:
                logger.error("OS error shutting down OSCQuery HTTP server", exc_info=True)
            except Exception as e:
                logger.error("Unexpected error shutting down OSCQuery HTTP server", exc_info=True)
        
        # Close zeroconf
        if self.zc:
            try:
                self.zc.close()
            except OSError as e:
                logger.error("OS error closing OSCQuery zeroconf", exc_info=True)
            except Exception as e:
                logger.error("Unexpected error closing OSCQuery zeroconf", exc_info=True)
        
        self.zc = None
        self.json_info = None
        self.osc_info = None
        self.http_server = None
    
    def get_osc_port(self) -> int:
        """Get the OSC port number."""
        return self.osc_port if self.osc_port is not None else get_free_port("UDP")
    
    def get_http_port(self) -> int:
        """Get the HTTP port number."""
        return self.http_port if self.http_port is not None else get_free_port("TCP")
