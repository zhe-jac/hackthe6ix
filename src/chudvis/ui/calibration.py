from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

import numpy as np

from chudvis.capture.camera import OpenCVCamera
from chudvis.core.events import GazeFeatures, Point
from chudvis.gaze.model import CalibrationProfile
from chudvis.gaze.training import TargetSamples, robust_sample_subset, select_best_profile
from chudvis.perception.mediapipe_tracker import MediaPipeTracker
from chudvis.ui.window import close_window, window_is_open


def dense_grid_targets(
    grid_size: int = 5,
    margin: float = 0.10,
) -> tuple[Point, ...]:
    if grid_size < 2:
        raise ValueError("Calibration grid must contain at least two rows and columns")
    if not 0.0 <= margin < 0.5:
        raise ValueError("Calibration margin must be in [0, 0.5)")
    coordinates = np.linspace(margin, 1.0 - margin, grid_size)
    targets: list[Point] = []
    for row, y in enumerate(coordinates):
        xs = coordinates if row % 2 == 0 else coordinates[::-1]
        targets.extend(Point(float(x), float(y)) for x in xs)
    return tuple(targets)


def drift_resistant_target_order(targets: tuple[Point, ...]) -> tuple[Point, ...]:
    """Break the correlation between capture time and a target's screen position."""
    if len(targets) < 2:
        return targets
    generator = np.random.default_rng(0xC0D15)
    order = generator.permutation(len(targets))
    return tuple(targets[int(index)] for index in order)


VALIDATION_TARGETS = (
    Point(0.20, 0.20),
    Point(0.80, 0.80),
    Point(0.50, 0.20),
    Point(0.20, 0.80),
    Point(0.80, 0.20),
    Point(0.20, 0.50),
    Point(0.80, 0.50),
    Point(0.50, 0.80),
    Point(0.56, 0.44),
)


class CalibrationCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CaptureStats:
    processed_frames: int
    face_frames: int


def _draw_target(
    canvas: Any,
    target: Point,
    current: int,
    total: int,
    phase: str,
    confidence: float,
    target_samples: int,
    minimum_confidence: float,
    attempt: int,
) -> None:
    import cv2

    height, width = canvas.shape[:2]
    location = (int(target.x * width), int(target.y * height))
    cv2.circle(canvas, location, 25, (80, 80, 80), 3)
    cv2.circle(canvas, location, 8, (255, 255, 255), -1)
    cv2.putText(
        canvas,
        f"{phase}: look at the dot with your eyes; keep your head still   {current}/{total}",
        (max(30, width // 2 - 470), 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.76,
        (220, 220, 220),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        "Press Esc to cancel",
        (30, height - 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (150, 150, 150),
        1,
        cv2.LINE_AA,
    )
    usable = confidence >= minimum_confidence
    status = f"EYE FEATURES {'READY' if usable else 'LOW CONFIDENCE'}  {confidence:.2f}"
    color = (80, 235, 100) if usable else (80, 110, 255)
    cv2.putText(
        canvas,
        status,
        (30, height - 72),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.68,
        color,
        2,
        cv2.LINE_AA,
    )
    retry = f"   retry {attempt}" if attempt > 1 else ""
    cv2.putText(
        canvas,
        f"Usable frames: {target_samples}{retry}",
        (30, height - 102),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (180, 180, 180),
        1,
        cv2.LINE_AA,
    )


def _draw_message(canvas: Any, title: str, lines: tuple[str, ...]) -> None:
    import cv2

    height, width = canvas.shape[:2]
    cv2.putText(
        canvas,
        title,
        (max(30, width // 2 - 310), height // 2 - 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.05,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    for index, line in enumerate(lines):
        cv2.putText(
            canvas,
            line,
            (max(30, width // 2 - 360), height // 2 + index * 38),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.70,
            (190, 210, 235),
            2,
            cv2.LINE_AA,
        )


def _warm_up_tracking(
    camera: OpenCVCamera,
    tracker: MediaPipeTracker,
    screen_size: tuple[int, int],
    window: str,
    minimum_confidence: float,
    seconds: float = 2.5,
) -> CaptureStats:
    """Let camera auto-controls and temporal landmark tracking settle before capture."""
    import cv2

    width, height = screen_size
    began = monotonic()
    processed_frames = 0
    face_frames = 0
    usable_frames = 0
    while monotonic() - began < seconds:
        frame = camera.read()
        result = tracker.process(frame, camera.latest_frame_at)
        processed_frames += 1
        face_frames += int(result.face_landmarks is not None)
        confidence = result.gaze_confidence if result.gaze_features is not None else 0.0
        usable_frames += int(confidence >= minimum_confidence)

        canvas = np.zeros((height, width, 3), dtype=np.uint8)
        progress = min((monotonic() - began) / seconds, 1.0)
        _draw_message(
            canvas,
            "Stabilizing camera and eye tracking...",
            (
                "Sit comfortably and look at the center dot.",
                f"Eye features: {'READY' if confidence >= minimum_confidence else 'WAITING'}  "
                f"{confidence:.2f}",
            ),
        )
        center = (width // 2, height // 2 + 80)
        cv2.circle(canvas, center, 10, (255, 255, 255), -1)
        cv2.rectangle(
            canvas,
            (width // 2 - 180, height // 2 + 130),
            (width // 2 - 180 + round(360 * progress), height // 2 + 142),
            (80, 220, 110),
            -1,
        )
        if not window_is_open(cv2, window):
            raise CalibrationCancelled("Calibration window closed")
        cv2.imshow(window, canvas)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            raise CalibrationCancelled("Calibration cancelled")

    minimum_usable = max(round(processed_frames * 0.50), 1)
    if usable_frames < minimum_usable:
        raise RuntimeError(
            "Eye tracking was not consistently ready during camera warm-up. "
            "Move closer, use even frontal lighting, and run `chudvis test`."
        )
    return CaptureStats(processed_frames, face_frames)


def _capture_targets(
    camera: OpenCVCamera,
    tracker: MediaPipeTracker,
    screen_size: tuple[int, int],
    window: str,
    targets: tuple[Point, ...],
    phase: str,
    settle_seconds: float,
    sample_seconds: float,
    maximum_samples: int,
    minimum_samples: int,
    minimum_confidence: float,
    maximum_attempts: int = 2,
) -> tuple[list[TargetSamples], CaptureStats]:
    import cv2

    width, height = screen_size
    groups: list[TargetSamples] = []
    processed_frames = 0
    face_frames = 0

    for index, target in enumerate(targets, start=1):
        selected: tuple[GazeFeatures, ...] = ()
        raw_samples: list[GazeFeatures] = []
        for attempt in range(1, maximum_attempts + 1):
            raw_samples = []
            began = monotonic()
            confidence = 0.0
            while monotonic() - began < settle_seconds + sample_seconds:
                frame = camera.read()
                result = tracker.process(frame, camera.latest_frame_at)
                processed_frames += 1
                face_frames += int(result.face_landmarks is not None)
                confidence = result.gaze_confidence if result.gaze_features is not None else 0.0
                elapsed = monotonic() - began
                if (
                    elapsed >= settle_seconds
                    and result.gaze_features is not None
                    and confidence >= minimum_confidence
                ):
                    raw_samples.append(result.gaze_features)

                canvas = np.zeros((height, width, 3), dtype=np.uint8)
                _draw_target(
                    canvas,
                    target,
                    index,
                    len(targets),
                    phase,
                    confidence,
                    len(raw_samples),
                    minimum_confidence,
                    attempt,
                )
                if not window_is_open(cv2, window):
                    raise CalibrationCancelled("Calibration window closed")
                cv2.imshow(window, canvas)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    raise CalibrationCancelled("Calibration cancelled")
                if not window_is_open(cv2, window):
                    raise CalibrationCancelled("Calibration window closed")

            selected = robust_sample_subset(raw_samples, maximum_samples, minimum_samples)
            if len(selected) >= minimum_samples:
                break

        if len(selected) < minimum_samples:
            if face_frames == 0:
                reason = "No face landmarks were detected."
            else:
                reason = "Eye features were missing or below the confidence threshold."
            raise RuntimeError(
                f"Could not capture target {index}/{len(targets)} after {maximum_attempts} "
                f"attempts ({len(raw_samples)} usable frames; {minimum_samples} required). "
                f"{reason} Move closer, improve front lighting, and run `chudvis test`."
            )
        groups.append(TargetSamples(target, selected))

    return groups, CaptureStats(processed_frames, face_frames)


def _show_training_message(window: str, screen_size: tuple[int, int]) -> None:
    import cv2

    width, height = screen_size
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    _draw_message(
        canvas,
        "Training and comparing gaze models...",
        ("The calibration window may pause briefly.",),
    )
    cv2.imshow(window, canvas)
    cv2.waitKey(1)


def _show_results(
    window: str,
    screen_size: tuple[int, int],
    profile: CalibrationProfile,
    seconds: float = 3.0,
) -> None:
    import cv2

    width, height = screen_size
    median = profile.validation_median_error_px or 0.0
    p95 = profile.validation_p95_error_px or 0.0
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    _draw_message(
        canvas,
        "Calibration complete",
        (
            f"Selected: {profile.model_type}",
            f"Validation error: median {median:.0f}px   p95 {p95:.0f}px",
            "Keep the webcam, monitor, and seating position unchanged.",
        ),
    )
    began = monotonic()
    while monotonic() - began < seconds and window_is_open(cv2, window):
        cv2.imshow(window, canvas)
        if cv2.waitKey(20) & 0xFF == 27:
            break


def run_calibration(
    camera: OpenCVCamera,
    tracker: MediaPipeTracker,
    screen_size: tuple[int, int],
    camera_index: int,
    ridge_alpha: float,
    grid_size: int = 5,
    minimum_confidence: float = 0.55,
    settle_seconds: float = 0.55,
    sample_seconds: float = 0.90,
) -> CalibrationProfile:
    import cv2

    window = "Chudvis calibration"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    try:
        warmup_stats = _warm_up_tracking(
            camera,
            tracker,
            screen_size,
            window,
            minimum_confidence,
        )
        training_groups, training_stats = _capture_targets(
            camera,
            tracker,
            screen_size,
            window,
            drift_resistant_target_order(dense_grid_targets(grid_size)),
            "DENSE CALIBRATION",
            settle_seconds,
            sample_seconds,
            maximum_samples=12,
            minimum_samples=8,
            minimum_confidence=minimum_confidence,
        )
        validation_groups, validation_stats = _capture_targets(
            camera,
            tracker,
            screen_size,
            window,
            VALIDATION_TARGETS,
            "VALIDATION",
            settle_seconds=0.45,
            sample_seconds=0.70,
            maximum_samples=8,
            minimum_samples=5,
            minimum_confidence=minimum_confidence,
        )
        _show_training_message(window, screen_size)
        profile = select_best_profile(
            training_groups,
            validation_groups,
            screen_size,
            camera_index,
            ridge_alpha,
        )
        _show_results(window, screen_size, profile)
    finally:
        close_window(cv2, window)

    total_frames = (
        warmup_stats.processed_frames
        + training_stats.processed_frames
        + validation_stats.processed_frames
    )
    total_face_frames = (
        warmup_stats.face_frames + training_stats.face_frames + validation_stats.face_frames
    )
    if total_frames and total_face_frames / total_frames < 0.80:
        print(
            "Warning: face tracking was intermittent during calibration; better lighting or "
            "a closer camera position may improve accuracy."
        )
    return profile
