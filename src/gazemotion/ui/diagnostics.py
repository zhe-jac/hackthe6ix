from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Any

import numpy as np

from gazemotion.capture.camera import OpenCVCamera
from gazemotion.core.config import AppConfig
from gazemotion.core.events import GazeSample, GestureEvent, GestureType
from gazemotion.core.platform import get_screen_size
from gazemotion.gaze.model import AdaptiveGazeSmoother, CalibrationProfile, GazeEstimator
from gazemotion.gestures.engine import GestureEngine, GestureMetrics
from gazemotion.perception.mediapipe_tracker import MediaPipeTracker, PerceptionResult
from gazemotion.ui.window import close_window, window_is_open


@dataclass(frozen=True, slots=True)
class DiagnosticNotice:
    label: str
    detail: str
    timestamp: float


def _event_detail(event: GestureEvent) -> str:
    if event.type == GestureType.PINCH_START:
        return "armed only; release may click"
    if event.type == GestureType.PINCH_CANCEL:
        return "ended without an action"
    if abs(event.delta.x) > 0.0001 or abs(event.delta.y) > 0.0001:
        return f"dx={event.delta.x:+.3f}  dy={event.delta.y:+.3f}"
    return f"confidence={event.confidence:.2f}"


class DiagnosticDashboard:
    WIDTH = 1760
    HEIGHT = 900
    CAMERA_WIDTH = 1280
    CAMERA_HEIGHT = 720

    def __init__(self, config: AppConfig, profile: CalibrationProfile | None) -> None:
        self.config = config
        self.profile = profile
        self.gestures = GestureEngine(config.gestures)
        self.gaze: GazeEstimator | None = None
        if profile is not None:
            smoother = AdaptiveGazeSmoother(
                config.gaze.smoothing_slow,
                config.gaze.smoothing_fast,
                config.gaze.fast_speed_threshold,
                config.gaze.stable_speed_threshold,
            )
            self.gaze = GazeEstimator(profile, smoother)
        self.last_gaze: GazeSample | None = None
        self.last_metrics: GestureMetrics | None = None
        self.notices: deque[DiagnosticNotice] = deque(maxlen=7)
        self.frames = 0
        self.face_frames = 0
        self.hand_frames = 0
        self.gaze_frames = 0

    def update(
        self,
        result: PerceptionResult,
        timestamp: float,
    ) -> list[GestureEvent]:
        self.frames += 1
        self.face_frames += int(result.face_landmarks is not None)
        self.hand_frames += int(result.hand is not None)
        self.last_metrics = GestureEngine.measure(result.hand)

        if self.gaze is not None and result.gaze_features is not None:
            self.last_gaze = self.gaze.estimate(
                result.gaze_features,
                result.gaze_confidence,
                timestamp,
            )
            self.gaze_frames += 1
        elif (
            self.last_gaze
            and timestamp - self.last_gaze.timestamp > self.config.gaze.max_sample_age_seconds
        ):
            self.last_gaze = None

        events = self.gestures.update(result.hand, timestamp)
        for event in events:
            if event.type == GestureType.DRAG_MOVE:
                continue
            notice = DiagnosticNotice(event.type.value.upper(), _event_detail(event), timestamp)
            self.notices.appendleft(notice)
            category = (
                "phase"
                if event.type in (GestureType.PINCH_START, GestureType.PINCH_CANCEL)
                else "action"
            )
            print(f"[{category}] {notice.label}: {notice.detail}")
        return events

    @staticmethod
    def _put(
        canvas: Any,
        text: str,
        position: tuple[int, int],
        color: tuple[int, int, int] = (225, 225, 225),
        scale: float = 0.57,
        thickness: int = 1,
    ) -> None:
        import cv2

        cv2.putText(
            canvas,
            text,
            position,
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            color,
            thickness,
            cv2.LINE_AA,
        )

    def _draw_camera(
        self, canvas: Any, frame: Any, tracker: MediaPipeTracker, result: PerceptionResult
    ) -> None:
        import cv2

        debug_frame = tracker.draw_debug(frame.copy(), result)
        source_height, source_width = debug_frame.shape[:2]
        scale = min(self.CAMERA_WIDTH / source_width, self.CAMERA_HEIGHT / source_height)
        target_width = round(source_width * scale)
        target_height = round(source_height * scale)
        resized = (
            debug_frame
            if (target_width, target_height) == (source_width, source_height)
            else cv2.resize(debug_frame, (target_width, target_height))
        )
        x = (self.CAMERA_WIDTH - target_width) // 2
        y = (self.CAMERA_HEIGHT - target_height) // 2
        canvas[y : y + target_height, x : x + target_width] = resized
        cv2.rectangle(canvas, (0, 0), (self.CAMERA_WIDTH, self.CAMERA_HEIGHT), (80, 80, 80), 1)

    def _draw_screen_map(self, canvas: Any) -> None:
        import cv2

        region_x, region_y, region_width, region_height = 1320, 700, 410, 175
        screen_width = self.profile.screen_width if self.profile else 16
        screen_height = self.profile.screen_height if self.profile else 9
        aspect = screen_width / max(screen_height, 1)
        width = region_width
        height = round(width / aspect)
        if height > region_height:
            height = region_height
            width = round(height * aspect)
        left = region_x + (region_width - width) // 2
        top = region_y + (region_height - height) // 2
        right = left + width
        bottom = top + height
        cv2.rectangle(canvas, (left, top), (right, bottom), (110, 110, 110), 2)
        self._put(
            canvas,
            "CALIBRATED GAZE POSITION",
            (region_x, 685),
            (170, 210, 255),
            0.55,
            2,
        )

        if self.last_gaze is None:
            message = (
                "No calibrated gaze yet" if self.profile else "No profile: run gazemotion calibrate"
            )
            self._put(canvas, message, (left + 18, top + 32), (120, 160, 255), 0.58, 2)
            return

        point = self.last_gaze.point
        x = round(left + point.x * width)
        y = round(top + point.y * height)
        color = (70, 255, 120) if self.last_gaze.stable else (0, 190, 255)
        cv2.circle(canvas, (x, y), 14, color, 2, cv2.LINE_AA)
        cv2.line(canvas, (x - 22, y), (x + 22, y), color, 1, cv2.LINE_AA)
        cv2.line(canvas, (x, y - 22), (x, y + 22), color, 1, cv2.LINE_AA)
        self._put(
            canvas,
            f"x={point.x * 100:5.1f}%  y={point.y * 100:5.1f}%  "
            f"stable={'YES' if self.last_gaze.stable else 'NO'}",
            (left + 12, bottom - 12),
            color,
            0.52,
            2,
        )

    def _draw_status(
        self,
        canvas: Any,
        result: PerceptionResult,
        fps: float,
        frame_shape: tuple[int, ...],
    ) -> None:
        x = 1310
        y = 35
        line = 27
        self._put(canvas, "GAZEMOTION DIAGNOSTICS", (x, y), (100, 220, 255), 0.72, 2)
        y += 42
        face_count = len(result.face_landmarks) if result.face_landmarks else 0
        self._put(
            canvas,
            f"Face/iris: {'YES' if result.gaze_features else 'NO'} ({face_count} points)",
            (x, y),
            (70, 235, 100) if result.gaze_features else (80, 110, 255),
            0.60,
            2,
        )
        y += line
        if result.gaze_features:
            right_x, right_y, left_x, left_y = result.gaze_features.values[:4]
            self._put(
                canvas,
                f"Raw iris R=({right_x:+.2f},{right_y:+.2f})",
                (x, y),
                (175, 175, 175),
                0.48,
            )
            y += 22
            self._put(
                canvas,
                f"Raw iris L=({left_x:+.2f},{left_y:+.2f})",
                (x, y),
                (175, 175, 175),
                0.48,
            )
            y += 22
        hand_label = "NO"
        hand_color = (140, 140, 140)
        if result.hand:
            hand_label = f"ACTION READY ({result.hand.handedness}, {result.hand.confidence:.2f})"
            hand_color = (70, 235, 100)
        elif result.hand_candidate:
            required = self.config.tracking.hand_confirmation_frames
            hand_label = (
                f"candidate {result.hand_confirmation_progress}/{required} "
                f"({result.hand_candidate.confidence:.2f})"
            )
            hand_color = (120, 180, 255)
        self._put(
            canvas,
            f"Hand: {hand_label}",
            (x, y),
            hand_color,
            0.60,
            2,
        )
        y += line
        self._put(canvas, f"Camera processing: {fps:.1f} FPS", (x, y))
        y += line
        self._put(
            canvas,
            f"Camera frame: {frame_shape[1]}x{frame_shape[0]}",
            (x, y),
            (175, 175, 175),
            0.49,
        )
        y += line
        self._put(
            canvas,
            f"Confirmed totals: face {self.face_frames}/{self.frames}, "
            f"hand {self.hand_frames}/{self.frames}",
            (x, y),
            (175, 175, 175),
            0.49,
        )

        y += 40
        self._put(canvas, "GESTURE INPUTS", (x, y), (170, 210, 255), 0.60, 2)
        y += line
        self._put(canvas, f"Exclusive mode: {self.gestures.current_mode}", (x, y), (100, 235, 255))
        y += line
        if self.last_metrics is None:
            self._put(canvas, "Show one hand to inspect metrics", (x, y), (150, 150, 150))
            y += line * 3
        else:
            metrics = self.last_metrics
            pinch_active = metrics.pinch_ratio <= self.config.gestures.pinch_on
            self._put(
                canvas,
                f"Pinch ratio: {metrics.pinch_ratio:.3f}  "
                f"trigger <= {self.config.gestures.pinch_on:.3f}",
                (x, y),
                (70, 235, 100) if pinch_active else (225, 225, 225),
            )
            y += line
            self._put(
                canvas,
                f"Open palm: {'YES' if metrics.open_palm else 'NO'}",
                (x, y),
                (70, 235, 100) if metrics.open_palm else (225, 225, 225),
            )
            y += line
            self._put(
                canvas,
                f"Thumbs up: {'YES' if metrics.thumbs_up else 'NO'}",
                (x, y),
                (70, 235, 100) if metrics.thumbs_up else (225, 225, 225),
            )
            y += line

        self._put(canvas, "CALIBRATION", (x, y + 10), (170, 210, 255), 0.60, 2)
        y += 40
        if self.profile:
            self._put(
                canvas, f"Profile: LOADED ({self.profile.created_at[:10]})", (x, y), (70, 235, 100)
            )
            y += line
            self._put(
                canvas,
                f"Screen: {self.profile.screen_width}x{self.profile.screen_height}",
                (x, y),
            )
            y += line
            self._put(canvas, f"Camera index: {self.profile.camera_index}", (x, y))
        else:
            self._put(canvas, "Profile: NOT FOUND", (x, y), (80, 110, 255), 0.60, 2)
            y += line
            self._put(canvas, "Face and gesture testing still works", (x, y), (170, 170, 170), 0.50)

        y = 535
        self._put(canvas, "RECENT EXCLUSIVE EVENTS", (x, y), (170, 210, 255), 0.60, 2)
        y += 28
        if not self.notices:
            self._put(canvas, "No completed gesture events yet", (x, y), (150, 150, 150), 0.52)
        for notice in list(self.notices)[:2]:
            age = max(monotonic() - notice.timestamp, 0.0)
            self._put(canvas, f"{notice.label:<18} {age:4.1f}s", (x, y), (100, 235, 255), 0.52, 2)
            y += 22
            self._put(canvas, notice.detail, (x + 14, y), (170, 170, 170), 0.45)
            y += 23

    def render(
        self,
        frame: Any,
        tracker: MediaPipeTracker,
        result: PerceptionResult,
        fps: float,
    ) -> Any:
        canvas = np.full((self.HEIGHT, self.WIDTH, 3), 18, dtype=np.uint8)
        self._draw_camera(canvas, frame, tracker, result)
        self._draw_screen_map(canvas)
        self._draw_status(canvas, result, fps, frame.shape)
        self._put(
            canvas,
            "Esc or Q: close diagnostics   No OS actions are executed",
            (24, 888),
            (145, 145, 145),
            0.48,
        )
        return canvas


def run_diagnostics(
    config: AppConfig,
    profile: CalibrationProfile | None,
    camera_index: int,
) -> None:
    import cv2

    camera = OpenCVCamera(
        index=camera_index,
        width=config.camera_width,
        height=config.camera_height,
        fps=config.camera_fps,
        fourcc=config.camera_fourcc,
        mirror=config.mirror_camera,
    )
    dashboard = DiagnosticDashboard(config, profile)
    window = "GazeMotion diagnostics"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    try:
        screen_width, screen_height = get_screen_size()
        window_scale = min(
            (screen_width - 40) / dashboard.WIDTH,
            (screen_height - 80) / dashboard.HEIGHT,
            1.0,
        )
        window_width = max(round(dashboard.WIDTH * window_scale), 640)
        window_height = max(round(dashboard.HEIGHT * window_scale), 480)
        cv2.resizeWindow(window, window_width, window_height)
        cv2.moveWindow(window, max(screen_width - window_width - 20, 0), 20)
        if hasattr(cv2, "WND_PROP_TOPMOST"):
            cv2.setWindowProperty(window, cv2.WND_PROP_TOPMOST, 1)
    except Exception:
        pass

    print("Diagnostics are safe: mouse and keyboard actions are disabled. Press Esc or Q to exit.")
    last_frame = monotonic()
    fps = 0.0
    try:
        with camera, MediaPipeTracker(max_hands=1, settings=config.tracking) as tracker:
            while True:
                now = monotonic()
                frame = camera.read()
                result = tracker.process(frame, now)
                dashboard.update(result, now)
                elapsed = max(now - last_frame, 1e-6)
                instant_fps = 1.0 / elapsed
                fps = instant_fps if fps == 0 else fps * 0.9 + instant_fps * 0.1
                last_frame = now
                canvas = dashboard.render(frame, tracker, result, fps)
                if not window_is_open(cv2, window):
                    break
                cv2.imshow(window, canvas)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q"), ord("Q")) or not window_is_open(cv2, window):
                    break
    finally:
        close_window(cv2, window)
