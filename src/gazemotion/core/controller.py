from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Protocol

from gazemotion.actions.base import InputAdapter
from gazemotion.agent.agent import AgentResult, VoiceCommandAgent
from gazemotion.core.config import GestureSettings
from gazemotion.core.events import (
    ControllerState,
    GazeSample,
    GestureEvent,
    GestureType,
    Point,
)


class DictationService(Protocol):
    def start(self) -> None: ...

    def finish(self) -> Future[str]: ...

    def cancel(self) -> None: ...


class InteractionController:
    def __init__(
        self,
        input_adapter: InputAdapter,
        screen_size: tuple[int, int],
        gesture_settings: GestureSettings,
        minimum_gaze_confidence: float = 0.55,
        max_gaze_age_seconds: float = 0.30,
        dictation: DictationService | None = None,
        status: Callable[[str], None] = print,
        agent: VoiceCommandAgent | None = None,
        announce: Callable[[str], None] | None = None,
    ) -> None:
        self.input = input_adapter
        self.screen_size = screen_size
        self.gestures = gesture_settings
        self.minimum_gaze_confidence = minimum_gaze_confidence
        self.max_gaze_age_seconds = max_gaze_age_seconds
        self.dictation = dictation
        self.status = status
        self.agent = agent
        self.announce = announce or (lambda _text: None)
        self.state = ControllerState.TRACKING
        self.latest_gaze: GazeSample | None = None
        self.locked_gaze: GazeSample | None = None
        self._transcription: Future[str] | None = None
        self._agent_future: Future[AgentResult] | None = None
        self._agent_executor: ThreadPoolExecutor | None = None
        if agent is not None:
            self._agent_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent")

    def _pixels(self, point: Point) -> Point:
        return Point(point.x * self.screen_size[0], point.y * self.screen_size[1])

    def on_gaze(self, sample: GazeSample) -> None:
        if sample.confidence < self.minimum_gaze_confidence:
            return
        self.latest_gaze = sample
        if self.state == ControllerState.TRACKING and self.locked_gaze is None:
            self.input.move_pointer(self._pixels(sample.point))

    def _toggle_pause(self) -> None:
        if self.state == ControllerState.PAUSED:
            self.state = ControllerState.TRACKING
            self.status("Tracking resumed")
            self.announce("Tracking resumed")
            return
        if self.state == ControllerState.DRAGGING:
            self.input.mouse_up()
        if self.state == ControllerState.DICTATING and self.dictation:
            self.dictation.cancel()
        self.locked_gaze = None
        self.state = ControllerState.PAUSED
        self.status("Paused: actions are disabled")
        self.announce("Paused")

    def request_pause(self) -> None:
        """Pause from outside the gesture loop (voice command or wellness alert)."""
        if self.state != ControllerState.PAUSED:
            self._toggle_pause()

    def _toggle_dictation(self) -> None:
        if self.dictation is None:
            self.status("Voice dictation is disabled or unavailable")
            return
        if self.state == ControllerState.TRACKING:
            try:
                self.dictation.start()
            except Exception as exc:
                self.status(f"Could not start dictation: {exc}")
                return
            self.state = ControllerState.DICTATING
            self.status("Dictation listening; hold thumbs-up again to type and press Enter")
        elif self.state == ControllerState.DICTATING:
            try:
                self._transcription = self.dictation.finish()
            except Exception as exc:
                self.status(f"Could not finish dictation: {exc}")
                self.state = ControllerState.TRACKING
                return
            self.state = ControllerState.TRANSCRIBING
            self.status("Transcribing locally...")

    def on_gesture(self, event: GestureEvent) -> None:
        if event.type == GestureType.PAUSE_TOGGLE:
            self._toggle_pause()
            return
        if self.state == ControllerState.PAUSED:
            return
        if event.type == GestureType.DICTATION_TOGGLE:
            self._toggle_dictation()
            return
        if self.state in (
            ControllerState.DICTATING,
            ControllerState.TRANSCRIBING,
            ControllerState.COMMANDING,
        ):
            return

        if event.type == GestureType.PINCH_START:
            if (
                self.latest_gaze is not None
                and event.timestamp - self.latest_gaze.timestamp <= self.max_gaze_age_seconds
            ):
                self.locked_gaze = self.latest_gaze
            else:
                self.status("Click ignored: gaze tracking is unavailable")
        elif event.type == GestureType.PINCH_CANCEL:
            self.locked_gaze = None
        elif event.type == GestureType.CLICK:
            if self.locked_gaze is not None:
                self.input.click(self._pixels(self.locked_gaze.point))
                self.status("Click")
            self.locked_gaze = None
        elif event.type == GestureType.DRAG_START:
            if self.locked_gaze is not None:
                self.input.mouse_down(self._pixels(self.locked_gaze.point))
                self.state = ControllerState.DRAGGING
                self.status("Drag started")
        elif event.type == GestureType.DRAG_MOVE and self.state == ControllerState.DRAGGING:
            self.input.move_relative(
                Point(
                    event.delta.x * self.screen_size[0] * self.gestures.drag_scale,
                    event.delta.y * self.screen_size[1] * self.gestures.drag_scale,
                )
            )
        elif event.type == GestureType.DRAG_END:
            if self.state == ControllerState.DRAGGING:
                self.input.mouse_up()
                self.status("Drag ended")
            self.state = ControllerState.TRACKING
            self.locked_gaze = None
        elif event.type == GestureType.SCROLL and self.state == ControllerState.TRACKING:
            amount = round(-event.delta.y * self.gestures.scroll_scale)
            self.input.scroll(amount)

    def _finish_transcription(self) -> None:
        if self._transcription is None or not self._transcription.done():
            return
        transcription = self._transcription
        self._transcription = None
        try:
            text = transcription.result()
        except Exception as exc:
            self.status(f"Transcription failed: {exc}")
            self.state = ControllerState.TRACKING
            return
        if self.agent is not None and self._agent_executor is not None:
            self.status(f'Heard: "{text}"' if text else "No speech detected")
            self._agent_future = self._agent_executor.submit(self.agent.handle, text)
            self.state = ControllerState.COMMANDING
            return
        if text:
            self.input.type_text(text)
            self.input.press_enter()
            self.status(f"Dictation submitted: {text}")
        else:
            self.status("No speech detected; nothing was typed")
        self.state = ControllerState.TRACKING

    def _finish_agent(self) -> None:
        if self._agent_future is None or not self._agent_future.done():
            return
        agent_future = self._agent_future
        self._agent_future = None
        try:
            result = agent_future.result()
        except Exception as exc:
            self.status(f"Voice command failed: {exc}")
            result = None
        if self.state == ControllerState.COMMANDING:
            self.state = ControllerState.TRACKING
        if result is None:
            return
        if result.spoken:
            self.status(result.spoken)
            self.announce(result.spoken)
        if result.pause_requested:
            self.request_pause()

    def poll(self) -> None:
        if self.state == ControllerState.TRANSCRIBING:
            self._finish_transcription()
        elif self.state == ControllerState.COMMANDING:
            self._finish_agent()

    def shutdown(self) -> None:
        if self.state == ControllerState.DRAGGING:
            self.input.mouse_up()
        if self.state == ControllerState.DICTATING and self.dictation:
            self.dictation.cancel()
        if self._agent_executor is not None:
            self._agent_executor.shutdown(wait=False, cancel_futures=True)
        self.state = ControllerState.PAUSED
