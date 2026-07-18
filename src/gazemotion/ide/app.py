from __future__ import annotations

from time import monotonic
from typing import Any

from gazemotion.actions.base import InputAdapter
from gazemotion.capture.camera import OpenCVCamera
from gazemotion.core.config import AppConfig
from gazemotion.core.controller import DictationService
from gazemotion.gaze.model import AdaptiveGazeSmoother, CalibrationProfile, GazeEstimator
from gazemotion.gestures.router import HandGestureRouter
from gazemotion.ide.adapter import IdeAdapter
from gazemotion.ide.controller import IdeInteractionController
from gazemotion.perception.mediapipe_tracker import MediaPipeTracker, PerceptionResult
from gazemotion.ui.window import close_window, window_is_open


class GazeMotionIdeApplication:
    """Run gaze, two-hand gesture, voice, and IDE intent processing together."""

    WINDOW_NAME = "GazeMotion IDE preview"

    def __init__(
        self,
        config: AppConfig,
        profile: CalibrationProfile,
        input_adapter: InputAdapter,
        ide_adapter: IdeAdapter,
        screen_size: tuple[int, int],
        dictation: DictationService | None = None,
        preview: bool = False,
    ) -> None:
        self.config = config
        self.profile = profile
        self.input_adapter = input_adapter
        self.ide_adapter = ide_adapter
        self.screen_size = screen_size
        self.dictation = dictation
        self.preview = preview
        self._running = False

    @classmethod
    def _draw_preview(
        cls,
        frame: Any,
        tracker: MediaPipeTracker,
        result: PerceptionResult,
        controller: IdeInteractionController,
        fps: float,
    ) -> None:
        import cv2

        tracker.draw_debug(frame, result)
        cv2.putText(
            frame,
            f"IDE: {controller.state.value}   hands: {len(result.hands)}   fps: {fps:.1f}",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (80, 220, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            f"{controller.settings.navigator_hand.title()}: review   "
            f"{controller.settings.editor_hand.title()}: editor   Esc: emergency stop",
            (20, 68),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            (230, 230, 230),
            2,
            cv2.LINE_AA,
        )
        cv2.imshow(cls.WINDOW_NAME, frame)

    def run(self) -> None:
        import cv2

        camera = OpenCVCamera(
            index=self.config.camera_index,
            width=self.config.camera_width,
            height=self.config.camera_height,
            fps=self.config.camera_fps,
            fourcc=self.config.camera_fourcc,
            mirror=self.config.mirror_camera,
        )
        smoother = AdaptiveGazeSmoother(
            min_cutoff=self.config.gaze.smoothing_min_cutoff,
            beta=self.config.gaze.smoothing_beta,
            derivative_cutoff=self.config.gaze.smoothing_derivative_cutoff,
            deadzone=self.config.gaze.smoothing_deadzone,
            stable_speed_threshold=self.config.gaze.stable_speed_threshold,
        )
        gaze = GazeEstimator(self.profile, smoother)
        gestures = HandGestureRouter(self.config.gestures, self.config.ide)
        controller = IdeInteractionController(
            self.input_adapter,
            self.ide_adapter,
            self.screen_size,
            self.config.gestures,
            self.config.ide,
            self.config.gaze.minimum_confidence,
            self.config.gaze.max_sample_age_seconds,
            self.dictation,
        )

        self._running = True
        last_frame_at = monotonic()
        fps = 0.0
        if self.preview:
            cv2.namedWindow(self.WINDOW_NAME, cv2.WINDOW_NORMAL)
        print("GazeMotion IDE mode is running. Press Ctrl+C for an emergency stop.")
        try:
            with (
                camera,
                MediaPipeTracker(max_hands=2, settings=self.config.tracking) as tracker,
            ):
                while self._running:
                    now = monotonic()
                    frame = camera.read()
                    result = tracker.process(frame, now)

                    if result.gaze_features is not None:
                        sample = gaze.estimate(result.gaze_features, result.gaze_confidence, now)
                        controller.on_gaze(sample)

                    for event in gestures.update(result.hands, now):
                        controller.on_gesture(event)
                    controller.poll()

                    elapsed = max(now - last_frame_at, 1e-6)
                    instant_fps = 1.0 / elapsed
                    fps = instant_fps if fps == 0.0 else fps * 0.9 + instant_fps * 0.1
                    last_frame_at = now

                    if self.preview:
                        if not window_is_open(cv2, self.WINDOW_NAME):
                            break
                        self._draw_preview(frame, tracker, result, controller, fps)
                        key = cv2.waitKey(1) & 0xFF
                        if key == 27 or not window_is_open(cv2, self.WINDOW_NAME):
                            break
        finally:
            controller.shutdown()
            if self.dictation is not None and hasattr(self.dictation, "close"):
                self.dictation.close()
            if self.preview:
                close_window(cv2, self.WINDOW_NAME)
            self._running = False

    def stop(self) -> None:
        self._running = False
