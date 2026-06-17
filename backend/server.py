"""
Server — WebSocket orchestrator (dual-channel).

Bridges Camera Vision + Phone Telemetry to the Frontend UI.
Supports two client types:
    - viewer: Desktop frontend (receives data for rendering)
    - phone:  Mobile remote (sends accelerometer telemetry)
"""

import asyncio
import json
import logging
import signal
import socket
import subprocess
import time

from websockets.asyncio.server import serve

from vision import VisionProcessor
from gesture_engine import GestureEngine, GestureType
from motion_engine import MotionEngine, MotionGestureType

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


def press_key_applescript(key_name: str) -> None:
    """Simulate a key press using native AppleScript."""
    key_code_map = {
        "Right": 124,
        "Left": 123,
        "Up": 126,
        "Down": 125,
        "Return": 36,
        "Space": 49,
        "Escape": 53,
    }
    code = key_code_map.get(key_name)
    if code is None:
        logger.warning(f"No AppleScript key code for: {key_name}")
        return

    script = f'tell application "System Events" to key code {code}'
    subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        timeout=2,
    )


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

                    elif msg_type == "telemetry":
                        gesture = self._motion_engine.update(msg)
                        if gesture != MotionGestureType.NONE:
                            key = MOTION_KEY_MAP.get(gesture)
                            if key:
                                press_key_applescript(key)
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
                        press_key_applescript(key)
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


def main() -> None:
    server = AuraPresenterServer()

    def signal_handler(sig, frame):
        server.shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Server terminated.")


if __name__ == "__main__":
    main()
