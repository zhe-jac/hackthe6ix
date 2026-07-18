"""Generate a post-training dataset for the GazeMotion intent model.

Synthesizes voice-transcript style utterances, labels them with the offline
rule grammar, and writes chat-format JSONL ready for Freesolo SFT. Run with:

    uv run python training/freesolo/generate_dataset.py

Outputs train.jsonl and eval.jsonl next to this script.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict
from pathlib import Path

from gazemotion.agent.parser import _SYSTEM_PROMPT, RuleBasedIntentParser

SEARCH_TOPICS = [
    "cat videos", "toronto weather", "python dataclasses", "hackathon schedule",
    "best ramen near me", "eye tracking research", "mediapipe hand landmarks",
    "cheap flights to tokyo", "how to tie a tie", "raptors score",
]
URLS = [
    "github.com", "youtube.com", "google.com", "hackthe6ix.com", "wikipedia.org",
    "devpost.com", "reddit.com", "news.ycombinator.com",
]
APPS = ["notepad", "calculator", "paint", "file explorer", "terminal", "browser"]
DICTATION = [
    "Hello, how are you doing today?",
    "See you at the demo at nine thirty.",
    "The quick brown fox jumps over the lazy dog.",
    "Thanks for reviewing our project!",
    "Meeting notes from the wellness sync.",
    "I will be five minutes late.",
]
HOTKEY_PHRASES = [
    "select all", "copy", "paste", "cut", "undo", "redo", "save",
    "delete last word", "new tab", "close tab", "next tab", "switch window",
    "go back", "go forward", "refresh", "new line",
]
PRESS_TARGETS = ["enter", "tab", "escape", "space", "backspace", "down", "up"]
FILLERS = ["", "please ", "um, ", "okay, ", "uh, "]

# Natural phrasings the rule grammar cannot parse, hand-labeled. These are the
# reason to post-train: the model learns to generalize where the regexes stop.
HARD_EXAMPLES: list[tuple[str, list[dict]]] = [
    ("can you pull up youtube dot com for me", [{"kind": "open_url", "url": "youtube.com"}]),
    ("take me to the github website", [{"kind": "open_url", "url": "github.com"}]),
    ("i want to see hackthe6ix dot com", [{"kind": "open_url", "url": "hackthe6ix.com"}]),
    ("bring up the calculator", [{"kind": "open_app", "app": "calculator"}]),
    ("can you get notepad open", [{"kind": "open_app", "app": "notepad"}]),
    ("fire up the terminal for me", [{"kind": "open_app", "app": "terminal"}]),
    ("make the page go down", [{"kind": "scroll", "amount": -6}]),
    ("move the page up a bit", [{"kind": "scroll", "amount": 6}]),
    ("keep going down the page", [{"kind": "scroll", "amount": -6}]),
    ("show me more of this page", [{"kind": "scroll", "amount": -6}]),
    (
        "find me some cheap flights to tokyo",
        [{"kind": "search_web", "query": "cheap flights to tokyo"}],
    ),
    (
        "i want to know the weather in toronto",
        [{"kind": "search_web", "query": "weather in toronto"}],
    ),
    (
        "look for eye tracking research papers",
        [{"kind": "search_web", "query": "eye tracking research papers"}],
    ),
    (
        "what is the raptors score right now",
        [{"kind": "search_web", "query": "raptors score right now"}],
    ),
    ("get rid of that last word", [{"kind": "press_keys", "keys": ["ctrl", "backspace"]}]),
    ("highlight everything", [{"kind": "press_keys", "keys": ["ctrl", "a"]}]),
    ("put that on the clipboard", [{"kind": "press_keys", "keys": ["ctrl", "c"]}]),
    ("take me back a page", [{"kind": "press_keys", "keys": ["alt", "left"]}]),
    ("reload this page", [{"kind": "press_keys", "keys": ["f5"]}]),
    ("hit the enter key for me", [{"kind": "press_keys", "keys": ["enter"]}]),
    ("give me a fresh tab", [{"kind": "press_keys", "keys": ["ctrl", "t"]}]),
    ("get me out of this tab", [{"kind": "press_keys", "keys": ["ctrl", "w"]}]),
    ("hold on stop everything", [{"kind": "pause"}]),
    ("that's enough for now, take a break", [{"kind": "pause"}]),
    ("quit listening to me", [{"kind": "pause"}]),
    (
        "write down hello team, the demo starts soon",
        [{"kind": "type_text", "text": "hello team, the demo starts soon", "submit": False}],
    ),
    (
        "enter my name is jacob and send it",
        [{"kind": "type_text", "text": "my name is jacob", "submit": True}],
    ),
    (
        "search for ramen near me and then scroll down",
        [{"kind": "search_web", "query": "ramen near me"}, {"kind": "scroll", "amount": -6}],
    ),
    (
        "open google dot com and press tab",
        [{"kind": "open_url", "url": "google.com"}, {"kind": "press_keys", "keys": ["tab"]}],
    ),
]


def utterances() -> list[str]:
    lines: list[str] = []
    for topic in SEARCH_TOPICS:
        for verb in ("search for", "search the web for", "google", "look up"):
            lines.append(f"{verb} {topic}")
    for url in URLS:
        for verb in ("open", "go to", "visit", "navigate to"):
            lines.append(f"{verb} {url}")
        lines.append("open " + url.replace(".", " dot "))
    for app in APPS:
        for verb in ("open", "launch", "start"):
            lines.append(f"{verb} {app}")
    for direction in ("down", "up"):
        lines.append(f"scroll {direction}")
        lines.append(f"scroll {direction} a lot")
    lines.extend(HOTKEY_PHRASES)
    for key in PRESS_TARGETS:
        lines.append(f"press {key}")
        lines.append(f"hit {key}")
    lines.extend(["pause", "stop listening", "pause tracking", "stop"])
    for text in DICTATION:
        lines.append(text)
        lines.append(f"type {text}")
    return lines


def _example(spoken: str, label: dict, source: str) -> dict:
    return {
        "source": source,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": spoken},
            {"role": "assistant", "content": json.dumps(label)},
        ],
    }


def build_examples(seed: int = 6) -> tuple[list[dict], list[dict]]:
    """Return (template examples labeled by the rule grammar, hand-labeled hard ones)."""
    random.seed(seed)
    parser = RuleBasedIntentParser()
    template = []
    for line in utterances():
        filler = random.choice(FILLERS)
        spoken = (filler + line).strip()
        if random.random() < 0.5:
            spoken = spoken[0].upper() + spoken[1:] + random.choice([".", "", "?", ""])
        intents = parser.parse(spoken)
        label = {"intents": [_clean(asdict(intent)) for intent in intents]}
        template.append(_example(spoken, label, "template"))
    hard = [
        _example(spoken, {"intents": intents}, "hard")
        for spoken, intents in HARD_EXAMPLES
    ]
    random.shuffle(template)
    random.shuffle(hard)
    return template, hard


def _clean(data: dict) -> dict:
    kind = data.pop("kind")
    cleaned = {"kind": kind.value if hasattr(kind, "value") else str(kind)}
    for key, value in data.items():
        if key == "submit":
            # submit stays explicit (even when False) so the model never
            # has to guess the default for dictated text.
            if cleaned["kind"] == "type_text":
                cleaned[key] = bool(value)
            continue
        if value in ("", 0, (), [], None):
            continue
        cleaned[key] = list(value) if isinstance(value, tuple) else value
    return cleaned


def main() -> None:
    out_dir = Path(__file__).parent
    template, hard = build_examples()
    template_split = max(len(template) // 10, 1)
    hard_split = max(len(hard) // 3, 1)
    eval_set = template[:template_split] + hard[:hard_split]
    train_set = template[template_split:] + hard[hard_split:]
    for name, rows in (("train.jsonl", train_set), ("eval.jsonl", eval_set)):
        path = out_dir / name
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        hard_count = sum(1 for row in rows if row["source"] == "hard")
        print(
            f"Wrote {len(rows)} examples to {path} "
            f"({len(rows) - hard_count} template, {hard_count} hard)"
        )


if __name__ == "__main__":
    main()
