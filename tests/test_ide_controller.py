from __future__ import annotations

from concurrent.futures import Future

from chudvis.actions.base import RecordingInputAdapter
from chudvis.core.config import GestureSettings, IdeSettings
from chudvis.core.events import (
    GazeSample,
    GestureEvent,
    GestureType,
    HandRole,
    Point,
    RoleGestureEvent,
)
from chudvis.ide.adapter import RecordingIdeAdapter
from chudvis.ide.controller import IdeControllerState, IdeInteractionController
from chudvis.speech.realtime_voice import VoiceEvent, VoiceEventType, VoiceState


class FakeDictation:
    def __init__(self, text: str = "extract this function") -> None:
        self.text = text
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def finish(self) -> Future[str]:
        future: Future[str] = Future()
        future.set_result(self.text)
        return future

    def cancel(self) -> None:
        self.cancelled = True


class DisconnectedIdeAdapter(RecordingIdeAdapter):
    def arm_selection(self, timeout_seconds: float) -> bool:
        self._record("arm_selection", timeout_seconds)
        return False


class FakeVoiceSession:
    def __init__(self) -> None:
        self.state = VoiceState.READY
        self.request_id: str | None = None
        self.events: list[VoiceEvent] = []
        self.cancelled: list[str | None] = []
        self.completions: list[tuple[str, str, str]] = []
        self.paused: list[bool] = []

    def start(self) -> None:
        pass

    def poll(self, max_events: int = 64) -> list[VoiceEvent]:
        events = self.events[:max_events]
        self.events = self.events[max_events:]
        return events

    def cancel(self, request_id: str | None = None) -> bool:
        self.cancelled.append(request_id)
        return True

    def complete(self, request_id: str, status: str, spoken_summary: str = "") -> bool:
        self.completions.append((request_id, status, spoken_summary))
        return True

    def set_paused(self, paused: bool) -> None:
        self.paused.append(paused)

    def close(self) -> None:
        pass


def _role_event(
    role: HandRole,
    kind: GestureType,
    timestamp: float = 0.0,
    delta: Point | None = None,
) -> RoleGestureEvent:
    return RoleGestureEvent(role, GestureEvent(kind, timestamp, 0.9, delta or Point(0.0, 0.0)))


def _controller(
    dictation: FakeDictation | None = None,
    voice_session: FakeVoiceSession | None = None,
) -> tuple[IdeInteractionController, RecordingInputAdapter, RecordingIdeAdapter]:
    inputs = RecordingInputAdapter()
    ide = RecordingIdeAdapter()
    controller = IdeInteractionController(
        inputs,
        ide,
        (1000, 500),
        GestureSettings(scroll_scale=50),
        IdeSettings(),
        dictation=dictation,
        voice_session=voice_session,
        status=lambda _message: None,
    )
    return controller, inputs, ide


def test_editor_pinch_arms_then_clicks_locked_gaze() -> None:
    controller, inputs, ide = _controller()
    controller.on_gaze(GazeSample(Point(0.25, 0.5), 0.9, True, 1.0))

    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.PINCH_START, 1.1))
    controller.on_gaze(GazeSample(Point(0.9, 0.9), 0.9, True, 1.15))
    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.CLICK, 1.2))

    assert ide.events[0] == ("arm_selection", 0.6)
    assert ("click", Point(250.0, 250.0)) in inputs.events


def test_hand_roles_route_scroll_to_different_actions() -> None:
    controller, _inputs, ide = _controller()

    controller.on_gesture(
        _role_event(HandRole.NAVIGATOR, GestureType.SCROLL, 1.0, Point(0.0, -0.1))
    )
    controller.on_gesture(
        _role_event(HandRole.EDITOR, GestureType.SCROLL, 1.1, Point(0.0, 0.1))
    )

    assert ("navigate_change", -1) in ide.events
    assert ("scroll_editor", 5) in ide.events


def test_disconnected_extension_prevents_raw_selection_click() -> None:
    inputs = RecordingInputAdapter()
    ide = DisconnectedIdeAdapter()
    controller = IdeInteractionController(
        inputs,
        ide,
        (1000, 500),
        GestureSettings(),
        IdeSettings(),
        status=lambda _message: None,
    )
    controller.on_gaze(GazeSample(Point(0.25, 0.5), 0.9, True, 1.0))

    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.PINCH_START, 1.1))
    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.CLICK, 1.2))

    assert not any(name == "click" for name, _value in inputs.events)


def test_voice_request_requires_explicit_confirmation() -> None:
    dictation = FakeDictation()
    controller, _inputs, ide = _controller(dictation)

    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.DICTATION_TOGGLE))
    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.DICTATION_TOGGLE, 1.0))
    controller.poll()

    assert controller.state == IdeControllerState.REQUEST_PENDING
    assert ("show_request", "extract this function") in ide.events
    assert not any(name == "submit_request" for name, _value in ide.events)

    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.DICTATION_TOGGLE, 2.0))

    assert controller.state == IdeControllerState.AGENT_WORKING
    assert ("submit_request", None) in ide.events


def test_open_palm_cancels_pending_request() -> None:
    dictation = FakeDictation()
    controller, _inputs, ide = _controller(dictation)
    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.DICTATION_TOGGLE))
    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.DICTATION_TOGGLE, 1.0))
    controller.poll()

    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.PAUSE_TOGGLE, 2.0))

    assert controller.state == IdeControllerState.TRACKING
    assert ("cancel_request", None) in ide.events


def test_streaming_voice_events_and_expansion_approval_round_trip() -> None:
    voice = FakeVoiceSession()
    controller, _inputs, ide = _controller(voice_session=voice)
    request_id = "request-1"
    voice.events.extend(
        [
            VoiceEvent(
                VoiceEventType.STATE,
                request_id=request_id,
                state=VoiceState.LISTENING,
            ),
            VoiceEvent(VoiceEventType.PARTIAL, request_id=request_id, text="fix"),
            VoiceEvent(
                VoiceEventType.REQUEST,
                request_id=request_id,
                text="fix the parser",
            ),
        ]
    )

    controller.poll()

    assert ("voice_partial", (request_id, "fix")) in ide.events
    assert ("voice_request", (request_id, "fix the parser")) in ide.events
    ide.inbound.append(
        {
            "method": "edit.approvalRequested",
            "params": {
                "requestId": request_id,
                "files": ["src/parser.py", "src/types.py"],
                "changeCount": 2,
            },
        }
    )
    controller.poll()
    assert controller.state == IdeControllerState.REQUEST_PENDING

    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.DICTATION_TOGGLE))
    assert ("approve_edit", request_id) in ide.events

    ide.inbound.append(
        {
            "method": "voice.complete",
            "params": {
                "requestId": request_id,
                "status": "succeeded",
                "spokenSummary": "Updated the parser.",
            },
        }
    )
    controller.poll()
    assert voice.completions == [
        (request_id, "succeeded", "Updated the parser."),
    ]


def test_wake_voice_prevents_competing_local_dictation_and_pauses_with_ide() -> None:
    voice = FakeVoiceSession()
    dictation = FakeDictation()
    controller, _inputs, _ide = _controller(dictation, voice)

    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.DICTATION_TOGGLE))
    assert not dictation.started

    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.PAUSE_TOGGLE, 1.0))
    controller.on_gesture(_role_event(HandRole.EDITOR, GestureType.PAUSE_TOGGLE, 2.0))
    assert voice.paused == [True, False]
