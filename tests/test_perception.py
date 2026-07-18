from __future__ import annotations

from gazemotion.core.config import TrackingSettings
from gazemotion.core.events import HandObservation, Point
from gazemotion.perception.mediapipe_tracker import MediaPipeTracker


def _hand(timestamp: float, shift_x: float = 0.0) -> HandObservation:
    points = tuple(Point(0.4 + shift_x + index * 0.005, 0.5) for index in range(21))
    return HandObservation(points, "right", 0.9, timestamp)


def _labeled_hand(
    handedness: str,
    timestamp: float,
    center_x: float,
) -> HandObservation:
    points = tuple(Point(center_x + index * 0.001, 0.5) for index in range(21))
    return HandObservation(points, handedness, 0.9, timestamp)


def _tracker(required_frames: int = 3) -> MediaPipeTracker:
    tracker = MediaPipeTracker.__new__(MediaPipeTracker)
    tracker.settings = TrackingSettings(hand_confirmation_frames=required_frames)
    tracker._hand_candidate = None
    tracker._hand_candidate_frames = 0
    tracker._hand_confirmed = False
    return tracker


def test_transient_hand_candidate_is_not_action_ready() -> None:
    tracker = _tracker(required_frames=3)

    assert tracker._stabilize_hand(_hand(0.0)) is None
    assert tracker._stabilize_hand(None) is None
    assert tracker._hand_candidate_frames == 0


def test_hand_requires_consecutive_confirmation_frames() -> None:
    tracker = _tracker(required_frames=3)

    assert tracker._stabilize_hand(_hand(0.0)) is None
    assert tracker._stabilize_hand(_hand(0.1, 0.01)) is None
    confirmed = tracker._stabilize_hand(_hand(0.2, 0.02))

    assert confirmed is not None
    assert tracker._hand_confirmed is True


def test_large_candidate_jump_restarts_confirmation() -> None:
    tracker = _tracker(required_frames=2)
    tracker._stabilize_hand(_hand(0.0))
    assert tracker._stabilize_hand(_hand(0.1, 0.01)) is not None

    assert tracker._stabilize_hand(_hand(0.2, 0.5)) is None
    assert tracker._hand_candidate_frames == 1


def _multi_tracker(required_frames: int = 2) -> MediaPipeTracker:
    tracker = MediaPipeTracker.__new__(MediaPipeTracker)
    tracker.settings = TrackingSettings(hand_confirmation_frames=required_frames)
    tracker._hand_tracks = {}
    tracker._next_hand_track_id = 1
    return tracker


def test_two_hands_are_confirmed_independently_when_detection_order_changes() -> None:
    tracker = _multi_tracker()

    confirmed, _candidates, _progress = tracker._stabilize_hands(
        (
            _labeled_hand("left", 0.0, 0.25),
            _labeled_hand("right", 0.0, 0.70),
        )
    )
    assert confirmed == ()

    confirmed, _candidates, progress = tracker._stabilize_hands(
        (
            _labeled_hand("right", 0.1, 0.69),
            _labeled_hand("left", 0.1, 0.26),
        )
    )

    assert [hand.handedness for hand in confirmed] == ["left", "right"]
    assert progress == (2, 2)


def test_confirmed_hand_keeps_stable_label_during_classifier_flicker() -> None:
    tracker = _multi_tracker()
    tracker._stabilize_hands(
        (
            _labeled_hand("left", 0.0, 0.25),
            _labeled_hand("right", 0.0, 0.70),
        )
    )

    confirmed, _candidates, _progress = tracker._stabilize_hands(
        (
            _labeled_hand("right", 0.1, 0.26),
            _labeled_hand("right", 0.1, 0.69),
        )
    )

    assert [hand.handedness for hand in confirmed] == ["left", "right"]
