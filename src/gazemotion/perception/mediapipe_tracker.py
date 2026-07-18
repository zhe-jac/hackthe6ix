from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import hypot
from time import monotonic
from typing import Any

from gazemotion.core.config import TrackingSettings
from gazemotion.core.events import GazeFeatures, HandObservation, Point
from gazemotion.perception.models import ensure_model


@dataclass(frozen=True, slots=True)
class PerceptionResult:
    gaze_features: GazeFeatures | None
    gaze_confidence: float
    hand: HandObservation | None
    face_landmarks: tuple[Point, ...] | None = None
    hand_candidate: HandObservation | None = None
    hand_confirmation_progress: int = 0


class MediaPipeTracker:
    """Low-latency face/iris and hand tracking using MediaPipe Tasks."""

    RIGHT_IRIS = (469, 470, 471, 472)
    LEFT_IRIS = (474, 475, 476, 477)
    RIGHT_EYE = (33, 133, 159, 145)
    LEFT_EYE = (362, 263, 386, 374)
    RIGHT_EYE_RING = (33, 160, 158, 133, 153, 144, 33)
    LEFT_EYE_RING = (362, 385, 387, 263, 373, 380, 362)
    HAND_CONNECTIONS = (
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 4),
        (0, 5),
        (5, 6),
        (6, 7),
        (7, 8),
        (5, 9),
        (9, 10),
        (10, 11),
        (11, 12),
        (9, 13),
        (13, 14),
        (14, 15),
        (15, 16),
        (13, 17),
        (17, 18),
        (18, 19),
        (19, 20),
        (0, 17),
    )

    def __init__(
        self,
        max_hands: int = 1,
        settings: TrackingSettings | None = None,
    ) -> None:
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise RuntimeError("MediaPipe is not installed; run `uv sync`") from exc

        self._mp = mp
        self.settings = settings or TrackingSettings()
        face_model = ensure_model("face_landmarker.task")
        hand_model = ensure_model("hand_landmarker.task")
        vision = mp.tasks.vision
        self._face = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(face_model)),
                running_mode=vision.RunningMode.VIDEO,
                num_faces=1,
                min_face_detection_confidence=self.settings.face_detection_confidence,
                min_face_presence_confidence=self.settings.face_presence_confidence,
                min_tracking_confidence=self.settings.face_tracking_confidence,
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
            )
        )
        self._hands = vision.HandLandmarker.create_from_options(
            vision.HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(hand_model)),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=max_hands,
                min_hand_detection_confidence=self.settings.hand_detection_confidence,
                min_hand_presence_confidence=self.settings.hand_presence_confidence,
                min_tracking_confidence=self.settings.hand_tracking_confidence,
            )
        )
        self._last_timestamp_ms = -1
        self._hand_candidate: HandObservation | None = None
        self._hand_candidate_frames = 0
        self._hand_confirmed = False

    @staticmethod
    def _points(landmarks: Iterable[Any]) -> tuple[Point, ...]:
        return tuple(Point(float(item.x), float(item.y)) for item in landmarks)

    @staticmethod
    def _mean(points: tuple[Point, ...], indices: tuple[int, ...]) -> Point:
        return Point(
            sum(points[i].x for i in indices) / len(indices),
            sum(points[i].y for i in indices) / len(indices),
        )

    @staticmethod
    def _hand_center(hand: HandObservation) -> Point:
        indices = (0, 5, 9, 13, 17)
        return Point(
            sum(hand.landmarks[index].x for index in indices) / len(indices),
            sum(hand.landmarks[index].y for index in indices) / len(indices),
        )

    def _stabilize_hand(self, hand: HandObservation | None) -> HandObservation | None:
        if hand is None:
            self._hand_candidate = None
            self._hand_candidate_frames = 0
            self._hand_confirmed = False
            return None

        continuous = False
        if self._hand_candidate is not None:
            previous = self._hand_center(self._hand_candidate)
            current = self._hand_center(hand)
            jump = hypot(current.x - previous.x, current.y - previous.y)
            continuous = (
                hand.handedness == self._hand_candidate.handedness
                and jump <= self.settings.hand_candidate_max_jump
            )

        if continuous:
            self._hand_candidate_frames += 1
        else:
            self._hand_candidate_frames = 1
            self._hand_confirmed = False
        self._hand_candidate = hand

        required = max(self.settings.hand_confirmation_frames, 1)
        if self._hand_candidate_frames >= required:
            self._hand_confirmed = True
        return hand if self._hand_confirmed else None

    @classmethod
    def extract_gaze_features(cls, points: tuple[Point, ...]) -> GazeFeatures | None:
        if len(points) < 478:
            return None

        right_iris = cls._mean(points, cls.RIGHT_IRIS)
        left_iris = cls._mean(points, cls.LEFT_IRIS)

        def relative_eye(iris: Point, eye: tuple[int, int, int, int]) -> tuple[float, float]:
            corner_a, corner_b, upper, lower = (points[i] for i in eye)
            width = max(abs(corner_b.x - corner_a.x), 1e-4)
            height = max(abs(lower.y - upper.y), 1e-4)
            min_x = min(corner_a.x, corner_b.x)
            min_y = min(upper.y, lower.y)
            return ((iris.x - min_x) / width, (iris.y - min_y) / height)

        right_x, right_y = relative_eye(right_iris, cls.RIGHT_EYE)
        left_x, left_y = relative_eye(left_iris, cls.LEFT_EYE)

        nose = points[1]
        left_face = points[234]
        right_face = points[454]
        face_width = max(abs(right_face.x - left_face.x), 1e-4)
        eye_midpoint = Point(
            (points[33].x + points[263].x) / 2,
            (points[33].y + points[263].y) / 2,
        )
        head_x = (nose.x - eye_midpoint.x) / face_width
        head_y = (nose.y - eye_midpoint.y) / face_width

        return GazeFeatures(
            (
                right_x,
                right_y,
                left_x,
                left_y,
                head_x,
                head_y,
                nose.x,
                nose.y,
                face_width,
            )
        )

    def process(self, bgr_frame: Any, timestamp: float | None = None) -> PerceptionResult:
        import cv2

        timestamp = timestamp if timestamp is not None else monotonic()
        timestamp_ms = max(round(timestamp * 1000), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        face_result = self._face.detect_for_video(image, timestamp_ms)
        hand_result = self._hands.detect_for_video(image, timestamp_ms)

        face_points: tuple[Point, ...] | None = None
        gaze_features: GazeFeatures | None = None
        gaze_confidence = 0.0
        if face_result.face_landmarks:
            face_points = self._points(face_result.face_landmarks[0])
            gaze_features = self.extract_gaze_features(face_points)
            gaze_confidence = 0.9 if gaze_features is not None else 0.0

        raw_hand: HandObservation | None = None
        if hand_result.hand_landmarks:
            points = self._points(hand_result.hand_landmarks[0])
            handedness = "unknown"
            confidence = 0.75
            if hand_result.handedness:
                category = hand_result.handedness[0][0]
                handedness = (category.category_name or "unknown").lower()
                confidence = float(category.score or confidence)
            raw_hand = HandObservation(points, handedness, confidence, timestamp)

        hand = self._stabilize_hand(raw_hand)
        return PerceptionResult(
            gaze_features,
            gaze_confidence,
            hand,
            face_points,
            raw_hand,
            self._hand_candidate_frames,
        )

    def draw_debug(self, frame: Any, result: PerceptionResult) -> Any:
        import cv2

        height, width = frame.shape[:2]
        if result.face_landmarks:
            for ring in (self.RIGHT_EYE_RING, self.LEFT_EYE_RING):
                for start, end in zip(ring, ring[1:], strict=False):
                    a = result.face_landmarks[start]
                    b = result.face_landmarks[end]
                    cv2.line(
                        frame,
                        (int(a.x * width), int(a.y * height)),
                        (int(b.x * width), int(b.y * height)),
                        (80, 220, 80),
                        1,
                        cv2.LINE_AA,
                    )
            for index in (*self.RIGHT_IRIS, *self.LEFT_IRIS):
                point = result.face_landmarks[index]
                cv2.circle(
                    frame,
                    (int(point.x * width), int(point.y * height)),
                    2,
                    (0, 255, 0),
                    -1,
                )
        visual_hand = result.hand or result.hand_candidate
        if visual_hand:
            confirmed = result.hand is not None
            color = (255, 180, 0) if confirmed else (110, 110, 110)
            thickness = 2 if confirmed else 1
            for start, end in self.HAND_CONNECTIONS:
                a = visual_hand.landmarks[start]
                b = visual_hand.landmarks[end]
                cv2.line(
                    frame,
                    (int(a.x * width), int(a.y * height)),
                    (int(b.x * width), int(b.y * height)),
                    color,
                    thickness,
                    cv2.LINE_AA,
                )
            for point in visual_hand.landmarks:
                cv2.circle(
                    frame,
                    (int(point.x * width), int(point.y * height)),
                    3 if confirmed else 2,
                    color,
                    -1,
                )
        return frame

    def close(self) -> None:
        self._face.close()
        self._hands.close()

    def __enter__(self) -> MediaPipeTracker:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
