from __future__ import annotations

import json
import re
from typing import Any, Protocol

from gazemotion.agent.intents import Intent, IntentKind
from gazemotion.core.config import AgentSettings


class ParserError(RuntimeError):
    pass


class IntentParser(Protocol):
    def parse(self, transcript: str) -> list[Intent]: ...


_HOTKEY_PHRASES: dict[str, tuple[str, ...]] = {
    "select all": ("ctrl", "a"),
    "copy": ("ctrl", "c"),
    "paste": ("ctrl", "v"),
    "cut": ("ctrl", "x"),
    "undo": ("ctrl", "z"),
    "redo": ("ctrl", "y"),
    "save": ("ctrl", "s"),
    "delete last word": ("ctrl", "backspace"),
    "new tab": ("ctrl", "t"),
    "close tab": ("ctrl", "w"),
    "next tab": ("ctrl", "tab"),
    "switch window": ("alt", "tab"),
    "go back": ("alt", "left"),
    "go forward": ("alt", "right"),
    "refresh": ("f5",),
    "new line": ("enter",),
}

_KEY_NAMES = {
    "enter", "tab", "escape", "esc", "space", "backspace", "delete",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
}

_SEARCH_RE = re.compile(
    r"^(?:please\s+)?(?:search(?:\s+the\s+web)?(?:\s+for)?|google|look\s+up)\s+(.+)$"
)
_OPEN_RE = re.compile(r"^(?:please\s+)?(?:open|go\s+to|visit|navigate\s+to|launch|start)\s+(.+)$")
_SCROLL_RE = re.compile(r"^(?:please\s+)?scroll\s+(down|up)(\s+(?:more|a\s+lot|faster))?$")
_PRESS_RE = re.compile(r"^(?:please\s+)?(?:press|hit)\s+(.+)$")
_TYPE_RE = re.compile(r"^(?:please\s+)?(?:type|write|say)\s+(.+)$")
_PAUSE_RE = re.compile(r"^(?:please\s+)?(?:pause|stop)(\s+(?:tracking|listening|controlling))?$")


_FILLER_RE = re.compile(r"^(?:um+|uh+|okay|ok|so|hey|well)[,.\s]+", re.IGNORECASE)


def _strip_fillers(text: str) -> str:
    while True:
        stripped = _FILLER_RE.sub("", text.lstrip(), count=1)
        if stripped == text:
            return text
        text = stripped


def _normalize(transcript: str) -> str:
    text = _strip_fillers(transcript.strip()).strip(".!?,").strip().lower()
    text = re.sub(r"\s+dot\s+(com|org|net|ca|io|dev)\b", r".\1", text)
    return re.sub(r"\s+", " ", text)


def _looks_like_url(target: str) -> bool:
    return target.startswith(("http://", "https://", "www.")) or bool(
        re.search(r"\.[a-z]{2,6}(/|$)", target)
    )


def _is_key_name(key: str) -> bool:
    return key in _KEY_NAMES or key in ("ctrl", "alt", "shift") or len(key) == 1


class RuleBasedIntentParser:
    """Offline transcript-to-intent grammar.

    Doubles as the labeling function for the Freesolo post-training dataset, so a
    small fine-tuned model can learn (and generalize past) exactly this behavior.
    """

    def parse(self, transcript: str) -> list[Intent]:
        original = transcript.strip()
        if not original:
            return []
        text = _normalize(original)

        if _PAUSE_RE.match(text):
            return [Intent(kind=IntentKind.PAUSE)]
        if text in _HOTKEY_PHRASES:
            return [Intent(kind=IntentKind.PRESS_KEYS, keys=_HOTKEY_PHRASES[text])]
        match = _SCROLL_RE.match(text)
        if match:
            step = 6 * (3 if match.group(2) else 1)
            amount = step if match.group(1) == "up" else -step
            return [Intent(kind=IntentKind.SCROLL, amount=amount)]
        match = _PRESS_RE.match(text)
        if match:
            keys = tuple(part for part in re.split(r"[\s+]+", match.group(1)) if part)
            if keys and all(_is_key_name(key) for key in keys):
                return [Intent(kind=IntentKind.PRESS_KEYS, keys=keys)]
        match = _SEARCH_RE.match(text)
        if match:
            return [Intent(kind=IntentKind.SEARCH_WEB, query=match.group(1))]
        match = _OPEN_RE.match(text)
        if match:
            target = match.group(1)
            if _looks_like_url(target):
                return [Intent(kind=IntentKind.OPEN_URL, url=target.replace(" ", ""))]
            return [Intent(kind=IntentKind.OPEN_APP, app=target)]
        match = _TYPE_RE.match(text)
        if match:
            stripped = _strip_fillers(original)
            verb_match = _TYPE_RE.match(stripped.lower())
            spoken = stripped[verb_match.start(1):].strip() if verb_match else match.group(1)
            return [Intent(kind=IntentKind.TYPE_TEXT, text=spoken, submit=False)]
        return [Intent(kind=IntentKind.TYPE_TEXT, text=original, submit=True)]


_SYSTEM_PROMPT = """\
You convert one voice transcript from a hands-free desktop controller into JSON intents.
Reply with ONLY a JSON object: {"intents": [ ... ]}. Each intent has "kind" plus fields:
- {"kind": "type_text", "text": str, "submit": bool}  # dictated text; submit=true presses Enter
- {"kind": "search_web", "query": str}
- {"kind": "open_url", "url": str}
- {"kind": "open_app", "app": str}
- {"kind": "scroll", "amount": int}  # positive scrolls up, negative down, magnitude ~6-18
- {"kind": "press_keys", "keys": ["ctrl", "c"]}
- {"kind": "pause"}
If the transcript is a command, emit the command intent(s) in order; otherwise treat it as
dictation (type_text with submit true). Never invent destructive shortcuts such as alt+f4.
"""


def _extract_json(payload: str) -> dict[str, Any]:
    text = payload.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ParserError(f"No JSON object in model reply: {payload[:120]!r}")
    return json.loads(text[start : end + 1])


def _intents_from_reply(reply: str) -> list[Intent]:
    data = _extract_json(reply)
    raw_intents = data.get("intents", [])
    if not isinstance(raw_intents, list):
        raise ParserError("Model reply is missing an 'intents' list")
    return [Intent.from_dict(item) for item in raw_intents if isinstance(item, dict)]


class BackboardIntentParser:
    """Parse transcripts with an LLM through the Backboard.io unified API.

    Keeps one Backboard thread per session so the assistant retains conversational
    context, and lets Backboard memory personalize behavior across sessions.
    """

    def __init__(self, settings: AgentSettings, api_key: str) -> None:
        self.settings = settings
        self.api_key = api_key
        self.thread_id: str | None = None

    def parse(self, transcript: str) -> list[Intent]:
        import requests

        payload: dict[str, Any] = {
            "content": transcript,
            "llm_provider": self.settings.llm_provider,
            "model_name": self.settings.model_name,
            "system_prompt": _SYSTEM_PROMPT,
            "memory": self.settings.memory,
            "stream": False,
            "json_output": True,
        }
        if self.thread_id:
            payload["thread_id"] = self.thread_id
        try:
            response = requests.post(
                f"{self.settings.base_url.rstrip('/')}/threads/messages",
                json=payload,
                headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise ParserError(f"Backboard request failed: {exc}") from exc
        self.thread_id = body.get("thread_id", self.thread_id)
        reply = body.get("message") or body.get("content") or ""
        return _intents_from_reply(reply)


class OpenAICompatibleIntentParser:
    """Parse transcripts with any OpenAI-compatible endpoint.

    This is the serving hook for the Freesolo post-trained intent model: point
    `agent.openai_base_url` at wherever the fine-tuned model is hosted.
    """

    def __init__(self, settings: AgentSettings, api_key: str) -> None:
        self.settings = settings
        self.api_key = api_key

    def parse(self, transcript: str) -> list[Intent]:
        import requests

        try:
            response = requests.post(
                f"{self.settings.openai_base_url.rstrip('/')}/chat/completions",
                json={
                    "model": self.settings.openai_model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": transcript},
                    ],
                    "temperature": 0,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            reply = body["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ParserError(f"Intent model request failed: {exc}") from exc
        return _intents_from_reply(reply)
