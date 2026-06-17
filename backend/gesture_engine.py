"""
Gesture Engine — State Machine for gesture recognition.

Converts raw landmark streams into discrete, debounced gesture events.
This is where the INTELLIGENCE of the system lives.

Current gestures:
    - SWIPE_RIGHT  → Advance slide (right arrow)
    - SWIPE_LEFT   → Previous slide (left arrow)

Architecture note: The engine now uses Pose (body) landmarks 
to track the arms (wrists) for better long-distance recognition.
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
    """Tracks a single swipe gesture through its lifecycle for BOTH arms."""
    state: SwipeState = SwipeState.IDLE
    start_left_x: float = 0.0
    start_right_x: float = 0.0
    start_time: float = 0.0
    last_gesture_time: float = 0.0
    history_left: list[float] = field(default_factory=list)
    history_right: list[float] = field(default_factory=list)


class GestureEngine:
    """
    Finite State Machine that recognizes gestures from pose landmark data.

    The engine uses a 3-state FSM per gesture type:
        IDLE → TRACKING → COOLDOWN → IDLE

    Key parameters:
        - swipe_threshold: Minimum normalized X displacement to count as swipe (increased for arm)
        - cooldown_ms: Time to ignore new gestures after one fires (debounce)
        - max_swipe_duration: Maximum time (s) a swipe can take (enforces speed)
        - min_samples: Minimum tracking samples before evaluating
    """

    def __init__(
        self,
        swipe_threshold: float = 0.25,      # Increased from 0.15 for wider arm movement
        cooldown_ms: int = 800,
        max_swipe_duration: float = 0.7,    # Decreased from 1.0 to require a faster swipe
        min_samples: int = 4,
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
        pose = landmarks_data.get("pose")
        # MediaPipe Pose has 33 landmarks. 15 is Left Wrist, 16 is Right Wrist.
        if not pose or len(pose) <= 16:
            self._reset_if_tracking()
            return GestureType.NONE

        left_wrist_x = pose[15]["x"]
        right_wrist_x = pose[16]["x"]
        now = time.time()

        return self._update_swipe(left_wrist_x, right_wrist_x, now)

    def _update_swipe(self, left_x: float, right_x: float, now: float) -> GestureType:
        """Run the swipe state machine tracking both arms."""
        t = self._tracker

        # --- COOLDOWN state: wait before accepting new gestures ---
        if t.state == SwipeState.COOLDOWN:
            if now - t.last_gesture_time >= self._cooldown_s:
                t.state = SwipeState.IDLE
            return GestureType.NONE

        # --- IDLE state: start tracking when we see the pose ---
        if t.state == SwipeState.IDLE:
            t.state = SwipeState.TRACKING
            t.start_left_x = left_x
            t.start_right_x = right_x
            t.start_time = now
            t.history_left = [left_x]
            t.history_right = [right_x]
            return GestureType.NONE

        # --- TRACKING state: accumulate samples and evaluate ---
        t.history_left.append(left_x)
        t.history_right.append(right_x)
        elapsed = now - t.start_time

        # Timeout: if the user is just holding their arms still, reset
        if elapsed > self._max_swipe_duration:
            self._reset_tracker()
            return GestureType.NONE

        # Need minimum samples for a reliable reading
        if len(t.history_left) < self._min_samples:
            return GestureType.NONE

        # Calculate displacement (note: MediaPipe X is mirrored)
        # Camera mirror means: physical right swipe = decreasing X
        displacement_left = t.start_left_x - left_x
        displacement_right = t.start_right_x - right_x

        # Check if EITHER arm crossed the threshold
        gesture_left = self._evaluate_arm(t.history_left, displacement_left)
        gesture_right = self._evaluate_arm(t.history_right, displacement_right)

        # If either arm swiped, fire the event (prioritize right swipe if conflicting)
        final_gesture = GestureType.NONE
        if gesture_left != GestureType.NONE:
            final_gesture = gesture_left
        if gesture_right != GestureType.NONE:
            final_gesture = gesture_right

        if final_gesture != GestureType.NONE:
            t.state = SwipeState.COOLDOWN
            t.last_gesture_time = now
            return final_gesture

        return GestureType.NONE

    def _evaluate_arm(self, history: list[float], displacement: float) -> GestureType:
        """Evaluate a single arm's history for a valid swipe."""
        if abs(displacement) >= self._swipe_threshold:
            recent = history[-3:]
            if self._is_consistent(recent, displacement > 0):
                return GestureType.SWIPE_RIGHT if displacement > 0 else GestureType.SWIPE_LEFT
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
        self._tracker.history_left.clear()
        self._tracker.history_right.clear()
