from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class GazeFeatures:
    """Normalized eye/head features used by the calibration model."""

    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class GazeSample:
    point: Point
    confidence: float
    stable: bool
    timestamp: float


@dataclass(frozen=True, slots=True)
class HandObservation:
    """A single hand's 21 MediaPipe landmarks in normalized frame coordinates."""

    landmarks: tuple[Point, ...]
    handedness: str
    confidence: float
    timestamp: float

    def __post_init__(self) -> None:
        if len(self.landmarks) != 21:
            raise ValueError("HandObservation requires exactly 21 landmarks")


class GestureType(str, Enum):
    PINCH_START = "pinch_start"
    PINCH_CANCEL = "pinch_cancel"
    CLICK = "click"
    DRAG_START = "drag_start"
    DRAG_MOVE = "drag_move"
    DRAG_END = "drag_end"
    SCROLL = "scroll"
    PAUSE_TOGGLE = "pause_toggle"
    DICTATION_TOGGLE = "dictation_toggle"


@dataclass(frozen=True, slots=True)
class GestureEvent:
    type: GestureType
    timestamp: float
    confidence: float = 1.0
    delta: Point = Point(0.0, 0.0)


class ControllerState(str, Enum):
    TRACKING = "tracking"
    DRAGGING = "dragging"
    DICTATING = "dictating"
    TRANSCRIBING = "transcribing"
    PAUSED = "paused"
