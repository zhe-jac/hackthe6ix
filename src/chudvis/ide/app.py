from __future__ import annotations

from time import monotonic
from typing import Any

from chudvis.actions.base import InputAdapter
from chudvis.capture.camera import OpenCVCamera
from chudvis.core.config import AppConfig
from chudvis.core.controller import DictationService
from chudvis.gaze.model import AdaptiveGazeSmoother, CalibrationProfile, GazeEstimator
from chudvis.gestures.router import HandGestureRouter
from chudvis.ide.adapter import IdeAdapter
from chudvis.ide.controller import IdeInteractionController
from chudvis.perception.mediapipe_tracker import MediaPipeTracker, PerceptionResult
from chudvis.speech.realtime_voice import VoiceSessionService
from chudvis.ui.window import close_window, window_is_open


class ChudvisIdeApplication:
    """Run gaze, two-hand gesture, voice, and IDE intent processing together."""

    WINDOW_NAME = "Chudvis IDE preview"

    def __init__(
        self,
        config: AppConfig,
        profile: CalibrationProfile,
        input_adapter: InputAdapter,
        ide_adapter: IdeAdapter,
        screen_size: tuple[int, int],
        dictation: DictationService | None = None,
        voice_session: VoiceSessionService | None = None,
        preview: bool = False,
    ) -> None:
        self.config = config
        self.profile = profile
        self.input_adapter = input_adapter
        self.ide_adapter = ide_adapter
        self.screen_size = screen_size
        self.dictation = dictation
        self.voice_session = voice_session
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
            median_window=self.config.gaze.smoothing_median_window,
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
            self.voice_session,
        )

        self._running = True
        voice_started = False
        voice_bridge_connected = False
        runtime_ready_sent = False
        last_frame_at = monotonic()
        fps = 0.0
        if self.preview:
            cv2.namedWindow(self.WINDOW_NAME, cv2.WINDOW_NORMAL)
        try:
            print("Chudvis IDE mode is running. Press Ctrl+C for an emergency stop.")
            with (
                camera,
                MediaPipeTracker(max_hands=2, settings=self.config.tracking) as tracker,
            ):
                while self._running:
                    bridge_connected = self.ide_adapter.connected
                    if runtime_ready_sent and not bridge_connected:
                        runtime_ready_sent = False
                    if self.voice_session is not None and bridge_connected and not voice_started:
                        try:
                            self.voice_session.start()
                            voice_started = True
                            voice_bridge_connected = True
                        except Exception as exc:
                            self.voice_session.close()
                            self.voice_session = None
                            controller.voice_session = None
                            fallback = (
                                "Using the local Whisper fallback."
                                if self.dictation is not None
                                else "Voice requests are disabled."
                            )
                            print(
                                f"Wake streaming stopped during microphone setup: {exc}. "
                                f"{fallback}"
                            )
                    elif self.voice_session is not None and voice_started:
                        if bridge_connected and not voice_bridge_connected:
                            self.voice_session.set_paused(False)
                        elif not bridge_connected and voice_bridge_connected:
                            self.voice_session.set_paused(True)
                        voice_bridge_connected = bridge_connected
                    frame = camera.read()
                    now = camera.latest_frame_at
                    result = tracker.process(frame, now)

                    if result.gaze_features is not None:
                        sample = gaze.estimate(result.gaze_features, result.gaze_confidence, now)
                        controller.on_gaze(sample)

                    for event in gestures.update(result.hands, now):
                        controller.on_gesture(event)
                    controller.poll()

                    if bridge_connected and not runtime_ready_sent:
                        if voice_started:
                            detail = "Camera, microphone, and backend are ready"
                        elif self.dictation is not None:
                            detail = (
                                "Camera and backend are ready; "
                                "local voice fallback is available"
                            )
                        else:
                            detail = "Camera and backend are ready; voice controls are disabled"
                        self.ide_adapter.runtime_ready(detail)
                        runtime_ready_sent = True

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
            if self.voice_session is not None:
                self.voice_session.close()
            if self.preview:
                close_window(cv2, self.WINDOW_NAME)
            self._running = False

    def stop(self) -> None:
        self._running = False
