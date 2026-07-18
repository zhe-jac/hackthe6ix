from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from gazemotion.actions.base import InputAdapter


class IntentKind(str, Enum):
    TYPE_TEXT = "type_text"
    SEARCH_WEB = "search_web"
    OPEN_URL = "open_url"
    OPEN_APP = "open_app"
    SCROLL = "scroll"
    PRESS_KEYS = "press_keys"
    PAUSE = "pause"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Intent:
    kind: IntentKind
    text: str = ""
    submit: bool = True
    query: str = ""
    url: str = ""
    app: str = ""
    amount: int = 0
    keys: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: dict) -> Intent:
        raw_kind = data.get("kind", "unknown")
        if isinstance(raw_kind, IntentKind):
            kind = raw_kind
        else:
            try:
                kind = IntentKind(str(raw_kind).lower())
            except ValueError:
                kind = IntentKind.UNKNOWN
        keys = data.get("keys") or ()
        if isinstance(keys, str):
            keys = tuple(part.strip() for part in keys.split("+") if part.strip())
        return cls(
            kind=kind,
            text=str(data.get("text", "")),
            submit=bool(data.get("submit", True)),
            query=str(data.get("query", "")),
            url=str(data.get("url", "")),
            app=str(data.get("app", "")),
            amount=int(data.get("amount", 0) or 0),
            keys=tuple(str(key).lower() for key in keys),
        )


class SystemAdapter(Protocol):
    """OS-level actions beyond raw pointer/keyboard events."""

    def open_url(self, url: str) -> None: ...

    def open_app(self, name: str) -> None: ...

    def press_keys(self, keys: tuple[str, ...]) -> None: ...


class RecordingSystemAdapter:
    """Safe adapter used by tests and `--dry-run`."""

    def __init__(self, announce: bool = False) -> None:
        self.events: list[tuple[str, object]] = []
        self.announce = announce

    def _record(self, name: str, value: object) -> None:
        self.events.append((name, value))
        if self.announce:
            print(f"[dry-run] {name}: {value}")

    def open_url(self, url: str) -> None:
        self._record("open_url", url)

    def open_app(self, name: str) -> None:
        self._record("open_app", name)

    def press_keys(self, keys: tuple[str, ...]) -> None:
        self._record("press_keys", keys)


_APP_ALIASES = {
    "notepad": "notepad",
    "calculator": "calc",
    "paint": "mspaint",
    "explorer": "explorer",
    "file explorer": "explorer",
    "terminal": "wt",
    "browser": None,  # opened through webbrowser instead
}


class DesktopSystemAdapter:
    """Launch URLs and applications on the local desktop."""

    def open_url(self, url: str) -> None:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)

    def open_app(self, name: str) -> None:
        normalized = name.strip().lower()
        target = _APP_ALIASES.get(normalized, normalized)
        if target is None:
            webbrowser.open("https://www.google.com")
            return
        if sys.platform == "win32":
            os.startfile(target)  # noqa: S606 - deliberate local app launch
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", target])
        else:
            subprocess.Popen([target])

    def press_keys(self, keys: tuple[str, ...]) -> None:
        from pynput import keyboard

        special = {
            "ctrl": keyboard.Key.ctrl,
            "alt": keyboard.Key.alt,
            "shift": keyboard.Key.shift,
            "cmd": keyboard.Key.cmd,
            "win": keyboard.Key.cmd,
            "enter": keyboard.Key.enter,
            "tab": keyboard.Key.tab,
            "escape": keyboard.Key.esc,
            "esc": keyboard.Key.esc,
            "backspace": keyboard.Key.backspace,
            "delete": keyboard.Key.delete,
            "space": keyboard.Key.space,
            "up": keyboard.Key.up,
            "down": keyboard.Key.down,
            "left": keyboard.Key.left,
            "right": keyboard.Key.right,
            "home": keyboard.Key.home,
            "end": keyboard.Key.end,
            "pageup": keyboard.Key.page_up,
            "pagedown": keyboard.Key.page_down,
        }
        controller = keyboard.Controller()
        resolved = [special.get(key, key) for key in keys]
        for key in resolved:
            controller.press(key)
        for key in reversed(resolved):
            controller.release(key)


class IntentExecutor:
    """Perform parsed intents through the input and system adapters."""

    def __init__(
        self,
        input_adapter: InputAdapter,
        system_adapter: SystemAdapter,
        scroll_step: int = 6,
    ) -> None:
        self.input = input_adapter
        self.system = system_adapter
        self.scroll_step = scroll_step

    def execute(self, intent: Intent) -> str:
        """Run one intent and return a short confirmation for feedback."""
        if intent.kind == IntentKind.TYPE_TEXT:
            if not intent.text:
                return "Nothing to type"
            self.input.type_text(intent.text)
            if intent.submit:
                self.input.press_enter()
            return f"Typed: {intent.text}"
        if intent.kind == IntentKind.SEARCH_WEB:
            query = intent.query or intent.text
            if not query:
                return "Search needs a query"
            self.system.open_url(
                "https://www.google.com/search?q=" + query.replace(" ", "+")
            )
            return f"Searching for {query}"
        if intent.kind == IntentKind.OPEN_URL:
            if not intent.url:
                return "No address to open"
            self.system.open_url(intent.url)
            return f"Opening {intent.url}"
        if intent.kind == IntentKind.OPEN_APP:
            if not intent.app:
                return "No application named"
            self.system.open_app(intent.app)
            return f"Opening {intent.app}"
        if intent.kind == IntentKind.SCROLL:
            amount = intent.amount or -self.scroll_step
            self.input.scroll(amount)
            return "Scrolling up" if amount > 0 else "Scrolling down"
        if intent.kind == IntentKind.PRESS_KEYS:
            if not intent.keys:
                return "No keys to press"
            self.system.press_keys(intent.keys)
            return "Pressed " + " ".join(intent.keys)
        if intent.kind == IntentKind.PAUSE:
            return "Pausing"
        return "Sorry, I did not understand that"
