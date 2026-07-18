from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from gazemotion.core.events import GazeFeatures

# Eye-region selection and normalization adapted from EyeTrax 0.4.0 (MIT):
# https://github.com/ck-zhang/EyeTrax. See EYETRAX_LICENSE.txt in this package.
LEFT_EYE_INDICES = (
    107,
    66,
    105,
    63,
    70,
    55,
    65,
    52,
    53,
    46,
    468,
    469,
    470,
    471,
    472,
    133,
    33,
    173,
    157,
    158,
    159,
    160,
    161,
    246,
    155,
    154,
    153,
    145,
    144,
    163,
    7,
    243,
    190,
    56,
    28,
    27,
    29,
    30,
    247,
    130,
    25,
    110,
    24,
    23,
    22,
    26,
    112,
    244,
    189,
    221,
    222,
    223,
    224,
    225,
    113,
    226,
    31,
    228,
    229,
    230,
    231,
    232,
    233,
    193,
    245,
    128,
    121,
    120,
    119,
    118,
    117,
    111,
    35,
    124,
    143,
    156,
)

RIGHT_EYE_INDICES = (
    336,
    296,
    334,
    293,
    300,
    285,
    295,
    282,
    283,
    276,
    473,
    476,
    475,
    474,
    477,
    362,
    263,
    398,
    384,
    385,
    386,
    387,
    388,
    466,
    382,
    381,
    380,
    374,
    373,
    390,
    249,
    463,
    414,
    286,
    258,
    257,
    259,
    260,
    467,
    359,
    255,
    339,
    254,
    253,
    252,
    256,
    341,
    464,
    413,
    441,
    442,
    443,
    444,
    445,
    342,
    446,
    261,
    448,
    449,
    450,
    451,
    452,
    453,
    417,
    465,
    357,
    350,
    349,
    348,
    347,
    346,
    340,
    265,
    353,
    372,
    383,
)

MUTUAL_INDICES = (4, 10, 151, 9, 152, 234, 454, 58, 288)
FEATURE_INDICES = LEFT_EYE_INDICES + RIGHT_EYE_INDICES + MUTUAL_INDICES
FEATURE_COUNT = len(FEATURE_INDICES) * 3 + 3


@dataclass(frozen=True, slots=True)
class GazeFeatureObservation:
    features: GazeFeatures | None
    confidence: float
    blink_detected: bool
    eye_aspect_ratio: float | None


class HeadNormalizedGazeExtractor:
    """Build pose-normalized 3D eye features from one MediaPipe face result."""

    def __init__(
        self,
        ear_history_frames: int = 50,
        blink_threshold_ratio: float = 0.80,
        blink_min_history_frames: int = 15,
        full_confidence_inter_eye_distance: float = 0.08,
    ) -> None:
        if not 0.0 < blink_threshold_ratio < 1.0:
            raise ValueError("Blink threshold ratio must be between 0 and 1")
        if full_confidence_inter_eye_distance <= 0.0:
            raise ValueError("Full-confidence inter-eye distance must be positive")
        self._blink_min_history_frames = max(blink_min_history_frames, 1)
        self._ear_history: deque[float] = deque(
            maxlen=max(ear_history_frames, self._blink_min_history_frames)
        )
        self._blink_threshold_ratio = blink_threshold_ratio
        self._full_confidence_inter_eye_distance = full_confidence_inter_eye_distance

    @staticmethod
    def _norm(vector: np.ndarray) -> float:
        return float(np.linalg.norm(vector))

    @staticmethod
    def _eye_aspect_ratio(points: np.ndarray) -> float:
        left_width = np.linalg.norm(points[33, :2] - points[133, :2])
        left_height = np.linalg.norm(points[159, :2] - points[145, :2])
        right_width = np.linalg.norm(points[263, :2] - points[362, :2])
        right_height = np.linalg.norm(points[386, :2] - points[374, :2])
        left = left_height / max(float(left_width), 1e-9)
        right = right_height / max(float(right_width), 1e-9)
        return float((left + right) / 2.0)

    def extract(self, landmarks: Any) -> GazeFeatureObservation:
        items = tuple(landmarks)
        if len(items) <= max(FEATURE_INDICES):
            return GazeFeatureObservation(None, 0.0, False, None)

        points = np.asarray(
            [(float(item.x), float(item.y), float(item.z)) for item in items],
            dtype=np.float64,
        )
        if not np.all(np.isfinite(points)):
            return GazeFeatureObservation(None, 0.0, False, None)

        left_corner = points[33]
        right_corner = points[263]
        top_of_head = points[10]
        eye_center = (left_corner + right_corner) / 2.0

        x_axis = right_corner - left_corner
        inter_eye_distance = self._norm(x_axis)
        if inter_eye_distance <= 1e-7:
            return GazeFeatureObservation(None, 0.0, False, None)
        x_axis /= inter_eye_distance

        y_axis = top_of_head - eye_center
        y_axis -= np.dot(y_axis, x_axis) * x_axis
        y_length = self._norm(y_axis)
        if y_length <= 1e-7:
            return GazeFeatureObservation(None, 0.0, False, None)
        y_axis /= y_length

        z_axis = np.cross(x_axis, y_axis)
        z_length = self._norm(z_axis)
        if z_length <= 1e-7:
            return GazeFeatureObservation(None, 0.0, False, None)
        z_axis /= z_length

        rotation = np.column_stack((x_axis, y_axis, z_axis))
        normalized = (points - eye_center) @ rotation
        normalized /= inter_eye_distance

        selected = normalized[np.asarray(FEATURE_INDICES, dtype=int)].reshape(-1)
        yaw = np.arctan2(rotation[1, 0], rotation[0, 0])
        pitch = np.arctan2(
            -rotation[2, 0],
            np.sqrt(rotation[2, 1] ** 2 + rotation[2, 2] ** 2),
        )
        roll = np.arctan2(rotation[2, 1], rotation[2, 2])
        feature_values = np.concatenate((selected, (yaw, pitch, roll)))
        if feature_values.size != FEATURE_COUNT or not np.all(np.isfinite(feature_values)):
            return GazeFeatureObservation(None, 0.0, False, None)

        ear = self._eye_aspect_ratio(points)
        warming_up = len(self._ear_history) < self._blink_min_history_frames
        if warming_up:
            self._ear_history.append(ear)
        if not warming_up:
            blink_threshold = float(np.median(self._ear_history)) * self._blink_threshold_ratio
        else:
            blink_threshold = 0.20
        blink_detected = ear < blink_threshold
        if not warming_up and not blink_detected:
            self._ear_history.append(ear)

        # Inter-eye distance is a useful proxy for whether the face is large enough
        # for stable iris landmarks. A normal desktop pose saturates this near 1.0.
        confidence = min(
            max(inter_eye_distance / self._full_confidence_inter_eye_distance, 0.0),
            1.0,
        )
        if blink_detected:
            return GazeFeatureObservation(None, 0.0, True, ear)
        return GazeFeatureObservation(
            GazeFeatures(tuple(float(value) for value in feature_values)),
            confidence,
            False,
            ear,
        )

    def reset(self) -> None:
        self._ear_history.clear()
