from __future__ import annotations

import json

import pytest

from gazemotion.agent.intents import Intent, IntentKind
from gazemotion.agent.parser import ParserError, RuleBasedIntentParser, _intents_from_reply


@pytest.fixture()
def parser() -> RuleBasedIntentParser:
    return RuleBasedIntentParser()


def _one(parser: RuleBasedIntentParser, text: str) -> Intent:
    intents = parser.parse(text)
    assert len(intents) == 1
    return intents[0]


def test_search_command(parser: RuleBasedIntentParser) -> None:
    intent = _one(parser, "Search the web for cat videos.")
    assert intent.kind == IntentKind.SEARCH_WEB
    assert intent.query == "cat videos"


def test_open_url_with_spoken_dot(parser: RuleBasedIntentParser) -> None:
    intent = _one(parser, "open youtube dot com")
    assert intent.kind == IntentKind.OPEN_URL
    assert intent.url == "youtube.com"


def test_open_app(parser: RuleBasedIntentParser) -> None:
    intent = _one(parser, "Please open notepad")
    assert intent.kind == IntentKind.OPEN_APP
    assert intent.app == "notepad"


def test_scroll_down_and_up(parser: RuleBasedIntentParser) -> None:
    assert _one(parser, "scroll down").amount < 0
    assert _one(parser, "scroll up").amount > 0
    assert _one(parser, "scroll down a lot").amount == -18


def test_hotkey_phrases(parser: RuleBasedIntentParser) -> None:
    intent = _one(parser, "select all")
    assert intent.kind == IntentKind.PRESS_KEYS
    assert intent.keys == ("ctrl", "a")


def test_press_named_key(parser: RuleBasedIntentParser) -> None:
    intent = _one(parser, "press enter")
    assert intent.kind == IntentKind.PRESS_KEYS
    assert intent.keys == ("enter",)


def test_pause_command(parser: RuleBasedIntentParser) -> None:
    assert _one(parser, "stop listening").kind == IntentKind.PAUSE
    assert _one(parser, "Pause.").kind == IntentKind.PAUSE


def test_explicit_type_does_not_submit(parser: RuleBasedIntentParser) -> None:
    intent = _one(parser, "type Hello there")
    assert intent.kind == IntentKind.TYPE_TEXT
    assert intent.text == "Hello there"
    assert intent.submit is False


def test_plain_dictation_submits(parser: RuleBasedIntentParser) -> None:
    intent = _one(parser, "See you at nine thirty")
    assert intent.kind == IntentKind.TYPE_TEXT
    assert intent.text == "See you at nine thirty"
    assert intent.submit is True


def test_empty_transcript(parser: RuleBasedIntentParser) -> None:
    assert parser.parse("   ") == []


def test_leading_fillers_do_not_break_commands(parser: RuleBasedIntentParser) -> None:
    intent = _one(parser, "Um, open hackthe6ix dot com")
    assert intent.kind == IntentKind.OPEN_URL
    assert intent.url == "hackthe6ix.com"
    hotkey = _one(parser, "okay, select all")
    assert hotkey.keys == ("ctrl", "a")


def test_filler_before_type_keeps_casing(parser: RuleBasedIntentParser) -> None:
    intent = _one(parser, "Okay, type See you at Nine")
    assert intent.kind == IntentKind.TYPE_TEXT
    assert intent.text == "See you at Nine"


def test_intents_from_reply_parses_fenced_json() -> None:
    reply = '```json\n{"intents": [{"kind": "search_web", "query": "ramen"}]}\n```'
    intents = _intents_from_reply(reply)
    assert intents == [Intent(kind=IntentKind.SEARCH_WEB, query="ramen")]


def test_intents_from_reply_rejects_non_json() -> None:
    with pytest.raises(ParserError):
        _intents_from_reply("I could not parse that")


def test_intent_from_dict_handles_unknown_kind_and_string_keys() -> None:
    intent = Intent.from_dict({"kind": "explode", "keys": "ctrl+shift+t"})
    assert intent.kind == IntentKind.UNKNOWN
    assert intent.keys == ("ctrl", "shift", "t")
    round_trip = Intent.from_dict(json.loads('{"kind": "scroll", "amount": -6}'))
    assert round_trip.amount == -6
