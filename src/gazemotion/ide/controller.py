from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from enum import Enum

from gazemotion.actions.base import InputAdapter
from gazemotion.core.config import GestureSettings, IdeSettings
from gazemotion.core.controller import DictationService
from gazemotion.core.events import (
    GazeSample,
    GestureType,
    HandRole,
    Point,
    RoleGestureEvent,
)
from gazemotion.ide.adapter import IdeAdapter


class IdeControllerState(str, Enum):
    TRACKING = "tracking"
    DICTATING = "dictating"
    TRANSCRIBING = "transcribing"
    REQUEST_PENDING = "request_pending"
    AGENT_WORKING = "agent_working"
    PAUSED = "paused"


class IdeInteractionController:
    """Translate role-tagged gestures into safe IDE and voice request actions."""

    def __init__(
        self,
        input_adapter: InputAdapter,
        ide_adapter: IdeAdapter,
        screen_size: tuple[int, int],
        gesture_settings: GestureSettings,
        ide_settings: IdeSettings,
        minimum_gaze_confidence: float = 0.55,
        max_gaze_age_seconds: float = 0.30,
        dictation: DictationService | None = None,
        status: Callable[[str], None] = print,
    ) -> None:
        self.input = input_adapter
        self.ide = ide_adapter
        self.screen_size = screen_size
        self.gestures = gesture_settings
        self.settings = ide_settings
        self.minimum_gaze_confidence = minimum_gaze_confidence
        self.max_gaze_age_seconds = max_gaze_age_seconds
        self.dictation = dictation
        self.status = status
        self.state = IdeControllerState.TRACKING
        self.latest_gaze: GazeSample | None = None
        self.locked_gaze: GazeSample | None = None
        self._transcription: Future[str] | None = None
        self._last_navigation_at = -1e9

    def _pixels(self, point: Point) -> Point:
        return Point(point.x * self.screen_size[0], point.y * self.screen_size[1])

    def on_gaze(self, sample: GazeSample) -> None:
        if sample.confidence < self.minimum_gaze_confidence:
            return
        self.latest_gaze = sample
        if self.state in (
            IdeControllerState.TRACKING,
            IdeControllerState.AGENT_WORKING,
        ) and self.locked_gaze is None:
            self.input.move_pointer(self._pixels(sample.point))

    def _toggle_pause(self) -> None:
        if self.state == IdeControllerState.REQUEST_PENDING:
            self.ide.cancel_request()
            self.state = IdeControllerState.TRACKING
            self.status("Edit request cancelled")
            return
        if self.state == IdeControllerState.PAUSED:
            self.state = IdeControllerState.TRACKING
            self.ide.set_paused(False)
            self.status("IDE control resumed")
            return
        if self.state == IdeControllerState.DICTATING and self.dictation is not None:
            self.dictation.cancel()
        self._transcription = None
        self.locked_gaze = None
        self.ide.cancel_selection()
        self.ide.set_paused(True)
        self.state = IdeControllerState.PAUSED
        self.status("IDE control paused")

    def _handle_dictation(self) -> None:
        if self.state == IdeControllerState.REQUEST_PENDING:
            self.ide.submit_request()
            self.state = IdeControllerState.AGENT_WORKING
            self.status("Edit request sent to the coding agent")
            return
        if self.dictation is None:
            self.status("Voice dictation is disabled or unavailable")
            return
        if self.state in (IdeControllerState.TRACKING, IdeControllerState.AGENT_WORKING):
            try:
                self.dictation.start()
            except Exception as exc:
                self.status(f"Could not start dictation: {exc}")
                return
            self.state = IdeControllerState.DICTATING
            self.status("Listening for an edit request")
            return
        if self.state == IdeControllerState.DICTATING:
            try:
                self._transcription = self.dictation.finish()
            except Exception as exc:
                self.status(f"Could not finish dictation: {exc}")
                self.state = IdeControllerState.TRACKING
                return
            self.state = IdeControllerState.TRANSCRIBING
            self.status("Transcribing edit request locally")

    def _on_editor_gesture(self, event: RoleGestureEvent) -> None:
        gesture = event.gesture
        if gesture.type == GestureType.DICTATION_TOGGLE:
            self._handle_dictation()
            return
        if self.state not in (IdeControllerState.TRACKING, IdeControllerState.AGENT_WORKING):
            return
        if gesture.type == GestureType.PINCH_START:
            if (
                self.latest_gaze is not None
                and gesture.timestamp - self.latest_gaze.timestamp <= self.max_gaze_age_seconds
            ):
                if self.ide.arm_selection(self.settings.selection_timeout_seconds):
                    self.locked_gaze = self.latest_gaze
                else:
                    self.status("Selection ignored: the IDE extension is disconnected")
            else:
                self.status("Selection ignored: gaze tracking is unavailable")
        elif gesture.type == GestureType.PINCH_CANCEL:
            self.locked_gaze = None
            self.ide.cancel_selection()
        elif gesture.type == GestureType.CLICK:
            if self.locked_gaze is not None:
                self.input.click(self._pixels(self.locked_gaze.point))
                self.status("Semantic selection requested")
            self.locked_gaze = None
        elif gesture.type == GestureType.DRAG_START:
            self.locked_gaze = None
            self.ide.cancel_selection()
        elif gesture.type == GestureType.SCROLL:
            lines = round(gesture.delta.y * self.gestures.scroll_scale)
            if lines:
                self.ide.scroll_editor(lines)

    def _on_navigator_gesture(self, event: RoleGestureEvent) -> None:
        gesture = event.gesture
        if self.state not in (IdeControllerState.TRACKING, IdeControllerState.AGENT_WORKING):
            return
        if gesture.type != GestureType.SCROLL:
            return
        if (
            gesture.timestamp - self._last_navigation_at
            < self.settings.navigation_cooldown_seconds
        ):
            return
        direction = -1 if gesture.delta.y < 0 else 1
        self.ide.navigate_change(direction)
        self._last_navigation_at = gesture.timestamp

    def on_gesture(self, event: RoleGestureEvent) -> None:
        if event.gesture.type == GestureType.PAUSE_TOGGLE:
            self._toggle_pause()
            return
        if self.state == IdeControllerState.PAUSED:
            return
        if event.role == HandRole.EDITOR:
            self._on_editor_gesture(event)
        else:
            self._on_navigator_gesture(event)

    def poll(self) -> None:
        self.ide.poll()
        if self.state != IdeControllerState.TRANSCRIBING or self._transcription is None:
            return
        if not self._transcription.done():
            return
        try:
            transcript = self._transcription.result().strip()
            if transcript:
                self.ide.show_request(transcript)
                self.state = IdeControllerState.REQUEST_PENDING
                self.status("Request ready; hold thumbs-up to send or an open palm to cancel")
            else:
                self.state = IdeControllerState.TRACKING
                self.status("No speech detected; edit request discarded")
        except Exception as exc:
            self.state = IdeControllerState.TRACKING
            self.status(f"Transcription failed: {exc}")
        finally:
            self._transcription = None

    def shutdown(self) -> None:
        if self.state == IdeControllerState.DICTATING and self.dictation is not None:
            self.dictation.cancel()
        if self.state == IdeControllerState.REQUEST_PENDING:
            self.ide.cancel_request()
        self.ide.cancel_selection()
        self.ide.set_paused(True)
        self.state = IdeControllerState.PAUSED
