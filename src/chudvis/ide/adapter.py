from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from chudvis.ide.transport import IdeTransport
from chudvis.speech.realtime_voice import VoiceState

BridgeMessage = dict[str, object]


class IdeAdapter(Protocol):
    @property
    def connected(self) -> bool: ...

    def navigate_change(self, direction: int) -> None: ...

    def scroll_editor(self, lines: int) -> None: ...

    def arm_selection(self, timeout_seconds: float) -> bool: ...

    def cancel_selection(self) -> None: ...

    def show_request(self, transcript: str) -> None: ...

    def submit_request(self) -> None: ...

    def cancel_request(self) -> None: ...

    def set_paused(self, paused: bool) -> None: ...

    def runtime_ready(self, detail: str) -> None: ...

    def voice_state(
        self,
        state: VoiceState,
        request_id: str | None = None,
        detail: str = "",
    ) -> None: ...

    def voice_level(self, level: float, dbfs: float) -> None: ...

    def voice_partial(self, request_id: str, text: str) -> None: ...

    def voice_request(self, request_id: str, transcript: str) -> None: ...

    def approve_edit(self, request_id: str) -> None: ...

    def cancel_edit(self, request_id: str) -> None: ...

    def diagnostic_event(
        self,
        category: str,
        name: str,
        data: object | None = None,
        request_id: str | None = None,
    ) -> None: ...

    def poll(self) -> list[BridgeMessage]: ...


class SocketIdeAdapter:
    def __init__(self, transport: IdeTransport, status: Callable[[str], None] = print) -> None:
        self.transport = transport
        self.status = status

    @property
    def connected(self) -> bool:
        return self.transport.connected

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

    def runtime_ready(self, detail: str) -> None:
        self.transport.notify("runtime.ready", {"message": detail[:500]})

    def voice_state(
        self,
        state: VoiceState,
        request_id: str | None = None,
        detail: str = "",
    ) -> None:
        params: dict[str, object] = {"state": state.value}
        if request_id is not None:
            params["requestId"] = request_id
        if detail:
            params["detail"] = detail[:500]
        self.transport.notify("voice.state", params)

    def voice_level(self, level: float, dbfs: float) -> None:
        self.transport.notify(
            "voice.level",
            {
                "level": round(max(0.0, min(1.0, level)), 3),
                "dbfs": round(max(-100.0, min(0.0, dbfs)), 1),
            },
            continuous=True,
            low_priority=True,
        )

    def voice_partial(self, request_id: str, text: str) -> None:
        self.transport.notify(
            "voice.partial",
            {"requestId": request_id, "text": text[:16_000]},
            continuous=True,
        )

    def voice_request(self, request_id: str, transcript: str) -> None:
        self.transport.notify(
            "voice.request",
            {"requestId": request_id, "transcript": transcript[:16_000]},
        )

    def approve_edit(self, request_id: str) -> None:
        self.transport.notify("edit.approve", {"requestId": request_id})

    def cancel_edit(self, request_id: str) -> None:
        self.transport.notify("edit.cancel", {"requestId": request_id})

    def diagnostic_event(
        self,
        category: str,
        name: str,
        data: object | None = None,
        request_id: str | None = None,
    ) -> None:
        params: dict[str, object] = {"category": category[:80], "name": name[:160]}
        if data is not None:
            params["data"] = data
        if request_id is not None:
            params["requestId"] = request_id[:100]
        # Diagnostics must never crowd functional gestures out of the bridge queue.
        self.transport.notify("diagnostic.event", params, continuous=True, low_priority=True)

    def poll(self) -> list[BridgeMessage]:
        inbound: list[BridgeMessage] = []
        for message in self.transport.poll():
            if message.get("method") != "bridge.status":
                inbound.append(message)
                continue
            params = message.get("params")
            if isinstance(params, dict) and isinstance(params.get("message"), str):
                self.status(params["message"])
        return inbound


class RecordingIdeAdapter:
    """Safe IDE adapter used by controller tests and simulations."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.diagnostics: list[dict[str, object | None]] = []
        self.inbound: list[BridgeMessage] = []

    def _record(self, name: str, value: object = None) -> None:
        self.events.append((name, value))

    @property
    def connected(self) -> bool:
        return True

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

    def runtime_ready(self, detail: str) -> None:
        self._record("runtime_ready", detail)

    def voice_state(
        self,
        state: VoiceState,
        request_id: str | None = None,
        detail: str = "",
    ) -> None:
        self._record("voice_state", (state, request_id, detail))

    def voice_level(self, level: float, dbfs: float) -> None:
        self._record("voice_level", (level, dbfs))

    def voice_partial(self, request_id: str, text: str) -> None:
        self._record("voice_partial", (request_id, text))

    def voice_request(self, request_id: str, transcript: str) -> None:
        self._record("voice_request", (request_id, transcript))

    def approve_edit(self, request_id: str) -> None:
        self._record("approve_edit", request_id)

    def cancel_edit(self, request_id: str) -> None:
        self._record("cancel_edit", request_id)

    def diagnostic_event(
        self,
        category: str,
        name: str,
        data: object | None = None,
        request_id: str | None = None,
    ) -> None:
        self.diagnostics.append(
            {"category": category, "name": name, "data": data, "request_id": request_id}
        )

    def poll(self) -> list[BridgeMessage]:
        messages = self.inbound
        self.inbound = []
        return messages
