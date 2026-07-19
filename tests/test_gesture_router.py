from __future__ import annotations

from chudvis.core.config import GestureSettings, IdeSettings
from chudvis.core.events import GestureType, HandObservation, HandRole, Point
from chudvis.gestures.router import HandGestureRouter


def _hand(
    kind: str,
    handedness: str,
    timestamp: float,
    shift_y: float = 0.0,
) -> HandObservation:
    points = [Point(0.5, 0.7) for _ in range(21)]
    points[0] = Point(0.5, 0.9)
    points[5] = Point(0.4, 0.62)
    points[9] = Point(0.5, 0.58)
    points[13] = Point(0.56, 0.62)
    points[17] = Point(0.6, 0.66)
    points[4] = Point(0.3, 0.65)
    points[8] = Point(0.7, 0.75)
    if kind == "pinch":
        points[4] = Point(0.49, 0.45)
        points[8] = Point(0.51, 0.45)
    elif kind == "open":
        points = [Point(point.x, point.y + shift_y) for point in points]
        for tip, pip, x in ((8, 6, 0.4), (12, 10, 0.48), (16, 14, 0.56), (20, 18, 0.64)):
            points[pip] = Point(x, 0.62 + shift_y)
            points[tip] = Point(x, 0.30 + shift_y)
        points[4] = Point(0.30, 0.52 + shift_y)
    return HandObservation(tuple(points), handedness, 0.95, timestamp)


def test_hands_have_independent_gesture_state() -> None:
    router = HandGestureRouter(
        GestureSettings(pinch_min_seconds=0.05),
        IdeSettings(),
    )

    started = router.update(
        (_hand("pinch", "left", 0.0), _hand("neutral", "right", 0.0)),
        0.0,
    )
    released = router.update(
        (_hand("neutral", "left", 0.1), _hand("pinch", "right", 0.1)),
        0.1,
    )

    assert [(event.role, event.gesture.type) for event in started] == [
        (HandRole.NAVIGATOR, GestureType.PINCH_START)
    ]
    assert [(event.role, event.gesture.type) for event in released] == [
        (HandRole.NAVIGATOR, GestureType.CLICK),
        (HandRole.EDITOR, GestureType.PINCH_START),
    ]


def test_hand_roles_can_be_swapped() -> None:
    router = HandGestureRouter(
        GestureSettings(),
        IdeSettings(navigator_hand="right", editor_hand="left"),
    )

    events = router.update((_hand("pinch", "right", 0.0),), 0.0)

    assert len(events) == 1
    assert events[0].role == HandRole.NAVIGATOR


def test_editor_hand_scroll_is_recognized_through_runtime_router() -> None:
    router = HandGestureRouter(
        GestureSettings(
            scroll_arm_seconds=0.3,
            scroll_deadzone=0.01,
            scroll_event_interval_seconds=0.05,
        ),
        IdeSettings(),
    )

    assert router.update((_hand("open", "right", 0.0),), 0.0) == []
    assert router.update((_hand("open", "right", 0.31),), 0.31) == []
    events = router.update((_hand("open", "right", 0.4, shift_y=0.03),), 0.4)

    assert len(events) == 1
    assert events[0].role == HandRole.EDITOR
    assert events[0].gesture.type == GestureType.SCROLL
    assert events[0].gesture.delta.y > 0


def test_duplicate_hand_mapping_is_rejected() -> None:
    try:
        HandGestureRouter(
            GestureSettings(),
            IdeSettings(navigator_hand="left", editor_hand="left"),
        )
    except ValueError as exc:
        assert "different" in str(exc)
    else:
        raise AssertionError("Expected duplicate hand mapping to be rejected")
