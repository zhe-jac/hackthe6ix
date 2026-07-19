from __future__ import annotations

from chudvis.ui.window import close_window, window_is_open


class FakeCV2:
    WND_PROP_VISIBLE = 1

    class error(Exception):
        pass

    def __init__(self, visible: float = 1.0, raise_error: bool = False) -> None:
        self.visible = visible
        self.raise_error = raise_error
        self.destroyed: list[str] = []

    def getWindowProperty(self, _name: str, _property: int) -> float:
        if self.raise_error:
            raise self.error("window is gone")
        return self.visible

    def destroyWindow(self, name: str) -> None:
        if self.raise_error:
            raise self.error("window is gone")
        self.destroyed.append(name)


def test_closed_or_missing_window_is_not_open() -> None:
    assert window_is_open(FakeCV2(1.0), "dashboard") is True
    assert window_is_open(FakeCV2(0.0), "dashboard") is False
    assert window_is_open(FakeCV2(raise_error=True), "dashboard") is False


def test_close_window_tolerates_already_closed_window() -> None:
    cv2 = FakeCV2()
    close_window(cv2, "dashboard")
    assert cv2.destroyed == ["dashboard"]

    close_window(FakeCV2(raise_error=True), "dashboard")
