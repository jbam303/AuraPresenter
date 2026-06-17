"""
Gesture Engine — State Machine for gesture recognition.

Converts raw landmark streams into discrete, debounced gesture events.
This is where the INTELLIGENCE of the system lives.

Current gestures:
    - SWIPE_RIGHT  → Advance slide (right arrow)
    - SWIPE_LEFT   → Previous slide (left arrow)

Architecture note: The engine is designed to be extensible.
Body gestures can be added by creating new recognizer methods
that consume pose landmarks instead of hand landmarks.
"""

import time
from enum import Enum, auto
from dataclasses import dataclass, field


class GestureType(Enum):
    """Recognized gesture types."""
    NONE = auto()
    SWIPE_RIGHT = auto()
    SWIPE_LEFT = auto()


class SwipeState(Enum):
    """State machine states for swipe detection."""
    IDLE = auto()
    TRACKING = auto()
    COOLDOWN = auto()


@dataclass
class SwipeTracker:
    """Tracks a single swipe gesture through its lifecycle."""
    state: SwipeState = SwipeState.IDLE
    start_x: float = 0.0
    start_time: float = 0.0
    last_gesture_time: float = 0.0
    history: list[float] = field(default_factory=list)


class GestureEngine:
    """
    Finite State Machine that recognizes gestures from landmark data.

    The engine uses a 3-state FSM per gesture type:
        IDLE → TRACKING → COOLDOWN → IDLE

    Key parameters:
        - swipe_threshold: Minimum normalized X displacement to count as swipe
        - cooldown_ms: Time to ignore new gestures after one fires (debounce)
        - max_swipe_duration: Maximum time (s) a swipe can take
        - min_samples: Minimum tracking samples before evaluating
    """

    def __init__(
        self,
        swipe_threshold: float = 0.15,
        cooldown_ms: int = 800,
        max_swipe_duration: float = 1.0,
        min_samples: int = 5,
    ):
        self._swipe_threshold = swipe_threshold
        self._cooldown_s = cooldown_ms / 1000.0
        self._max_swipe_duration = max_swipe_duration
        self._min_samples = min_samples
        self._tracker = SwipeTracker()

    def update(self, landmarks_data: dict) -> GestureType:
        """
        Feed new landmark data and get back a gesture event (or NONE).

        Args:
            landmarks_data: Dict from VisionProcessor.process()

        Returns:
            GestureType indicating what gesture was detected (if any).
        """
        hands = landmarks_data.get("hands", [])
        if not hands:
            self._reset_if_tracking()
            return GestureType.NONE

        # Use the wrist landmark (index 0) of the first detected hand
        # as the primary tracking point for swipe gestures.
        wrist = hands[0][0]
        wrist_x = wrist["x"]
        now = time.time()

        return self._update_swipe(wrist_x, now)

    def _update_swipe(self, x: float, now: float) -> GestureType:
        """Run the swipe state machine."""
        t = self._tracker

        # --- COOLDOWN state: wait before accepting new gestures ---
        if t.state == SwipeState.COOLDOWN:
            if now - t.last_gesture_time >= self._cooldown_s:
                t.state = SwipeState.IDLE
            return GestureType.NONE

        # --- IDLE state: start tracking when we see a hand ---
        if t.state == SwipeState.IDLE:
            t.state = SwipeState.TRACKING
            t.start_x = x
            t.start_time = now
            t.history = [x]
            return GestureType.NONE

        # --- TRACKING state: accumulate samples and evaluate ---
        t.history.append(x)
        elapsed = now - t.start_time

        # Timeout: if the user is just holding their hand still, reset
        if elapsed > self._max_swipe_duration:
            self._reset_tracker()
            return GestureType.NONE

        # Need minimum samples for a reliable reading
        if len(t.history) < self._min_samples:
            return GestureType.NONE

        # Calculate displacement (note: MediaPipe X is mirrored)
        # Camera mirror means: physical right swipe = decreasing X
        displacement = t.start_x - x

        if abs(displacement) >= self._swipe_threshold:
            # Check direction consistency: the last few points
            # should trend in the same direction (noise filter)
            recent = t.history[-3:]
            if self._is_consistent(recent, displacement > 0):
                gesture = (
                    GestureType.SWIPE_RIGHT
                    if displacement > 0
                    else GestureType.SWIPE_LEFT
                )
                t.state = SwipeState.COOLDOWN
                t.last_gesture_time = now
                return gesture

        return GestureType.NONE

    def _is_consistent(self, points: list[float], expect_decrease: bool) -> bool:
        """Check that recent points trend consistently in one direction."""
        for i in range(1, len(points)):
            if expect_decrease and points[i] >= points[i - 1]:
                return False
            if not expect_decrease and points[i] <= points[i - 1]:
                return False
        return True

    def _reset_if_tracking(self) -> None:
        """Reset tracker only if currently in TRACKING state."""
        if self._tracker.state == SwipeState.TRACKING:
            self._reset_tracker()

    def _reset_tracker(self) -> None:
        """Return tracker to IDLE."""
        self._tracker.state = SwipeState.IDLE
        self._tracker.history.clear()
