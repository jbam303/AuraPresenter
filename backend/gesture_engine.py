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
from collections import deque

class GestureType(Enum):
    """Recognized gesture types."""
    NONE = auto()
    SWIPE_RIGHT = auto()
    SWIPE_LEFT = auto()

class GestureEngine:
    """
    Evaluates gestures using a sliding window.
    Unlike hand tracking, the pose landmarker sees the body continuously,
    so we cannot rely on an IDLE -> TRACKING state transition. We must
    evaluate the displacement over a recent time window.
    """

    def __init__(
        self,
        swipe_threshold: float = 0.15,      # 15% of screen width (adjusted for velocity check)
        cooldown_ms: int = 1000,            # 1 second cooldown
        window_duration: float = 0.4,       # Evaluate only the last 0.4 seconds (snappier)
        min_samples: int = 4,
    ):
        self._swipe_threshold = swipe_threshold
        self._cooldown_s = cooldown_ms / 1000.0
        self._window_duration = window_duration
        self._min_samples = min_samples
        
        self._last_gesture_time = 0.0
        # Store tuples of (timestamp, x_position)
        self._history_left = deque()
        self._history_right = deque()

    def update(self, landmarks_data: dict) -> GestureType:
        pose = landmarks_data.get("pose")
        now = time.time()

        # Cooldown check
        if now - self._last_gesture_time < self._cooldown_s:
            self._history_left.clear()
            self._history_right.clear()
            return GestureType.NONE

        if not pose or len(pose) <= 16:
            self._history_left.clear()
            self._history_right.clear()
            return GestureType.NONE

        left_wrist_x = pose[15]["x"]
        right_wrist_x = pose[16]["x"]

        self._history_left.append((now, left_wrist_x))
        self._history_right.append((now, right_wrist_x))

        # Prune old samples outside the window
        while self._history_left and now - self._history_left[0][0] > self._window_duration:
            self._history_left.popleft()
        while self._history_right and now - self._history_right[0][0] > self._window_duration:
            self._history_right.popleft()

        # Check for gestures
        gesture_left = self._evaluate_arm(list(self._history_left))
        gesture_right = self._evaluate_arm(list(self._history_right))

        final_gesture = GestureType.NONE
        if gesture_left != GestureType.NONE:
            final_gesture = gesture_left
        elif gesture_right != GestureType.NONE:
            final_gesture = gesture_right

        if final_gesture != GestureType.NONE:
            self._last_gesture_time = now
            self._history_left.clear()
            self._history_right.clear()
            return final_gesture

        return GestureType.NONE

    def _evaluate_arm(self, history: list[tuple[float, float]]) -> GestureType:
        if len(history) < self._min_samples:
            return GestureType.NONE

        oldest_time, oldest_x = history[0]
        newest_time, newest_x = history[-1]
        
        elapsed_time = newest_time - oldest_time
        if elapsed_time <= 0:
            return GestureType.NONE

        # En una imagen espejada (mirrored):
        # Mover tu brazo hacia TU DERECHA hace que la X aumente (de 0.0 a 1.0).
        # Mover tu brazo hacia TU IZQUIERDA hace que la X disminuya.
        displacement = newest_x - oldest_x
        
        # Calculamos la VELOCIDAD (Unidades de pantalla por segundo)
        velocity = displacement / elapsed_time

        # Requerimos una distancia mínima (0.15) Y una velocidad mínima (0.5 unidades/seg)
        # Esto filtra los movimientos largos pero muy lentos (acomodarse la postura)
        if abs(displacement) >= 0.15 and abs(velocity) >= 0.5:
            # Check consistency of the last few frames to avoid noise
            recent_x = [pt[1] for pt in history[-4:]]
            
            # Si se movió a la derecha (displacement > 0), esperamos que la X vaya aumentando
            is_moving_right = displacement > 0
            if self._is_consistent(recent_x, is_moving_right):
                return GestureType.SWIPE_RIGHT if is_moving_right else GestureType.SWIPE_LEFT
                
        return GestureType.NONE

    def _is_consistent(self, points: list[float], moving_right: bool) -> bool:
        """Verifica que los últimos puntos no vayan fuertemente en la dirección contraria."""
        if len(points) < 2:
            return True
        for i in range(1, len(points)):
            if moving_right and points[i] < points[i - 1] - 0.03: # 3% noise margin en contra
                return False
            if not moving_right and points[i] > points[i - 1] + 0.03:
                return False
        return True
