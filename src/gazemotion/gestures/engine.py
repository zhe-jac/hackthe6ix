from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from gazemotion.core.config import GestureSettings
from gazemotion.core.events import GestureEvent, GestureType, HandObservation, Point


def _distance(a: Point, b: Point) -> float:
    return hypot(a.x - b.x, a.y - b.y)


@dataclass(frozen=True, slots=True)
class GestureMetrics:
    palm_center: Point
    pinch_ratio: float
    open_palm: bool
    thumbs_up: bool


class GestureEngine:
    """Recognize a deliberately small, stateful gesture vocabulary."""

    def __init__(self, settings: GestureSettings | None = None) -> None:
        self.settings = settings or GestureSettings()
        self._pinching = False
        self._pinch_started = 0.0
        self._pinch_origin = Point(0.0, 0.0)
        self._last_palm = Point(0.0, 0.0)
        self._dragging = False
        self._open_pose_since: float | None = None
        self._still_since: float | None = None
        self._still_anchor: Point | None = None
        self._open_latched = False
        self._scroll_accumulator_y = 0.0
        self._last_scroll_event = -1e9
        self._thumbs_since: float | None = None
        self._thumbs_latched = False
        self._last_discrete = -1e9
        self._missing_since: float | None = None

    @staticmethod
    def _palm_center(hand: HandObservation) -> Point:
        indices = (0, 5, 9, 13, 17)
        return Point(
            sum(hand.landmarks[i].x for i in indices) / len(indices),
            sum(hand.landmarks[i].y for i in indices) / len(indices),
        )

    @staticmethod
    def _is_open_palm(hand: HandObservation) -> bool:
        wrist = hand.landmarks[0]
        extended = 0
        for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
            if _distance(wrist, hand.landmarks[tip]) > _distance(wrist, hand.landmarks[pip]) * 1.12:
                extended += 1
        return extended >= 4

    @staticmethod
    def _is_thumbs_up(hand: HandObservation) -> bool:
        points = hand.landmarks
        # Thresholds scale with palm width so the pose reads the same whether
        # the hand is close to the camera or across the room.
        palm_width = max(_distance(points[5], points[17]), 1e-4)
        thumb_vertical = (
            points[4].y < points[3].y - 0.2 * palm_width and points[3].y < points[2].y
        )
        curled = sum(
            points[tip].y > points[pip].y for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18))
        )
        return thumb_vertical and curled >= 3

    @staticmethod
    def _pinch_ratio(hand: HandObservation) -> float:
        palm_width = max(_distance(hand.landmarks[5], hand.landmarks[17]), 1e-4)
        return _distance(hand.landmarks[4], hand.landmarks[8]) / palm_width

    @classmethod
    def measure(cls, hand: HandObservation | None) -> GestureMetrics | None:
        """Return human-readable metrics used by the gesture state machines."""
        if hand is None:
            return None
        return GestureMetrics(
            palm_center=cls._palm_center(hand),
            pinch_ratio=cls._pinch_ratio(hand),
            open_palm=cls._is_open_palm(hand),
            thumbs_up=cls._is_thumbs_up(hand),
        )

    def _discrete_allowed(self, timestamp: float) -> bool:
        return timestamp - self._last_discrete >= self.settings.event_cooldown_seconds

    def hold_progress(self, timestamp: float) -> dict[str, float]:
        """Progress (0..1) of the timed holds, for UI feedback."""
        progress = {"thumbs_up": 0.0, "pause": 0.0, "drag": 0.0}
        if self._thumbs_since is not None and not self._thumbs_latched:
            progress["thumbs_up"] = min(
                (timestamp - self._thumbs_since) / self.settings.thumbs_hold_seconds, 1.0
            )
        if self._still_since is not None and not self._open_latched:
            progress["pause"] = min(
                (timestamp - self._still_since) / self.settings.open_hold_seconds, 1.0
            )
        if self._pinching and not self._dragging:
            progress["drag"] = min(
                (timestamp - self._pinch_started) / self.settings.drag_hold_seconds, 1.0
            )
        return progress

    @property
    def current_mode(self) -> str:
        if self._dragging:
            return "dragging"
        if self._pinching:
            return "pinch_armed"
        if self._thumbs_since is not None:
            return "thumbs_up_arming"
        if self._open_pose_since is not None:
            return "open_palm_arming"
        return "neutral"

    def _reset_open_state(self) -> None:
        self._open_pose_since = None
        self._still_since = None
        self._still_anchor = None
        self._open_latched = False
        self._scroll_accumulator_y = 0.0

    def _reset_non_pinch_holds(self) -> None:
        self._reset_open_state()
        self._thumbs_since = None
        self._thumbs_latched = False

    def _handle_missing(self, timestamp: float) -> list[GestureEvent]:
        events: list[GestureEvent] = []
        if self._dragging:
            events.append(GestureEvent(GestureType.DRAG_END, timestamp, confidence=0.5))
        elif self._pinching:
            events.append(GestureEvent(GestureType.PINCH_CANCEL, timestamp, confidence=0.5))
        self._pinching = False
        self._dragging = False
        self._reset_non_pinch_holds()
        return events

    def _has_active_state(self) -> bool:
        return (
            self._pinching
            or self._dragging
            or self._open_pose_since is not None
            or self._thumbs_since is not None
        )

    def _handle_missing_frame(self, timestamp: float) -> list[GestureEvent]:
        """Tolerate brief tracking dropouts before cancelling in-flight gestures.

        Hand detection flickers for a frame or two during fast movement; without
        a grace period every flicker ended drags and restarted hold timers.
        """
        if not self._has_active_state():
            self._missing_since = None
            return []
        if self._missing_since is None:
            self._missing_since = timestamp
        if timestamp - self._missing_since < self.settings.hand_lost_grace_seconds:
            return []
        self._missing_since = None
        return self._handle_missing(timestamp)

    def update(
        self,
        hand: HandObservation | None,
        timestamp: float,
    ) -> list[GestureEvent]:
        if hand is None:
            return self._handle_missing_frame(timestamp)
        self._missing_since = None

        events: list[GestureEvent] = []
        metrics = self.measure(hand)
        assert metrics is not None
        palm = metrics.palm_center
        pinch_ratio = metrics.pinch_ratio

        if not self._pinching and pinch_ratio <= self.settings.pinch_on:
            self._pinching = True
            self._pinch_started = timestamp
            self._pinch_origin = palm
            self._last_palm = palm
            self._reset_non_pinch_holds()
            events.append(GestureEvent(GestureType.PINCH_START, timestamp, hand.confidence))

        if self._pinching:
            if pinch_ratio < self.settings.pinch_off:
                duration = timestamp - self._pinch_started
                delta = Point(palm.x - self._last_palm.x, palm.y - self._last_palm.y)
                if not self._dragging and duration >= self.settings.drag_hold_seconds:
                    self._dragging = True
                    self._last_palm = palm
                    return [GestureEvent(GestureType.DRAG_START, timestamp, hand.confidence)]
                if self._dragging and (abs(delta.x) > 0.001 or abs(delta.y) > 0.001):
                    events.append(
                        GestureEvent(GestureType.DRAG_MOVE, timestamp, hand.confidence, delta)
                    )
                self._last_palm = palm
                return events

            self._pinching = False
            if self._dragging:
                self._dragging = False
                events.append(GestureEvent(GestureType.DRAG_END, timestamp, hand.confidence))
            elif (
                timestamp - self._pinch_started >= self.settings.pinch_min_seconds
                and self._discrete_allowed(timestamp)
            ):
                self._last_discrete = timestamp
                events.append(GestureEvent(GestureType.CLICK, timestamp, hand.confidence))
            else:
                events.append(GestureEvent(GestureType.PINCH_CANCEL, timestamp, hand.confidence))
            return events

        if metrics.thumbs_up:
            self._reset_open_state()
            if self._thumbs_since is None:
                self._thumbs_since = timestamp
            elif (
                not self._thumbs_latched
                and timestamp - self._thumbs_since >= self.settings.thumbs_hold_seconds
                and self._discrete_allowed(timestamp)
            ):
                self._thumbs_latched = True
                self._last_discrete = timestamp
                events.append(
                    GestureEvent(GestureType.DICTATION_TOGGLE, timestamp, hand.confidence)
                )
            return events

        self._thumbs_since = None
        self._thumbs_latched = False

        if metrics.open_palm:
            if self._open_pose_since is None:
                self._open_pose_since = timestamp
                self._still_since = timestamp
                self._still_anchor = palm
                self._last_palm = palm

            assert self._still_anchor is not None
            assert self._still_since is not None
            movement_from_anchor = _distance(palm, self._still_anchor)
            delta_y = palm.y - self._last_palm.y

            if movement_from_anchor > self.settings.open_stillness:
                self._still_since = timestamp
                self._still_anchor = palm

            scroll_armed = timestamp - self._open_pose_since >= self.settings.scroll_arm_seconds
            if (
                scroll_armed
                and not self._open_latched
                and abs(delta_y) >= self.settings.scroll_deadzone * 0.5
            ):
                if self._scroll_accumulator_y * delta_y < 0:
                    self._scroll_accumulator_y = delta_y
                else:
                    self._scroll_accumulator_y += delta_y
            elif abs(delta_y) < self.settings.scroll_deadzone * 0.5:
                self._scroll_accumulator_y *= 0.5

            scroll_ready = (
                abs(self._scroll_accumulator_y) >= self.settings.scroll_activation_distance
                and timestamp - self._last_scroll_event
                >= self.settings.scroll_event_interval_seconds
            )
            if scroll_ready:
                scroll_delta = self._scroll_accumulator_y
                self._scroll_accumulator_y = 0.0
                self._last_scroll_event = timestamp
                self._last_palm = palm
                return [
                    GestureEvent(
                        GestureType.SCROLL,
                        timestamp,
                        hand.confidence,
                        Point(0.0, scroll_delta),
                    )
                ]

            if (
                not self._open_latched
                and timestamp - self._still_since >= self.settings.open_hold_seconds
                and self._discrete_allowed(timestamp)
            ):
                self._open_latched = True
                self._last_discrete = timestamp
                events.append(GestureEvent(GestureType.PAUSE_TOGGLE, timestamp, hand.confidence))
            self._last_palm = palm
            return events

        self._reset_open_state()
        return events
