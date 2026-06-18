"""
Motion Engine — State Machine for phone accelerometer gesture recognition.

Detects flick gestures (quick, intentional movements) from accelerometer data
sent by the phone's DeviceMotion API.

Current gestures:
    - FLICK_RIGHT  → Advance slide (right arrow)
    - FLICK_LEFT   → Previous slide (left arrow)

Uses the same FSM pattern as gesture_engine.py (IDLE → COOLDOWN)
but simplified: a flick is a single acceleration spike, not a tracked path.
"""

import time
from enum import Enum, auto


class MotionGestureType(Enum):
    """Recognized motion gesture types."""
    NONE = auto()
    FLICK_RIGHT = auto()
    FLICK_LEFT = auto()


class MotionEngine:
    """
    Detects flick gestures from accelerometer data.

    A flick is a sudden, sharp acceleration along the X axis
    that exceeds a threshold. The engine uses a simple
    2-state FSM: IDLE → COOLDOWN.

    Parameters:
        flick_threshold: Minimum acceleration (m/s²) to register as a flick.
                         Uses `acceleration` (gravity removed), so 8 m/s² is
                         a deliberate flick. Falls back gracefully if only
                         accelerationIncludingGravity is available.
        cooldown_ms: Time to ignore new gestures after one fires (debounce).
    """

    def __init__(
        self,
        flick_threshold: float = 8.0,
        cooldown_ms: int = 800,
    ):
        self._flick_threshold = flick_threshold
        self._cooldown_s = cooldown_ms / 1000.0
        self._in_cooldown = False
        self._last_gesture_time = 0.0

    def set_threshold(self, threshold: float) -> None:
        """Update the minimum acceleration threshold."""
        self._flick_threshold = max(1.0, threshold)

    def update(self, telemetry: dict) -> MotionGestureType:
        """
        Feed new telemetry data and get back a gesture event (or NONE).

        Args:
            telemetry: Dict with at least "ax" (X-axis acceleration in m/s²).
                       Positive ax = rightward, Negative ax = leftward.

        Returns:
            MotionGestureType indicating what gesture was detected.
        """
        now = time.time()

        # Cooldown check
        if self._in_cooldown:
            if now - self._last_gesture_time >= self._cooldown_s:
                self._in_cooldown = False
            else:
                return MotionGestureType.NONE

        ax = telemetry.get("ax", 0.0)

        # Check if acceleration exceeds threshold
        if abs(ax) >= self._flick_threshold:
            gesture = (
                MotionGestureType.FLICK_RIGHT
                if ax > 0
                else MotionGestureType.FLICK_LEFT
            )
            self._in_cooldown = True
            self._last_gesture_time = now
            return gesture

        return MotionGestureType.NONE
