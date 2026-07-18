from __future__ import annotations

from gazemotion.core.events import Point


class PynputInputAdapter:
    def __init__(self) -> None:
        try:
            from pynput import keyboard, mouse
        except Exception as exc:
            raise RuntimeError(
                "Global input could not initialize. On Linux, use an X11 session or run "
                "with --dry-run."
            ) from exc
        self._mouse_module = mouse
        self._keyboard_module = keyboard
        self._mouse = mouse.Controller()
        self._keyboard = keyboard.Controller()
        self._button_held = False

    @staticmethod
    def _coordinates(point: Point) -> tuple[int, int]:
        return (round(point.x), round(point.y))

    def move_pointer(self, point: Point) -> None:
        self._mouse.position = self._coordinates(point)

    def click(self, point: Point) -> None:
        self._mouse.position = self._coordinates(point)
        self._mouse.click(self._mouse_module.Button.left, 1)

    def mouse_down(self, point: Point) -> None:
        self._mouse.position = self._coordinates(point)
        if not self._button_held:
            self._mouse.press(self._mouse_module.Button.left)
            self._button_held = True

    def mouse_up(self) -> None:
        if self._button_held:
            self._mouse.release(self._mouse_module.Button.left)
            self._button_held = False

    def move_relative(self, delta: Point) -> None:
        x, y = self._mouse.position
        self._mouse.position = (round(x + delta.x), round(y + delta.y))

    def scroll(self, amount: int) -> None:
        if amount:
            self._mouse.scroll(0, amount)

    def type_text(self, text: str) -> None:
        self._keyboard.type(text)

    def press_enter(self) -> None:
        self._keyboard.press(self._keyboard_module.Key.enter)
        self._keyboard.release(self._keyboard_module.Key.enter)
