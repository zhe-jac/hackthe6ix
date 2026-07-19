from __future__ import annotations

from collections.abc import Iterable

from chudvis.core.config import GestureSettings, IdeSettings
from chudvis.core.events import HandObservation, HandRole, RoleGestureEvent
from chudvis.gestures.engine import GestureEngine


class HandGestureRouter:
    """Route independently recognized hand gestures to stable IDE roles."""

    def __init__(
        self,
        gesture_settings: GestureSettings,
        ide_settings: IdeSettings,
    ) -> None:
        navigator = ide_settings.navigator_hand.lower()
        editor = ide_settings.editor_hand.lower()
        if navigator == editor:
            raise ValueError("Navigator and editor hands must be different")
        if navigator not in {"left", "right"} or editor not in {"left", "right"}:
            raise ValueError("IDE hand mappings must be 'left' or 'right'")
        self._hand_for_role = {
            HandRole.NAVIGATOR: navigator,
            HandRole.EDITOR: editor,
        }
        self._engines = {
            role: GestureEngine(gesture_settings)
            for role in (HandRole.NAVIGATOR, HandRole.EDITOR)
        }

    @property
    def engines(self) -> dict[HandRole, GestureEngine]:
        return self._engines.copy()

    def update(
        self,
        hands: Iterable[HandObservation],
        timestamp: float,
    ) -> list[RoleGestureEvent]:
        by_handedness: dict[str, HandObservation] = {}
        for hand in hands:
            label = hand.handedness.lower()
            current = by_handedness.get(label)
            if current is None or hand.confidence > current.confidence:
                by_handedness[label] = hand

        events: list[RoleGestureEvent] = []
        for role, engine in self._engines.items():
            role_hand = by_handedness.get(self._hand_for_role[role])
            events.extend(
                RoleGestureEvent(role, gesture)
                for gesture in engine.update(role_hand, timestamp)
            )
        return events
