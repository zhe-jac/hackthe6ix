from __future__ import annotations

from concurrent.futures import Future

from chudvis.actions.base import RecordingInputAdapter
from chudvis.core.config import GestureSettings
from chudvis.core.controller import InteractionController
from chudvis.core.events import (
    ControllerState,
    GazeSample,
    GestureEvent,
    GestureType,
    Point,
)


class FakeDictation:
    def __init__(self, text: str = "hello world") -> None:
        self.text = text
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def finish(self) -> Future[str]:
        result: Future[str] = Future()
        result.set_result(self.text)
        return result

    def cancel(self) -> None:
        self.cancelled = True


def _sample(x: float, y: float, timestamp: float = 0.0) -> GazeSample:
    return GazeSample(Point(x, y), 0.9, True, timestamp)


def _event(kind: GestureType, timestamp: float = 0.0, delta: Point | None = None) -> GestureEvent:
    return GestureEvent(kind, timestamp, 0.9, delta or Point(0.0, 0.0))


def test_click_uses_gaze_locked_at_pinch_start() -> None:
    adapter = RecordingInputAdapter()
    controller = InteractionController(adapter, (1000, 500), GestureSettings())

    controller.on_gaze(_sample(0.25, 0.5))
    controller.on_gesture(_event(GestureType.PINCH_START))
    controller.on_gaze(_sample(0.9, 0.9, 0.1))
    controller.on_gesture(_event(GestureType.CLICK, 0.2))

    assert ("click", Point(250.0, 250.0)) in adapter.events
    assert ("click", Point(900.0, 450.0)) not in adapter.events


def test_stale_gaze_cannot_be_clicked() -> None:
    adapter = RecordingInputAdapter()
    controller = InteractionController(
        adapter,
        (1000, 500),
        GestureSettings(),
        max_gaze_age_seconds=0.25,
        status=lambda _: None,
    )
    controller.on_gaze(_sample(0.25, 0.5, 1.0))

    controller.on_gesture(_event(GestureType.PINCH_START, 1.5))
    controller.on_gesture(_event(GestureType.CLICK, 1.6))

    assert not any(name == "click" for name, _ in adapter.events)


def test_drag_uses_hand_delta_after_gaze_lock() -> None:
    adapter = RecordingInputAdapter()
    settings = GestureSettings(drag_scale=2.0)
    controller = InteractionController(adapter, (1000, 500), settings)
    controller.on_gaze(_sample(0.4, 0.3))
    controller.on_gesture(_event(GestureType.PINCH_START))

    controller.on_gesture(_event(GestureType.DRAG_START, 0.6))
    controller.on_gesture(_event(GestureType.DRAG_MOVE, 0.7, Point(0.01, 0.02)))
    controller.on_gesture(_event(GestureType.DRAG_END, 0.8))

    assert ("mouse_down", Point(400.0, 150.0)) in adapter.events
    assert ("move_relative", Point(20.0, 20.0)) in adapter.events
    assert ("mouse_up", None) in adapter.events
    assert controller.state == ControllerState.TRACKING


def test_scroll_moves_the_desktop_and_preserves_fractional_motion() -> None:
    adapter = RecordingInputAdapter()
    controller = InteractionController(
        adapter,
        (1000, 500),
        GestureSettings(scroll_scale=10.0),
    )

    controller.on_gesture(_event(GestureType.SCROLL, 0.0, Point(0.0, -0.04)))
    controller.on_gesture(_event(GestureType.SCROLL, 0.1, Point(0.0, -0.04)))
    controller.on_gesture(_event(GestureType.SCROLL, 0.2, Point(0.0, -0.04)))

    assert adapter.events == [("scroll", 1)]


def test_pause_blocks_clicks_until_resumed() -> None:
    adapter = RecordingInputAdapter()
    controller = InteractionController(
        adapter, (100, 100), GestureSettings(), status=lambda _: None
    )
    controller.on_gaze(_sample(0.5, 0.5))
    controller.on_gesture(_event(GestureType.PAUSE_TOGGLE))
    controller.on_gesture(_event(GestureType.PINCH_START))
    controller.on_gesture(_event(GestureType.CLICK))

    assert controller.state == ControllerState.PAUSED
    assert not any(name == "click" for name, _ in adapter.events)

    controller.on_gesture(_event(GestureType.PAUSE_TOGGLE, 1.0))
    assert controller.state == ControllerState.TRACKING


def test_dictation_types_and_presses_enter() -> None:
    adapter = RecordingInputAdapter()
    dictation = FakeDictation("test phrase")
    controller = InteractionController(
        adapter,
        (100, 100),
        GestureSettings(),
        max_gaze_age_seconds=0.3,
        dictation=dictation,
        status=lambda _: None,
    )

    controller.on_gesture(_event(GestureType.DICTATION_TOGGLE))
    assert controller.state == ControllerState.DICTATING
    controller.on_gesture(_event(GestureType.DICTATION_TOGGLE, 1.0))
    assert controller.state == ControllerState.TRANSCRIBING
    controller.poll()

    assert ("type_text", "test phrase") in adapter.events
    assert ("press_enter", None) in adapter.events
    assert controller.state == ControllerState.TRACKING
