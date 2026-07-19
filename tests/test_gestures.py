from __future__ import annotations

from chudvis.core.config import GestureSettings
from chudvis.core.events import GestureType, HandObservation, Point
from chudvis.gestures.engine import GestureEngine


def _base_points() -> list[Point]:
    points = [Point(0.5, 0.7) for _ in range(21)]
    points[0] = Point(0.5, 0.9)
    points[5] = Point(0.4, 0.62)
    points[9] = Point(0.5, 0.58)
    points[13] = Point(0.56, 0.62)
    points[17] = Point(0.6, 0.66)
    return points


def _hand(kind: str, timestamp: float, shift_y: float = 0.0) -> HandObservation:
    points = _base_points()
    if kind == "pinch":
        points[4] = Point(0.49, 0.45)
        points[8] = Point(0.51, 0.45)
    elif kind == "open":
        points = [Point(point.x, point.y + shift_y) for point in points]
        for tip, pip, x in ((8, 6, 0.4), (12, 10, 0.48), (16, 14, 0.56), (20, 18, 0.64)):
            points[pip] = Point(x, 0.62 + shift_y)
            points[tip] = Point(x, 0.30 + shift_y)
        points[4] = Point(0.30, 0.52 + shift_y)
    elif kind == "thumbs":
        points[2] = Point(0.40, 0.70)
        points[3] = Point(0.42, 0.55)
        points[4] = Point(0.43, 0.35)
        for tip, pip, x in ((8, 6, 0.43), (12, 10, 0.49), (16, 14, 0.55), (20, 18, 0.61)):
            points[pip] = Point(x, 0.61)
            points[tip] = Point(x, 0.76)
    else:
        points[4] = Point(0.3, 0.65)
        points[8] = Point(0.7, 0.75)
        for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
            points[pip] = Point(points[tip].x, 0.64)
            points[tip] = Point(points[tip].x, 0.76)
    if shift_y and kind != "open":
        points = [Point(point.x, point.y + shift_y) for point in points]
    return HandObservation(tuple(points), "right", 0.95, timestamp)


def _types(events: list) -> list[GestureType]:
    return [event.type for event in events]


def test_quick_pinch_becomes_one_click() -> None:
    engine = GestureEngine()

    assert _types(engine.update(_hand("pinch", 0.0), 0.0)) == [GestureType.PINCH_START]
    assert engine.update(_hand("pinch", 0.1), 0.1) == []
    assert _types(engine.update(_hand("neutral", 0.2), 0.2)) == [GestureType.CLICK]
    assert engine.update(_hand("neutral", 0.3), 0.3) == []


def test_single_frame_pinch_is_cancelled_not_clicked() -> None:
    engine = GestureEngine(GestureSettings(pinch_min_seconds=0.1))

    engine.update(_hand("pinch", 0.0), 0.0)
    events = engine.update(_hand("neutral", 0.04), 0.04)

    assert _types(events) == [GestureType.PINCH_CANCEL]


def test_held_pinch_becomes_drag() -> None:
    engine = GestureEngine(GestureSettings(drag_hold_seconds=0.5))

    engine.update(_hand("pinch", 0.0), 0.0)
    assert _types(engine.update(_hand("pinch", 0.6), 0.6)) == [GestureType.DRAG_START]
    assert _types(engine.update(_hand("pinch", 0.7, 0.03), 0.7)) == [GestureType.DRAG_MOVE]
    assert _types(engine.update(_hand("neutral", 0.8), 0.8)) == [GestureType.DRAG_END]


def test_open_palm_hold_toggles_pause_once() -> None:
    settings = GestureSettings(open_hold_seconds=1.0, event_cooldown_seconds=0.1)
    engine = GestureEngine(settings)

    engine.update(_hand("open", 0.0), 0.0)
    assert _types(engine.update(_hand("open", 1.1), 1.1)) == [GestureType.PAUSE_TOGGLE]
    assert engine.update(_hand("open", 1.3), 1.3) == []


def test_open_palm_motion_scrolls() -> None:
    engine = GestureEngine(
        GestureSettings(
            scroll_arm_seconds=0.3,
            scroll_deadzone=0.01,
            scroll_activation_distance=0.03,
        )
    )

    engine.update(_hand("open", 0.0), 0.0)
    assert engine.update(_hand("open", 0.2, shift_y=0.04), 0.2) == []
    engine.update(_hand("open", 0.31, shift_y=0.04), 0.31)
    events = engine.update(_hand("open", 0.4, shift_y=0.08), 0.4)

    assert _types(events) == [GestureType.SCROLL]
    assert events[0].delta.y > 0


def test_open_palm_jitter_does_not_continuously_scroll() -> None:
    engine = GestureEngine(
        GestureSettings(
            scroll_arm_seconds=0.2,
            scroll_deadzone=0.01,
            scroll_activation_distance=0.04,
        )
    )
    engine.update(_hand("open", 0.0), 0.0)

    events = []
    for index, shift in enumerate((0.003, -0.003, 0.004, -0.002, 0.003), start=1):
        timestamp = 0.2 + index * 0.1
        events.extend(engine.update(_hand("open", timestamp, shift_y=shift), timestamp))

    assert GestureType.SCROLL not in _types(events)


def test_scroll_events_are_rate_limited() -> None:
    engine = GestureEngine(
        GestureSettings(
            scroll_arm_seconds=0.1,
            scroll_deadzone=0.005,
            scroll_activation_distance=0.02,
            scroll_event_interval_seconds=0.2,
        )
    )
    engine.update(_hand("open", 0.0), 0.0)
    engine.update(_hand("open", 0.11), 0.11)
    first = engine.update(_hand("open", 0.2, shift_y=0.03), 0.2)
    second = engine.update(_hand("open", 0.25, shift_y=0.06), 0.25)

    assert _types(first) == [GestureType.SCROLL]
    assert second == []


def test_thumbs_up_toggles_dictation_once() -> None:
    engine = GestureEngine(GestureSettings(thumbs_hold_seconds=0.5, event_cooldown_seconds=0.1))

    engine.update(_hand("thumbs", 0.0), 0.0)
    assert _types(engine.update(_hand("thumbs", 0.6), 0.6)) == [GestureType.DICTATION_TOGGLE]
    assert engine.update(_hand("thumbs", 0.8), 0.8) == []


def test_lost_hand_cancels_active_pinch_after_short_grace() -> None:
    engine = GestureEngine(GestureSettings(pinch_lost_grace_seconds=0.1))
    engine.update(_hand("pinch", 0.0), 0.0)

    assert engine.update(None, 0.05) == []
    assert _types(engine.update(None, 0.16)) == [GestureType.PINCH_CANCEL]


def test_pinch_released_while_missing_is_cancelled_not_clicked() -> None:
    engine = GestureEngine(
        GestureSettings(pinch_min_seconds=0.05, pinch_lost_grace_seconds=0.1)
    )
    engine.update(_hand("pinch", 0.0), 0.0)

    assert engine.update(None, 0.04) == []
    assert _types(engine.update(_hand("neutral", 0.08), 0.08)) == [
        GestureType.PINCH_CANCEL
    ]


def test_reacquired_pinch_can_still_click() -> None:
    engine = GestureEngine(
        GestureSettings(pinch_min_seconds=0.05, pinch_lost_grace_seconds=0.1)
    )
    engine.update(_hand("pinch", 0.0), 0.0)

    assert engine.update(None, 0.03) == []
    assert engine.update(_hand("pinch", 0.06), 0.06) == []
    assert _types(engine.update(_hand("neutral", 0.10), 0.10)) == [GestureType.CLICK]


def test_missing_time_does_not_turn_pinch_into_drag() -> None:
    engine = GestureEngine(
        GestureSettings(drag_hold_seconds=0.5, pinch_lost_grace_seconds=0.3)
    )
    engine.update(_hand("pinch", 0.0), 0.0)
    engine.update(_hand("pinch", 0.15), 0.15)
    engine.update(None, 0.20)
    engine.update(None, 0.35)

    assert engine.update(_hand("pinch", 0.40), 0.40) == []
    assert engine.update(_hand("pinch", 0.65), 0.65) == []
    assert _types(engine.update(_hand("pinch", 0.71), 0.71)) == [GestureType.DRAG_START]


def test_drag_survives_brief_tracking_dropout_without_jump() -> None:
    engine = GestureEngine(
        GestureSettings(drag_hold_seconds=0.5, drag_lost_grace_seconds=0.3)
    )
    engine.update(_hand("pinch", 0.0), 0.0)
    assert _types(engine.update(_hand("pinch", 0.6), 0.6)) == [GestureType.DRAG_START]

    assert engine.update(None, 0.65) == []
    assert engine.update(None, 0.80) == []
    assert engine.update(_hand("pinch", 0.85, 0.03), 0.85) == []
    assert _types(engine.update(_hand("pinch", 0.90, 0.05), 0.90)) == [
        GestureType.DRAG_MOVE
    ]
    assert _types(engine.update(_hand("neutral", 0.95, 0.05), 0.95)) == [
        GestureType.DRAG_END
    ]


def test_lost_drag_ends_after_grace() -> None:
    engine = GestureEngine(
        GestureSettings(drag_hold_seconds=0.5, drag_lost_grace_seconds=0.3)
    )
    engine.update(_hand("pinch", 0.0), 0.0)
    engine.update(_hand("pinch", 0.6), 0.6)

    assert engine.update(None, 0.65) == []
    assert _types(engine.update(None, 1.0)) == [GestureType.DRAG_END]


def test_missing_hand_resets_thumbs_up_hold() -> None:
    engine = GestureEngine(
        GestureSettings(thumbs_hold_seconds=0.5, event_cooldown_seconds=0.1)
    )
    engine.update(_hand("thumbs", 0.0), 0.0)
    engine.update(_hand("thumbs", 0.3), 0.3)

    assert engine.update(None, 0.35) == []
    assert engine.update(_hand("thumbs", 0.60), 0.60) == []
    assert engine.update(_hand("thumbs", 0.85), 0.85) == []
    assert _types(engine.update(_hand("thumbs", 1.11), 1.11)) == [
        GestureType.DICTATION_TOGGLE
    ]


def test_missing_hand_resets_open_palm_hold() -> None:
    engine = GestureEngine(
        GestureSettings(open_hold_seconds=0.5, event_cooldown_seconds=0.1)
    )
    engine.update(_hand("open", 0.0), 0.0)
    engine.update(_hand("open", 0.3), 0.3)

    assert engine.update(None, 0.35) == []
    assert engine.update(_hand("open", 0.60), 0.60) == []
    assert engine.update(_hand("open", 0.85), 0.85) == []
    assert _types(engine.update(_hand("open", 1.11), 1.11)) == [
        GestureType.PAUSE_TOGGLE
    ]


def test_drag_hold_progress_freezes_while_hand_is_missing() -> None:
    engine = GestureEngine(GestureSettings(pinch_lost_grace_seconds=0.5))
    engine.update(_hand("pinch", 0.0), 0.0)
    engine.update(None, 0.25)

    progress_at_loss = engine.hold_progress(0.25)["drag"]
    assert engine.hold_progress(0.45)["drag"] == progress_at_loss


def test_missing_hand_with_no_active_gesture_is_silent() -> None:
    engine = GestureEngine()
    assert engine.update(None, 0.0) == []
    assert engine.update(None, 5.0) == []


def _scaled_hand(kind: str, timestamp: float, scale: float) -> HandObservation:
    original = _hand(kind, timestamp)
    center = Point(0.5, 0.7)
    points = tuple(
        Point(center.x + (point.x - center.x) * scale, center.y + (point.y - center.y) * scale)
        for point in original.landmarks
    )
    return HandObservation(points, original.handedness, original.confidence, timestamp)


def test_thumbs_up_detected_for_small_far_away_hand() -> None:
    engine = GestureEngine(
        GestureSettings(thumbs_hold_seconds=0.5, event_cooldown_seconds=0.1)
    )

    engine.update(_scaled_hand("thumbs", 0.0, scale=0.1), 0.0)
    events = engine.update(_scaled_hand("thumbs", 0.6, scale=0.1), 0.6)
    assert _types(events) == [GestureType.DICTATION_TOGGLE]
