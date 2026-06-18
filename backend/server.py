"""
Server — WebSocket orchestrator (dual-channel).

Bridges Camera Vision + Phone Telemetry to the Frontend UI.
Supports two client types:
    - viewer: Desktop frontend (receives data for rendering)
    - phone:  Mobile remote (sends accelerometer telemetry)
"""

import asyncio
import ipaddress
import json
import logging
import platform
import signal
import socket
import ssl
import subprocess
import time
import sys
import os
import threading
import http.server
import socketserver

try:
    import webview
except ImportError:
    webview = None

from websockets.asyncio.server import serve

from vision import VisionProcessor
from gesture_engine import GestureEngine, GestureType
from motion_engine import MotionEngine, MotionGestureType
from updater import start_update_thread

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AuraPresenter")
logging.getLogger("websockets").setLevel(logging.WARNING)


# --- Configuration ---
WS_HOST = "0.0.0.0"
WS_PORT = 8765
TARGET_FPS = 30
FRAME_INTERVAL = 1.0 / TARGET_FPS
VITE_PORT = 5173


# --- Gesture → Key mapping ---
CAMERA_KEY_MAP: dict[GestureType, str] = {
    GestureType.SWIPE_RIGHT: "Right",
    GestureType.SWIPE_LEFT: "Left",
}

MOTION_KEY_MAP: dict[MotionGestureType, str] = {
    MotionGestureType.FLICK_RIGHT: "Right",
    MotionGestureType.FLICK_LEFT: "Left",
}


def get_local_ip() -> str:
    """Detect the machine's LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def press_key_crossplatform(key_name: str) -> None:
    """Press a key using AppleScript on macOS, or PyAutoGUI on Windows/Linux."""
    system = platform.system()
    
    # Map string like "Right" to "right"
    key_name = key_name.lower()
    
    if system == "Darwin":
        try:
            key_code_map = {
                "right": 124,
                "left": 123,
                "up": 126,
                "down": 125,
                "return": 36,
                "space": 49,
                "escape": 53,
            }
            code = key_code_map.get(key_name)
            if code is None:
                return

            script = f'tell application "System Events" to key code {code}'
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=2)
        except Exception as e:
            logger.error(f"Error executing AppleScript: {e}")
    else:
        try:
            import pyautogui
            pyautogui.press(key_name)
        except ImportError:
            logger.error("pyautogui is not installed. Keyboard simulation will not work on this OS.")
        except Exception as e:
            logger.error(f"Error executing PyAutoGUI: {e}")

class AuraPresenterServer:
    """Manages camera loop, phone telemetry, and WebSocket broadcast."""

    def __init__(self):
        self._vision = VisionProcessor()
        self._camera_engine = GestureEngine()
        self._motion_engine = MotionEngine()
        self._viewers: set = set()
        self._phones: set = set()
        self._running = False
        self._local_ip = get_local_ip()

    async def _register_viewer(self, ws) -> None:
        """Register a new viewer client and send config."""
        self._viewers.add(ws)
        logger.info(f"Viewer connected. Viewers: {len(self._viewers)}")

        # Send config with local IP for QR code generation
        config = {
            "type": "config",
            "local_ip": self._local_ip,
            "ws_port": WS_PORT,
            "vite_port": VITE_PORT,
        }
        try:
            await ws.send(json.dumps(config))
        except Exception:
            pass

    async def _promote_to_phone(self, ws) -> None:
        """Move a client from viewers to phones."""
        self._viewers.discard(ws)
        self._phones.add(ws)
        logger.info(
            f"Phone connected. Phones: {len(self._phones)}, "
            f"Viewers: {len(self._viewers)}"
        )

    async def _unregister(self, ws) -> None:
        """Remove client from all sets."""
        was_phone = ws in self._phones
        self._viewers.discard(ws)
        self._phones.discard(ws)
        label = "Phone" if was_phone else "Viewer"
        logger.info(
            f"{label} disconnected. Viewers: {len(self._viewers)}, "
            f"Phones: {len(self._phones)}"
        )

    async def _broadcast_viewers(self, message: str) -> None:
        """Send a message to all viewer clients, pruning dead ones."""
        if not self._viewers:
            return

        dead = set()
        for client in self._viewers:
            try:
                await client.send(message)
            except Exception:
                dead.add(client)

        if dead:
            self._viewers -= dead
            logger.info(
                f"Pruned {len(dead)} dead viewer(s). Active: {len(self._viewers)}"
            )

    async def _send_to_client(self, ws, message: str) -> bool:
        """Send a message to a single client. Returns False if dead."""
        try:
            await ws.send(message)
            return True
        except Exception:
            return False

    async def _handler(self, ws) -> None:
        """Handle a single WebSocket connection lifecycle."""
        await self._register_viewer(ws)
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    msg_type = msg.get("type")

                    if msg_type == "phone_init":
                        await self._promote_to_phone(ws)
                        await self._send_to_client(ws, json.dumps({
                            "type": "phone_ack",
                            "status": "connected",
                        }))

                    elif msg_type == "ping":
                        await self._send_to_client(ws, json.dumps({"type": "pong"}))

                    elif msg_type == "update_sensitivity":
                        threshold = msg.get("threshold", 8.0)
                        self._motion_engine.set_threshold(threshold)
                        logger.info(f"Phone sensitivity updated to {threshold}")

                    elif msg_type == "telemetry":
                        gesture = self._motion_engine.update(msg)
                        if gesture != MotionGestureType.NONE:
                            key = MOTION_KEY_MAP.get(gesture)
                            if key:
                                press_key_crossplatform(key)
                                logger.info(
                                    f"Phone Gesture: {gesture.name} → Key: {key}"
                                )

                            # Notify the phone that sent the gesture
                            await self._send_to_client(ws, json.dumps({
                                "type": "phone_gesture",
                                "gesture": gesture.name,
                            }))

                            # Notify all desktop viewers
                            await self._broadcast_viewers(json.dumps({
                                "type": "phone_gesture",
                                "gesture": gesture.name,
                            }))

                except json.JSONDecodeError:
                    pass
        finally:
            await self._unregister(ws)

    async def _camera_loop(self) -> None:
        """Main loop: camera → process → detect → broadcast to viewers."""
        self._vision.start()
        self._running = True
        logger.info("Camera started. Processing frames...")

        try:
            while self._running:
                loop_start = time.time()

                success, frame = self._vision.read_frame()
                if not success:
                    await asyncio.sleep(0.01)
                    continue

                landmarks_data = self._vision.process(frame)
                gesture = self._camera_engine.update(landmarks_data)

                message = {
                    "type": "frame",
                    "hands": landmarks_data["hands"],
                    "pose": landmarks_data["pose"],
                    "frame_shape": landmarks_data["frame_shape"],
                    "gesture": (
                        gesture.name if gesture != GestureType.NONE else None
                    ),
                }

                if gesture != GestureType.NONE:
                    key = CAMERA_KEY_MAP.get(gesture)
                    if key:
                        press_key_crossplatform(key)
                        logger.info(f"Camera Gesture: {gesture.name} → Key: {key}")

                # Only broadcast to viewers (not phones)
                await self._broadcast_viewers(json.dumps(message))

                elapsed = time.time() - loop_start
                sleep_time = max(0, FRAME_INTERVAL - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        finally:
            self._vision.stop()
            logger.info("Camera stopped.")

    async def run(self) -> None:
        """Start the WebSocket server and camera loop."""
        logger.info(f"Starting WebSocket server on ws://{WS_HOST}:{WS_PORT}")
        logger.info(f"LAN IP: {self._local_ip}")
        logger.info(
            f"Phone URL: http://{self._local_ip}:{VITE_PORT}/phone.html"
        )

        async with serve(self._handler, WS_HOST, WS_PORT):
            logger.info("Server ready. Waiting for clients...")
            await self._camera_loop()

    def shutdown(self) -> None:
        """Signal the camera loop to stop."""
        self._running = False
        logger.info("Shutdown signal received.")


def get_static_folder() -> str:
    """Return the path to the built frontend files."""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        return os.path.join(sys._MEIPASS, 'dist')
    return os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')


def get_cert_dir() -> str:
    """Return the directory where SSL certs are stored."""
    if getattr(sys, 'frozen', False):
        # When packaged, store certs next to the executable
        base = os.path.dirname(sys.executable)
        if sys.platform == 'darwin':
            # macOS .app bundle: go up to the .app parent directory
            base = os.path.dirname(os.path.dirname(os.path.dirname(base)))
        cert_dir = os.path.join(base, '.aurapresenter_certs')
    else:
        cert_dir = os.path.join(os.path.dirname(__file__), '.certs')
    os.makedirs(cert_dir, exist_ok=True)
    return cert_dir


def generate_self_signed_cert() -> tuple[str, str]:
    """Generate a self-signed SSL certificate if one doesn't exist. Returns (certfile, keyfile)."""
    cert_dir = get_cert_dir()
    certfile = os.path.join(cert_dir, 'cert.pem')
    keyfile = os.path.join(cert_dir, 'key.pem')

    if os.path.exists(certfile) and os.path.exists(keyfile):
        logger.info("Using existing SSL certificate.")
        return certfile, keyfile

    logger.info("Generating self-signed SSL certificate...")
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "AuraPresenter Local"),
        ])

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.IPAddress(ipaddress.IPv4Address("0.0.0.0")),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                    x509.DNSName("localhost"),
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )

        with open(keyfile, 'wb') as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))
        with open(certfile, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        logger.info(f"SSL certificate generated at {cert_dir}")
    except ImportError:
        # Fallback: use openssl CLI
        logger.info("cryptography not installed, falling back to openssl CLI...")
        subprocess.run([
            'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
            '-keyout', keyfile, '-out', certfile,
            '-days', '3650', '-nodes',
            '-subj', '/CN=AuraPresenter Local',
        ], capture_output=True)

    return certfile, keyfile


def start_http_server(port: int):
    """Run an HTTPS server to serve frontend static files (enables DeviceMotion on phones)."""
    static_dir = get_static_folder()
    certfile, keyfile = generate_self_signed_cert()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=static_dir, **kwargs)

        def log_message(self, format, *args):
            pass

    httpd = socketserver.ThreadingTCPServer(("0.0.0.0", port), Handler)

    # Wrap socket with SSL
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
    httpd.socket = ssl_ctx.wrap_socket(httpd.socket, server_side=True)

    logger.info(f"Serving static files from {static_dir} at https://0.0.0.0:{port}")
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()


def main() -> None:
    # 0. Start Auto-Updater thread
    start_update_thread()

    # 1. Start the HTTP static server
    start_http_server(VITE_PORT)

    server = AuraPresenterServer()

    # 2. Start WebSocket and Camera loop in a daemon thread
    # PyWebView REQUIRES the main thread, so asyncio must run in background
    def run_asyncio_server():
        try:
            asyncio.run(server.run())
        except Exception as e:
            logger.error(f"Server loop error: {e}")

    ws_thread = threading.Thread(target=run_asyncio_server, daemon=True)
    ws_thread.start()

    # 3. Create Desktop Window
    if webview:
        window = webview.create_window(
            'AuraPresenter', 
            f'https://127.0.0.1:{VITE_PORT}',
            width=1000,
            height=700,
            background_color='#0c101a' # matches --bg-primary
        )
        
        # Shutdown cleanly when window closes
        def on_closed():
            server.shutdown()
            os._exit(0)

        window.events.closed += on_closed
        logger.info("Starting PyWebView...")
        webview.start()
    else:
        logger.warning("pywebview not installed. Running headless. Press Ctrl+C to stop.")
        def signal_handler(sig, frame):
            server.shutdown()
            sys.exit(0)
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.shutdown()

if __name__ == "__main__":
    main()
