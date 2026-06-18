"""
Vision Module — Single Responsibility: Camera + MediaPipe landmark extraction.

Uses the MediaPipe Tasks API (0.10.35+) with HandLandmarker and PoseLandmarker.
Returns raw landmark data. Zero gesture logic lives here.
"""

import os
import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    PoseLandmarker,
    PoseLandmarkerOptions,
)
from mediapipe.tasks.python.vision.hand_landmarker import (
    vision_task_running_mode,
)

VisionRunningMode = vision_task_running_mode.VisionTaskRunningMode

# Model paths (relative to this file)
_DIR = os.path.dirname(os.path.abspath(__file__))
HAND_MODEL_PATH = os.path.join(_DIR, "hand_landmarker.task")
POSE_MODEL_PATH = os.path.join(_DIR, "pose_landmarker.task")


class VisionProcessor:
    """Processes webcam frames and extracts hand/pose landmarks via MediaPipe Tasks."""

    def __init__(self, camera_index: int = 0):
        self._camera_index = camera_index
        self._cap: cv2.VideoCapture | None = None
        self._hands: HandLandmarker | None = None
        self._pose: PoseLandmarker | None = None
        self._frame_timestamp_ms: int = 0

    def start(self) -> None:
        """Initialize camera and MediaPipe processors."""
        self._cap = cv2.VideoCapture(self._camera_index)

        # Hand Landmarker — VIDEO mode for sequential frame processing
        hand_options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=HAND_MODEL_PATH),
            running_mode=VisionRunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.7,
            min_tracking_confidence=0.6,
        )
        self._hands = HandLandmarker.create_from_options(hand_options)

        # Pose Landmarker — VIDEO mode
        pose_options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=POSE_MODEL_PATH),
            running_mode=VisionRunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )
        self._pose = PoseLandmarker.create_from_options(pose_options)

    def stop(self) -> None:
        """Release all resources."""
        if self._hands:
            self._hands.close()
        if self._pose:
            self._pose.close()
        if self._cap:
            self._cap.release()

    def read_frame(self) -> tuple[bool, "cv2.Mat | None"]:
        """Read a single frame from the camera."""
        if not self._cap or not self._cap.isOpened():
            # Retry opening if it failed (e.g. waiting for Mac permissions)
            import time
            time.sleep(0.5)
            self._cap = cv2.VideoCapture(self._camera_index)
            if not self._cap.isOpened():
                return False, None
        return self._cap.read()

    def process(self, frame: "cv2.Mat") -> dict:
        """
        Process a BGR frame and return extracted landmarks.

        Returns a dict with:
            - "hands": list of hand landmark dicts (up to 2 hands)
            - "pose": pose landmark dict or None
            - "frame_shape": [h, w] of the processed frame
        """
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # MediaPipe Tasks requires an mp.Image wrapper
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        # Increment timestamp (must be monotonically increasing for VIDEO mode)
        self._frame_timestamp_ms += 33  # ~30 FPS

        # Process hands
        hand_result = self._hands.detect_for_video(
            mp_image, self._frame_timestamp_ms
        )
        hands_data = []
        if hand_result.hand_landmarks:
            for hand_landmarks in hand_result.hand_landmarks:
                landmarks = []
                for lm in hand_landmarks:
                    landmarks.append({
                        "x": round(lm.x, 4),
                        "y": round(lm.y, 4),
                        "z": round(lm.z, 4),
                    })
                hands_data.append(landmarks)

        # Process pose (body)
        pose_result = self._pose.detect_for_video(
            mp_image, self._frame_timestamp_ms
        )
        pose_data = None
        if pose_result.pose_landmarks:
            pose_data = []
            for lm in pose_result.pose_landmarks[0]:
                pose_data.append({
                    "x": round(lm.x, 4),
                    "y": round(lm.y, 4),
                    "z": round(lm.z, 4),
                    "visibility": round(lm.visibility, 3),
                })

        return {
            "hands": hands_data,
            "pose": pose_data,
            "frame_shape": [h, w],
        }
