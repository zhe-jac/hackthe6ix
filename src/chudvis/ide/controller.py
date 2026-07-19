from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from enum import Enum
from math import trunc

from chudvis.actions.base import InputAdapter
from chudvis.core.config import GestureSettings, IdeSettings
from chudvis.core.controller import DictationService
from chudvis.core.events import (
    GazeSample,
    GestureType,
    HandRole,
    Point,
    RoleGestureEvent,
)
from chudvis.gaze.model import GazeConfidenceGate
from chudvis.ide.adapter import IdeAdapter
from chudvis.speech.realtime_voice import VoiceEventType, VoiceSessionService, VoiceState


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
        voice_session: VoiceSessionService | None = None,
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
        self.voice_session = voice_session
        self.status = status
        self.gaze_gate = GazeConfidenceGate(
            minimum_gaze_confidence,
            max_gaze_age_seconds,
        )
        self.state = IdeControllerState.TRACKING
        self.latest_gaze: GazeSample | None = None
        self.locked_gaze: GazeSample | None = None
        self._transcription: Future[str] | None = None
        self._last_navigation_at = -1e9
        self._editor_scroll_remainder = 0.0
        self._active_voice_request: str | None = None
        self._approval_pending = False

    def _diagnostic(
        self,
        category: str,
        name: str,
        data: object | None = None,
        request_id: str | None = None,
    ) -> None:
        diagnostic = getattr(self.ide, "diagnostic_event", None)
        if callable(diagnostic):
            diagnostic(category, name, data, request_id)

    def _gesture_action(
        self,
        event: RoleGestureEvent,
        action: str,
        outcome: str,
        **detail: object,
    ) -> None:
        self._diagnostic(
            "action",
            f"gesture.{outcome}",
            {
                "gesture": event.gesture.type.value,
                "role": event.role.value,
                "action": action,
                "controllerState": self.state.value,
                **detail,
            },
        )

    def _pixels(self, point: Point) -> Point:
        return Point(point.x * self.screen_size[0], point.y * self.screen_size[1])

    def on_gaze(self, sample: GazeSample) -> None:
        if not self.gaze_gate.accepts(sample):
            return
        self.latest_gaze = sample
        if (
            self.state
            in (
                IdeControllerState.TRACKING,
                IdeControllerState.AGENT_WORKING,
            )
            and self.locked_gaze is None
        ):
            self.input.move_pointer(self._pixels(sample.point))

    def _toggle_pause(self) -> None:
        if self.state == IdeControllerState.REQUEST_PENDING:
            if self._active_voice_request is not None:
                self.ide.cancel_edit(self._active_voice_request)
                if self.voice_session is not None:
                    self.voice_session.cancel(self._active_voice_request)
                self._approval_pending = False
            else:
                self.ide.cancel_request()
            self.state = IdeControllerState.TRACKING
            self.status("Request cancelled")
            return
        if self._active_voice_request is not None:
            self.ide.cancel_edit(self._active_voice_request)
            if self.voice_session is not None:
                self.voice_session.cancel(self._active_voice_request)
            self.state = IdeControllerState.TRACKING
            self.status("Voice request cancelled")
            return
        if self.state == IdeControllerState.PAUSED:
            self.state = IdeControllerState.TRACKING
            if self.voice_session is not None:
                self.voice_session.set_paused(False)
            self.ide.set_paused(False)
            self.status("IDE control resumed")
            return
        if self.state == IdeControllerState.DICTATING and self.dictation is not None:
            self.dictation.cancel()
        self._transcription = None
        self.locked_gaze = None
        self.ide.cancel_selection()
        if self.voice_session is not None:
            self.voice_session.set_paused(True)
        self.ide.set_paused(True)
        self.state = IdeControllerState.PAUSED
        self.status("IDE control paused")

    def _handle_dictation(self) -> None:
        if self.state == IdeControllerState.REQUEST_PENDING:
            if self._active_voice_request is not None and self._approval_pending:
                self.ide.approve_edit(self._active_voice_request)
                self._approval_pending = False
            else:
                self.ide.submit_request()
            self.state = IdeControllerState.AGENT_WORKING
            self.status("Request approved")
            return
        if self.voice_session is not None:
            self.status("Wake voice is active; say Chudvis before each request")
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
            self._gesture_action(event, "dictation.toggle", "executed")
            return
        if self.state not in (
            IdeControllerState.TRACKING,
            IdeControllerState.AGENT_WORKING,
            IdeControllerState.REQUEST_PENDING,
        ):
            self._gesture_action(event, "none", "ignored", reason="controller state")
            return
        if gesture.type == GestureType.PINCH_START:
            if (
                self.latest_gaze is not None
                and gesture.timestamp - self.latest_gaze.timestamp <= self.max_gaze_age_seconds
            ):
                if self.ide.arm_selection(self.settings.selection_timeout_seconds):
                    self.locked_gaze = self.latest_gaze
                    self._gesture_action(
                        event,
                        "selection.arm",
                        "executed",
                        timeoutSeconds=self.settings.selection_timeout_seconds,
                    )
                else:
                    self.status("Selection ignored: the IDE extension is disconnected")
                    self._gesture_action(
                        event, "selection.arm", "ignored", reason="IDE disconnected"
                    )
            else:
                self.status("Selection ignored: gaze tracking is unavailable")
                self._gesture_action(event, "selection.arm", "ignored", reason="gaze unavailable")
        elif gesture.type == GestureType.PINCH_CANCEL:
            self.locked_gaze = None
            self.ide.cancel_selection()
            self._gesture_action(event, "selection.cancel", "executed")
        elif gesture.type == GestureType.CLICK:
            if self.locked_gaze is not None:
                point = self._pixels(self.locked_gaze.point)
                self.input.click(point)
                self.status("Semantic selection requested")
                self._gesture_action(
                    event,
                    "pointer.click",
                    "executed",
                    x=round(point.x),
                    y=round(point.y),
                )
            else:
                self._gesture_action(event, "pointer.click", "ignored", reason="gaze not locked")
            self.locked_gaze = None
        elif gesture.type == GestureType.DRAG_START:
            self.locked_gaze = None
            self.ide.cancel_selection()
            self._gesture_action(event, "selection.cancel", "executed")
        elif gesture.type == GestureType.SCROLL:
            scaled = (
                gesture.delta.y * self.gestures.scroll_scale
                + self._editor_scroll_remainder
            )
            lines = trunc(scaled)
            self._editor_scroll_remainder = scaled - lines
            if lines:
                self.ide.scroll_editor(lines)
                self._gesture_action(event, "editor.scroll", "executed", lines=lines)
            else:
                self._gesture_action(event, "editor.scroll", "ignored", reason="zero lines")
        else:
            self._gesture_action(event, "none", "ignored", reason="no IDE mapping")

    def _on_navigator_gesture(self, event: RoleGestureEvent) -> None:
        gesture = event.gesture
        if self.state not in (
            IdeControllerState.TRACKING,
            IdeControllerState.AGENT_WORKING,
            IdeControllerState.REQUEST_PENDING,
        ):
            self._gesture_action(event, "none", "ignored", reason="controller state")
            return
        if gesture.type != GestureType.SCROLL:
            self._gesture_action(event, "none", "ignored", reason="no navigator mapping")
            return
        if gesture.timestamp - self._last_navigation_at < self.settings.navigation_cooldown_seconds:
            self._gesture_action(event, "review.navigate", "ignored", reason="cooldown")
            return
        direction = -1 if gesture.delta.y < 0 else 1
        self.ide.navigate_change(direction)
        self._last_navigation_at = gesture.timestamp
        self._gesture_action(event, "review.navigate", "executed", direction=direction)

    def on_gesture(self, event: RoleGestureEvent) -> None:
        self._diagnostic(
            "gesture",
            "committed",
            {
                "type": event.gesture.type.value,
                "role": event.role.value,
                "confidence": event.gesture.confidence,
                "delta": {"x": event.gesture.delta.x, "y": event.gesture.delta.y},
                "timestamp": event.gesture.timestamp,
                "controllerState": self.state.value,
            },
        )
        if event.gesture.type == GestureType.PAUSE_TOGGLE:
            self._toggle_pause()
            self._gesture_action(event, "control.pause-toggle", "executed")
            return
        if self.state == IdeControllerState.PAUSED:
            self._gesture_action(event, "none", "ignored", reason="controls paused")
            return
        if event.role == HandRole.EDITOR:
            self._on_editor_gesture(event)
        else:
            self._on_navigator_gesture(event)

    def poll(self) -> None:
        for message in self.ide.poll():
            self._handle_bridge_message(message)
        if self.voice_session is not None:
            for event in self.voice_session.poll():
                if event.type == VoiceEventType.STATE and event.state is not None:
                    self._diagnostic(
                        "speech",
                        "runtime.state",
                        {"state": event.state.value, "detail": event.detail},
                        event.request_id,
                    )
                    self.ide.voice_state(event.state, event.request_id, event.detail)
                    if event.state == VoiceState.READY:
                        self._active_voice_request = None
                        self._approval_pending = False
                        if self.state != IdeControllerState.PAUSED:
                            self.state = IdeControllerState.TRACKING
                elif event.type == VoiceEventType.LEVEL:
                    self.ide.voice_level(event.level, event.dbfs)
                elif event.type == VoiceEventType.PARTIAL and event.request_id is not None:
                    self._diagnostic(
                        "speech",
                        "transcript.partial",
                        {"text": event.text},
                        event.request_id,
                    )
                    self.ide.voice_partial(event.request_id, event.text)
                elif event.type == VoiceEventType.REQUEST and event.request_id is not None:
                    self._diagnostic(
                        "speech",
                        "transcript.committed",
                        {"transcript": event.text},
                        event.request_id,
                    )
                    self._active_voice_request = event.request_id
                    self.state = IdeControllerState.AGENT_WORKING
                    self.ide.voice_request(event.request_id, event.text)
        if self.state != IdeControllerState.TRANSCRIBING or self._transcription is None:
            return
        if not self._transcription.done():
            return
        try:
            transcript = self._transcription.result().strip()
            if transcript:
                self._diagnostic(
                    "speech", "transcript.committed", {"transcript": transcript, "engine": "local"}
                )
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

    def _handle_bridge_message(self, message: dict[str, object]) -> None:
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        request_id = params.get("requestId")
        if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 100):
            return
        if method == "voice.cancel":
            if self.voice_session is not None:
                self.voice_session.cancel(request_id)
            return
        if method == "voice.complete":
            status = params.get("status")
            summary = params.get("spokenSummary", "")
            if (
                self.voice_session is None
                or not isinstance(request_id, str)
                or not isinstance(status, str)
                or not isinstance(summary, str)
                or len(summary) > 160
            ):
                return
            completed = self.voice_session.complete(request_id, status, summary)
            if not completed and summary:
                completed = self.voice_session.speak(summary)
            if completed:
                self._approval_pending = False
            return
        if method == "voice.speak":
            text = params.get("text")
            if self.voice_session is not None and isinstance(text, str) and 0 < len(text) <= 160:
                self.voice_session.speak(text)
            return
        if method == "edit.approvalRequested":
            if request_id != self._active_voice_request:
                return
            files = params.get("files")
            change_count = params.get("changeCount")
            if (
                not isinstance(files, list)
                or len(files) > 3
                or not all(isinstance(path, str) and len(path) <= 500 for path in files)
                or not isinstance(change_count, int)
                or change_count < 1
                or change_count > 100
            ):
                return
            self._approval_pending = True
            self.state = IdeControllerState.REQUEST_PENDING
            self.status("Changes need review; use thumbs-up to apply or open palm to cancel")

    def shutdown(self) -> None:
        if self.state == IdeControllerState.DICTATING and self.dictation is not None:
            self.dictation.cancel()
        if self.state == IdeControllerState.REQUEST_PENDING:
            if self._active_voice_request is not None:
                self.ide.cancel_edit(self._active_voice_request)
            else:
                self.ide.cancel_request()
        if self.voice_session is not None:
            self.voice_session.cancel(self._active_voice_request)
        self.ide.cancel_selection()
        self.ide.set_paused(True)
        self.state = IdeControllerState.PAUSED
