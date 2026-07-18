from __future__ import annotations

from time import monotonic
from typing import Any

import numpy as np

from gazemotion.capture.camera import OpenCVCamera
from gazemotion.core.events import GazeFeatures, Point
from gazemotion.gaze.model import CalibrationProfile
from gazemotion.perception.mediapipe_tracker import MediaPipeTracker
from gazemotion.ui.window import close_window, window_is_open

CALIBRATION_TARGETS = (
    Point(0.10, 0.10),
    Point(0.50, 0.10),
    Point(0.90, 0.10),
    Point(0.10, 0.50),
    Point(0.50, 0.50),
    Point(0.90, 0.50),
    Point(0.10, 0.90),
    Point(0.50, 0.90),
    Point(0.90, 0.90),
)


class CalibrationCancelled(RuntimeError):
    pass


def _draw_target(
    canvas: Any,
    target: Point,
    current: int,
    total: int,
    face_detected: bool,
    target_samples: int,
    total_samples: int,
) -> None:
    import cv2

    height, width = canvas.shape[:2]
    location = (int(target.x * width), int(target.y * height))
    cv2.circle(canvas, location, 24, (80, 80, 80), 3)
    cv2.circle(canvas, location, 8, (255, 255, 255), -1)
    cv2.putText(
        canvas,
        f"Look at the dot and keep your head comfortable   {current}/{total}",
        (max(30, width // 2 - 360), 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
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
    status = "FACE + IRIS DETECTED" if face_detected else "NO FACE/IRIS DETECTION"
    color = (80, 235, 100) if face_detected else (80, 110, 255)
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
    cv2.putText(
        canvas,
        f"Samples: this target {target_samples}   total {total_samples}",
        (30, height - 102),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (180, 180, 180),
        1,
        cv2.LINE_AA,
    )


def run_calibration(
    camera: OpenCVCamera,
    tracker: MediaPipeTracker,
    screen_size: tuple[int, int],
    camera_index: int,
    ridge_alpha: float,
    settle_seconds: float = 0.65,
    sample_seconds: float = 0.90,
) -> CalibrationProfile:
    import cv2

    width, height = screen_size
    window = "GazeMotion calibration"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    samples: list[tuple[GazeFeatures, Point]] = []
    sample_counts: list[int] = []
    face_frames = 0
    processed_frames = 0

    try:
        for index, target in enumerate(CALIBRATION_TARGETS, start=1):
            began = monotonic()
            face_detected = False
            target_samples = 0
            while monotonic() - began < settle_seconds + sample_seconds:
                canvas = np.zeros((height, width, 3), dtype=np.uint8)
                _draw_target(
                    canvas,
                    target,
                    index,
                    len(CALIBRATION_TARGETS),
                    face_detected,
                    target_samples,
                    len(samples),
                )
                if not window_is_open(cv2, window):
                    raise CalibrationCancelled("Calibration window closed")
                cv2.imshow(window, canvas)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    raise CalibrationCancelled("Calibration cancelled")
                if not window_is_open(cv2, window):
                    raise CalibrationCancelled("Calibration window closed")

                frame = camera.read()
                result = tracker.process(frame)
                processed_frames += 1
                face_detected = result.face_landmarks is not None
                face_frames += int(face_detected)
                elapsed = monotonic() - began
                if elapsed >= settle_seconds and result.gaze_features is not None:
                    samples.append((result.gaze_features, target))
                    target_samples += 1
            sample_counts.append(target_samples)
    finally:
        close_window(cv2, window)

    if len(samples) < 30:
        counts = ", ".join(str(count) for count in sample_counts)
        if face_frames == 0:
            reason = "No face landmarks were detected in any camera frame."
        else:
            reason = "A face was detected, but too few frames contained usable iris landmarks."
        raise RuntimeError(
            f"Not enough face/iris samples were captured ({len(samples)}/30 required). "
            f"{reason} Processed {processed_frames} frames; per-target samples: [{counts}]. "
            "Run `gazemotion test` to inspect the camera, landmarks, and thresholds."
        )
    return CalibrationProfile.fit(samples, screen_size, camera_index, ridge_alpha)
