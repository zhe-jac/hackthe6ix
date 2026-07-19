from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Any

import numpy as np

from chudvis.capture.camera import OpenCVCamera
from chudvis.core.config import AppConfig
from chudvis.core.events import GazeSample, GestureEvent, GestureType
from chudvis.core.platform import get_screen_size
from chudvis.gaze.model import (
    AdaptiveGazeSmoother,
    CalibrationProfile,
    GazeConfidenceGate,
    GazeEstimator,
)
from chudvis.gestures.engine import GestureEngine, GestureMetrics
from chudvis.perception.mediapipe_tracker import MediaPipeTracker, PerceptionResult
from chudvis.ui.window import close_window, window_is_open


@dataclass(frozen=True, slots=True)
class DiagnosticNotice:
    label: str
    detail: str
    timestamp: float


_PRACTICE_CARDS = (
    ("click", "1. CLICK", "Quick thumb+index pinch,", "release right away"),
    ("drag", "2. DRAG", "Pinch and HOLD ~0.6s,", "move hand, then release"),
    ("scroll", "3. SCROLL", "Open palm facing camera,", "sweep hand up or down"),
    ("pause", "4. PAUSE", "Open palm held STILL", "for ~1.3 seconds"),
    ("dictate", "5. DICTATE", "Thumbs-up pose,", "hold for ~0.7s"),
)

_EVENT_TO_CARD = {
    GestureType.CLICK: "click",
    GestureType.DRAG_END: "drag",
    GestureType.SCROLL: "scroll",
    GestureType.PAUSE_TOGGLE: "pause",
    GestureType.DICTATION_TOGGLE: "dictate",
}


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
        self.gaze_gate = GazeConfidenceGate(
            config.gaze.minimum_confidence,
            config.gaze.max_sample_age_seconds,
        )
        if profile is not None:
            smoother = AdaptiveGazeSmoother(
                median_window=config.gaze.smoothing_median_window,
                min_cutoff=config.gaze.smoothing_min_cutoff,
                beta=config.gaze.smoothing_beta,
                derivative_cutoff=config.gaze.smoothing_derivative_cutoff,
                deadzone=config.gaze.smoothing_deadzone,
                stable_speed_threshold=config.gaze.stable_speed_threshold,
            )
            self.gaze = GazeEstimator(profile, smoother)
        self.last_gaze: GazeSample | None = None
        self.last_effective_gaze_confidence = 0.0
        self.last_metrics: GestureMetrics | None = None
        self.notices: deque[DiagnosticNotice] = deque(maxlen=7)
        self.frames = 0
        self.face_frames = 0
        self.hand_frames = 0
        self.gaze_frames = 0
        self.dropped_camera_frames = 0
        self.completed_at: dict[str, float | None] = {key: None for key, *_ in _PRACTICE_CARDS}
        self.full_gaze_overlay = True
        self._screen_size: tuple[int, int] | None = None
        self._window_rect: tuple[int, int, int, int] | None = None
        self._last_timestamp = 0.0

    def set_gaze_overlay_geometry(
        self,
        screen_size: tuple[int, int] | None,
        window_rect: tuple[int, int, int, int] | None,
    ) -> None:
        self._screen_size = screen_size
        self._window_rect = window_rect

    def toggle_gaze_overlay(self) -> bool:
        self.full_gaze_overlay = not self.full_gaze_overlay
        return self.full_gaze_overlay

    def _gaze_canvas_point(self) -> tuple[int, int] | None:
        if self.last_gaze is None:
            return None

        point = self.last_gaze.point
        if self._screen_size is not None and self._window_rect is not None:
            screen_width, screen_height = self._screen_size
            left, top, window_width, window_height = self._window_rect
            if window_width > 0 and window_height > 0:
                screen_x = point.x * screen_width
                screen_y = point.y * screen_height
                x = round((screen_x - left) * self.WIDTH / window_width)
                y = round((screen_y - top) * self.HEIGHT / window_height)
            else:
                x = round(point.x * self.WIDTH)
                y = round(point.y * self.HEIGHT)
        else:
            x = round(point.x * self.WIDTH)
            y = round(point.y * self.HEIGHT)

        margin = 32
        return (
            min(max(x, margin), self.WIDTH - margin),
            min(max(y, margin), self.HEIGHT - margin),
        )

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
            sample = self.gaze.estimate(
                result.gaze_features,
                result.gaze_confidence,
                timestamp,
            )
            self.last_effective_gaze_confidence = sample.confidence
            if self.gaze_gate.accepts(sample):
                self.last_gaze = sample
                self.gaze_frames += 1
        elif result.gaze_features is None:
            self.last_effective_gaze_confidence = 0.0
        if (
            self.last_gaze
            and timestamp - self.last_gaze.timestamp > self.config.gaze.max_sample_age_seconds
        ):
            self.last_gaze = None

        self._last_timestamp = timestamp
        events = self.gestures.update(result.hand, timestamp)
        for event in events:
            card = _EVENT_TO_CARD.get(event.type)
            if card is not None:
                self.completed_at[card] = timestamp
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
                "No calibrated gaze yet" if self.profile else "No profile: run chudvis calibrate"
            )
            self._put(canvas, message, (left + 18, top + 32), (120, 160, 255), 0.58, 2)
            return

        point = self.last_gaze.point
        color = (70, 255, 120) if self.last_gaze.stable else (0, 190, 255)
        if self.full_gaze_overlay:
            self._put(
                canvas,
                "Full-dashboard marker ON (G to toggle)",
                (left + 12, top + 32),
                color,
                0.52,
                2,
            )
        else:
            x = round(left + point.x * width)
            y = round(top + point.y * height)
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

    def _draw_full_gaze_overlay(self, canvas: Any) -> None:
        if not self.full_gaze_overlay:
            return
        location = self._gaze_canvas_point()
        if location is None or self.last_gaze is None:
            return

        import cv2

        x, y = location
        color = (70, 255, 120) if self.last_gaze.stable else (0, 190, 255)
        shadow = (15, 15, 15)
        cv2.circle(canvas, location, 24, shadow, 7, cv2.LINE_AA)
        cv2.circle(canvas, location, 24, color, 3, cv2.LINE_AA)
        cv2.circle(canvas, location, 5, shadow, -1, cv2.LINE_AA)
        cv2.circle(canvas, location, 3, color, -1, cv2.LINE_AA)
        cv2.line(canvas, (x - 38, y), (x + 38, y), shadow, 6, cv2.LINE_AA)
        cv2.line(canvas, (x, y - 38), (x, y + 38), shadow, 6, cv2.LINE_AA)
        cv2.line(canvas, (x - 38, y), (x + 38, y), color, 2, cv2.LINE_AA)
        cv2.line(canvas, (x, y - 38), (x, y + 38), color, 2, cv2.LINE_AA)
        label_x = min(x + 30, self.WIDTH - 125)
        label_y = max(y - 28, 28)
        self._put(canvas, "GAZE", (label_x, label_y), shadow, 0.62, 5)
        self._put(canvas, "GAZE", (label_x, label_y), color, 0.62, 2)

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
        self._put(canvas, "CHUDVIS DIAGNOSTICS", (x, y), (100, 220, 255), 0.72, 2)
        y += 42
        face_count = len(result.face_landmarks) if result.face_landmarks else 0
        face_detected = result.face_landmarks is not None
        self._put(
            canvas,
            f"Face landmarks: {'YES' if face_detected else 'NO'} ({face_count} points)",
            (x, y),
            (70, 235, 100) if face_detected else (80, 110, 255),
            0.60,
            2,
        )
        y += line
        gaze_state = (
            "BLINK - POINTER HELD"
            if result.blink_detected
            else ("READY" if result.gaze_features is not None else "UNAVAILABLE")
        )
        gaze_color = (
            (80, 190, 255)
            if result.blink_detected
            else ((70, 235, 100) if result.gaze_features is not None else (80, 110, 255))
        )
        self._put(canvas, f"Head-normalized gaze: {gaze_state}", (x, y), gaze_color, 0.54, 2)
        y += 22
        if result.eye_aspect_ratio is not None:
            self._put(
                canvas,
                f"Features: {len(result.gaze_features.values) if result.gaze_features else 486}  "
                f"eye openness={result.eye_aspect_ratio:.3f}  "
                f"landmarks={result.gaze_confidence:.2f}  "
                f"calibrated={self.last_effective_gaze_confidence:.2f}",
                (x, y),
                (175, 175, 175),
                0.48,
            )
            y += 22
        hand_label = "NO"
        hand_color = (140, 140, 140)
        if result.hands:
            labels = ", ".join(hand.handedness for hand in result.hands)
            hand_label = f"{len(result.hands)} ACTION READY ({labels})"
            hand_color = (70, 235, 100)
        elif result.hand:
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
            f"Stale camera frames discarded: {self.dropped_camera_frames}",
            (x, y),
            (175, 175, 175),
            0.49,
        )
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
            self._put(canvas, f"Model: {self.profile.model_type}", (x, y))
            y += line
            if self.profile.validation_median_error_px is not None:
                self._put(
                    canvas,
                    f"Validation: median {self.profile.validation_median_error_px:.0f}px  "
                    f"p95 {self.profile.validation_p95_error_px or 0.0:.0f}px",
                    (x, y),
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

    def _card_state(self, key: str, progress: dict[str, float]) -> tuple[str, float]:
        """Return the live status and hold progress for a practice card."""
        mode = self.gestures.current_mode
        open_palm = self.last_metrics.open_palm if self.last_metrics else False
        if key == "click" and mode == "pinch_armed":
            if self.gestures.hand_missing:
                return "tracking lost - reacquire...", 0.0
            return "ARMED - release now to click", 0.0
        if key == "drag":
            if mode == "dragging":
                if self.gestures.hand_missing:
                    return "tracking lost - holding drag...", 1.0
                return "DRAGGING - release to finish", 1.0
            if progress["drag"] > 0.0:
                return "keep holding the pinch...", progress["drag"]
        if key == "scroll" and open_palm:
            return "palm seen - sweep up/down", 0.0
        if key == "pause" and progress["pause"] > 0.0:
            return "hold still...", progress["pause"]
        if key == "dictate" and progress["thumbs_up"] > 0.0:
            return "keep holding...", progress["thumbs_up"]
        return "", 0.0

    def _draw_practice(self, canvas: Any) -> None:
        import cv2

        top, height, width, gap = 733, 138, 244, 9
        self._put(canvas, "TRY EACH GESTURE:", (14, top - 6), (170, 210, 255), 0.55, 2)
        progress = self.gestures.hold_progress(self._last_timestamp)
        for index, (key, title, line_one, line_two) in enumerate(_PRACTICE_CARDS):
            left = 12 + index * (width + gap)
            bottom = top + height
            done_at = self.completed_at[key]
            status, hold = self._card_state(key, progress)
            flash = done_at is not None and self._last_timestamp - done_at < 1.2
            if flash:
                border, accent, thickness = (120, 255, 160), (120, 255, 160), 3
            elif status:
                border, accent, thickness = (100, 235, 255), (100, 235, 255), 2
            elif done_at is not None:
                border, accent, thickness = (70, 200, 90), (70, 235, 100), 2
            else:
                border, accent, thickness = (95, 95, 95), (160, 160, 160), 1
            cv2.rectangle(canvas, (left, top), (left + width, bottom), border, thickness)
            self._put(canvas, title, (left + 12, top + 28), accent, 0.58, 2)
            if done_at is not None:
                self._put(canvas, "DONE", (left + width - 62, top + 28), (70, 235, 100), 0.55, 2)
            self._put(canvas, line_one, (left + 12, top + 56), (200, 200, 200), 0.45)
            self._put(canvas, line_two, (left + 12, top + 76), (200, 200, 200), 0.45)
            if status:
                self._put(canvas, status, (left + 12, top + 103), (100, 235, 255), 0.46, 2)
            elif done_at is None:
                self._put(
                    canvas, "waiting for you...", (left + 12, top + 103), (130, 130, 130), 0.44
                )
            if hold > 0.0:
                bar_top = bottom - 18
                cv2.rectangle(
                    canvas, (left + 12, bar_top), (left + width - 12, bottom - 10), (60, 60, 60), -1
                )
                filled = round((width - 24) * hold)
                cv2.rectangle(
                    canvas, (left + 12, bar_top), (left + 12 + filled, bottom - 10), accent, -1
                )

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
        self._draw_practice(canvas)
        self._put(
            canvas,
            "G: toggle full gaze marker   Esc or Q: close   No OS actions are executed",
            (24, 888),
            (145, 145, 145),
            0.48,
        )
        self._draw_full_gaze_overlay(canvas)
        return canvas


def run_diagnostics(
    config: AppConfig,
    profile: CalibrationProfile | None,
    camera_index: int,
    ide_mode: bool = False,
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
    window = "Chudvis diagnostics"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    screen_size: tuple[int, int] | None = None
    try:
        screen_width, screen_height = get_screen_size()
        screen_size = (screen_width, screen_height)
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

    mode = "two-hand IDE" if ide_mode else "desktop"
    print(
        f"Diagnostics are safe ({mode} mode): mouse and keyboard actions are disabled. "
        "Press Esc or Q to exit."
    )
    last_frame = monotonic()
    fps = 0.0
    try:
        with (
            camera,
            MediaPipeTracker(
                max_hands=2 if ide_mode else 1,
                settings=config.tracking,
            ) as tracker,
        ):
            while True:
                frame = camera.read()
                now = camera.latest_frame_at
                result = tracker.process(frame, now)
                dashboard.update(result, now)
                dashboard.dropped_camera_frames = camera.dropped_frames
                elapsed = max(now - last_frame, 1e-6)
                instant_fps = 1.0 / elapsed
                fps = instant_fps if fps == 0 else fps * 0.9 + instant_fps * 0.1
                last_frame = now
                canvas = dashboard.render(frame, tracker, result, fps)
                if not window_is_open(cv2, window):
                    break
                cv2.imshow(window, canvas)
                if screen_size is not None and hasattr(cv2, "getWindowImageRect"):
                    try:
                        window_rect = tuple(int(value) for value in cv2.getWindowImageRect(window))
                        if len(window_rect) == 4:
                            dashboard.set_gaze_overlay_geometry(screen_size, window_rect)
                    except Exception:
                        dashboard.set_gaze_overlay_geometry(screen_size, None)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("g"), ord("G")):
                    enabled = dashboard.toggle_gaze_overlay()
                    print(
                        "Full-dashboard gaze marker enabled" if enabled else "Mini gaze map enabled"
                    )
                if key in (27, ord("q"), ord("Q")) or not window_is_open(cv2, window):
                    break
    finally:
        close_window(cv2, window)
