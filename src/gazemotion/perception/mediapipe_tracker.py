from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import hypot
from time import monotonic
from typing import Any

from gazemotion.core.config import TrackingSettings
from gazemotion.core.events import GazeFeatures, HandObservation, Point
from gazemotion.gaze.features import HeadNormalizedGazeExtractor
from gazemotion.perception.models import ensure_model


@dataclass(frozen=True, slots=True)
class PerceptionResult:
    gaze_features: GazeFeatures | None
    gaze_confidence: float
    hand: HandObservation | None
    face_landmarks: tuple[Point, ...] | None = None
    hand_candidate: HandObservation | None = None
    hand_confirmation_progress: int = 0
    hands: tuple[HandObservation, ...] = ()
    hand_candidates: tuple[HandObservation, ...] = ()
    hand_confirmation_progresses: tuple[int, ...] = ()
    blink_detected: bool = False
    eye_aspect_ratio: float | None = None


@dataclass(slots=True)
class _HandTrackState:
    track_id: int
    hand: HandObservation
    confirmation_frames: int = 1
    confirmed: bool = False


class MediaPipeTracker:
    """Low-latency face/iris and hand tracking using MediaPipe Tasks."""

    RIGHT_IRIS = (469, 470, 471, 472)
    LEFT_IRIS = (474, 475, 476, 477)
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
        self._max_hands = max(max_hands, 1)
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
        self._hand_tracks: dict[int, _HandTrackState] = {}
        self._next_hand_track_id = 1
        self._gaze_extractor = HeadNormalizedGazeExtractor(
            self.settings.gaze_ear_history_frames,
            self.settings.gaze_blink_threshold_ratio,
            self.settings.gaze_blink_min_history_frames,
            self.settings.gaze_full_confidence_inter_eye_distance,
        )

    @staticmethod
    def _points(landmarks: Iterable[Any]) -> tuple[Point, ...]:
        return tuple(Point(float(item.x), float(item.y)) for item in landmarks)

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

    @staticmethod
    def _with_handedness(hand: HandObservation, handedness: str) -> HandObservation:
        if hand.handedness == handedness:
            return hand
        return HandObservation(
            hand.landmarks,
            handedness,
            hand.confidence,
            hand.timestamp,
        )

    def _stabilize_hands(
        self,
        hands: tuple[HandObservation, ...],
    ) -> tuple[
        tuple[HandObservation, ...],
        tuple[HandObservation, ...],
        tuple[int, ...],
    ]:
        """Match detections to short-lived tracks and confirm each hand independently."""
        if not hands:
            self._hand_tracks.clear()
            return (), (), ()

        pairings: list[tuple[float, int, int]] = []
        for detection_index, hand in enumerate(hands):
            center = self._hand_center(hand)
            for track_id, track in self._hand_tracks.items():
                previous_center = self._hand_center(track.hand)
                jump = hypot(center.x - previous_center.x, center.y - previous_center.y)
                if jump > self.settings.hand_candidate_max_jump:
                    continue
                handedness_penalty = 0.05 if hand.handedness != track.hand.handedness else 0.0
                pairings.append((jump + handedness_penalty, detection_index, track_id))

        matched_detections: dict[int, int] = {}
        matched_tracks: set[int] = set()
        for _cost, detection_index, track_id in sorted(pairings):
            if detection_index in matched_detections or track_id in matched_tracks:
                continue
            matched_detections[detection_index] = track_id
            matched_tracks.add(track_id)

        current_tracks: dict[int, _HandTrackState] = {}
        for detection_index, detected_hand in enumerate(hands):
            matched_track_id = matched_detections.get(detection_index)
            if matched_track_id is None:
                track_id = self._next_hand_track_id
                self._next_hand_track_id += 1
                track = _HandTrackState(track_id, detected_hand)
            else:
                track_id = matched_track_id
                previous_track = self._hand_tracks[track_id]
                stable_label = previous_track.hand.handedness
                stable_hand = self._with_handedness(detected_hand, stable_label)
                track = _HandTrackState(
                    track_id,
                    stable_hand,
                    previous_track.confirmation_frames + 1,
                    previous_track.confirmed,
                )

            required = max(self.settings.hand_confirmation_frames, 1)
            if track.confirmation_frames >= required:
                track.confirmed = True
            current_tracks[track_id] = track

        self._hand_tracks = current_tracks
        ordered = sorted(
            current_tracks.values(),
            key=lambda track: (track.hand.handedness, track.track_id),
        )
        confirmed = tuple(track.hand for track in ordered if track.confirmed)
        candidates = tuple(track.hand for track in ordered)
        progress = tuple(track.confirmation_frames for track in ordered)
        return confirmed, candidates, progress

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
        blink_detected = False
        eye_aspect_ratio: float | None = None
        if face_result.face_landmarks:
            raw_face_landmarks = face_result.face_landmarks[0]
            face_points = self._points(raw_face_landmarks)
            gaze_observation = self._gaze_extractor.extract(raw_face_landmarks)
            gaze_features = gaze_observation.features
            gaze_confidence = gaze_observation.confidence
            blink_detected = gaze_observation.blink_detected
            eye_aspect_ratio = gaze_observation.eye_aspect_ratio

        raw_hands: list[HandObservation] = []
        handedness_results = hand_result.handedness or []
        for index, landmarks in enumerate(hand_result.hand_landmarks or ()):
            points = self._points(landmarks)
            handedness = "unknown"
            confidence = 0.75
            if index < len(handedness_results) and handedness_results[index]:
                category = handedness_results[index][0]
                handedness = (category.category_name or "unknown").lower()
                confidence = float(category.score or confidence)
            raw_hands.append(HandObservation(points, handedness, confidence, timestamp))

        raw_hand = raw_hands[0] if raw_hands else None
        hands: tuple[HandObservation, ...]
        candidates: tuple[HandObservation, ...]
        progresses: tuple[int, ...]
        if self._max_hands == 1:
            hand = self._stabilize_hand(raw_hand)
            hands = (hand,) if hand is not None else ()
            candidates = (raw_hand,) if raw_hand is not None else ()
            progresses = (self._hand_candidate_frames,) if raw_hand is not None else ()
        else:
            hands, candidates, progresses = self._stabilize_hands(tuple(raw_hands))
            hand = hands[0] if hands else None
        return PerceptionResult(
            gaze_features,
            gaze_confidence,
            hand,
            face_points,
            raw_hand,
            progresses[0] if progresses else 0,
            hands,
            candidates,
            progresses,
            blink_detected,
            eye_aspect_ratio,
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
        fallback_hand = result.hand or result.hand_candidate
        visual_hands: tuple[HandObservation, ...] = result.hand_candidates
        if not visual_hands and fallback_hand is not None:
            visual_hands = (fallback_hand,)
        confirmed_ids = {id(hand) for hand in result.hands}
        if not confirmed_ids and result.hand is not None:
            confirmed_ids.add(id(result.hand))
        for visual_hand in visual_hands:
            confirmed = id(visual_hand) in confirmed_ids
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
            center = self._hand_center(visual_hand)
            cv2.putText(
                frame,
                visual_hand.handedness.upper(),
                (int(center.x * width), int(center.y * height)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
                cv2.LINE_AA,
            )
        return frame

    def close(self) -> None:
        self._face.close()
        self._hands.close()

    def __enter__(self) -> MediaPipeTracker:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
