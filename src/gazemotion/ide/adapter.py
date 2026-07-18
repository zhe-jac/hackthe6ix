from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from gazemotion.ide.transport import IdeTransport


class IdeAdapter(Protocol):
    def navigate_change(self, direction: int) -> None: ...

    def scroll_editor(self, lines: int) -> None: ...

    def arm_selection(self, timeout_seconds: float) -> bool: ...

    def cancel_selection(self) -> None: ...

    def show_request(self, transcript: str) -> None: ...

    def submit_request(self) -> None: ...

    def cancel_request(self) -> None: ...

    def set_paused(self, paused: bool) -> None: ...

    def poll(self) -> None: ...


class SocketIdeAdapter:
    def __init__(self, transport: IdeTransport, status: Callable[[str], None] = print) -> None:
        self.transport = transport
        self.status = status

    def navigate_change(self, direction: int) -> None:
        self.transport.notify("review.navigate", {"direction": -1 if direction < 0 else 1})

    def scroll_editor(self, lines: int) -> None:
        self.transport.notify("editor.scroll", {"lines": lines}, continuous=True)

    def arm_selection(self, timeout_seconds: float) -> bool:
        if not self.transport.connected:
            return False
        return self.transport.notify(
            "selection.arm",
            {"timeoutMs": max(round(timeout_seconds * 1000), 1)},
        )

    def cancel_selection(self) -> None:
        self.transport.notify("selection.cancel")

    def show_request(self, transcript: str) -> None:
        self.transport.notify("request.preview", {"transcript": transcript})

    def submit_request(self) -> None:
        self.transport.notify("request.submit")

    def cancel_request(self) -> None:
        self.transport.notify("request.cancel")

    def set_paused(self, paused: bool) -> None:
        self.transport.notify("control.pause", {"paused": paused})

    def poll(self) -> None:
        for message in self.transport.poll():
            if message.get("method") != "bridge.status":
                continue
            params = message.get("params")
            if isinstance(params, dict) and isinstance(params.get("message"), str):
                self.status(params["message"])


class RecordingIdeAdapter:
    """Safe IDE adapter used by controller tests and simulations."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def _record(self, name: str, value: object = None) -> None:
        self.events.append((name, value))

    def navigate_change(self, direction: int) -> None:
        self._record("navigate_change", direction)

    def scroll_editor(self, lines: int) -> None:
        self._record("scroll_editor", lines)

    def arm_selection(self, timeout_seconds: float) -> bool:
        self._record("arm_selection", timeout_seconds)
        return True

    def cancel_selection(self) -> None:
        self._record("cancel_selection")

    def show_request(self, transcript: str) -> None:
        self._record("show_request", transcript)

    def submit_request(self) -> None:
        self._record("submit_request")

    def cancel_request(self) -> None:
        self._record("cancel_request")

    def set_paused(self, paused: bool) -> None:
        self._record("set_paused", paused)

    def poll(self) -> None:
        pass
