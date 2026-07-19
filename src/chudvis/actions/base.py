from __future__ import annotations

from typing import Protocol

from chudvis.core.events import Point


class InputAdapter(Protocol):
    def move_pointer(self, point: Point) -> None: ...

    def click(self, point: Point) -> None: ...

    def mouse_down(self, point: Point) -> None: ...

    def mouse_up(self) -> None: ...

    def move_relative(self, delta: Point) -> None: ...

    def scroll(self, amount: int) -> None: ...

    def type_text(self, text: str) -> None: ...

    def press_enter(self) -> None: ...


class RecordingInputAdapter:
    """Safe adapter used by tests and `--dry-run`."""

    def __init__(self, announce: bool = False) -> None:
        self.events: list[tuple[str, object]] = []
        self.announce = announce

    def _record(self, name: str, value: object = None) -> None:
        self.events.append((name, value))
        if self.announce:
            print(f"[dry-run] {name}: {value}")

    def move_pointer(self, point: Point) -> None:
        self._record("move_pointer", point)

    def click(self, point: Point) -> None:
        self._record("click", point)

    def mouse_down(self, point: Point) -> None:
        self._record("mouse_down", point)

    def mouse_up(self) -> None:
        self._record("mouse_up")

    def move_relative(self, delta: Point) -> None:
        self._record("move_relative", delta)

    def scroll(self, amount: int) -> None:
        self._record("scroll", amount)

    def type_text(self, text: str) -> None:
        self._record("type_text", text)

    def press_enter(self) -> None:
        self._record("press_enter")
