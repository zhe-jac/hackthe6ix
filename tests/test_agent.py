from __future__ import annotations

from gazemotion.actions.base import RecordingInputAdapter
from gazemotion.agent.agent import VoiceCommandAgent
from gazemotion.agent.intents import (
    Intent,
    IntentExecutor,
    IntentKind,
    RecordingSystemAdapter,
)
from gazemotion.agent.parser import ParserError, RuleBasedIntentParser


def _executor() -> tuple[IntentExecutor, RecordingInputAdapter, RecordingSystemAdapter]:
    input_adapter = RecordingInputAdapter()
    system_adapter = RecordingSystemAdapter()
    return IntentExecutor(input_adapter, system_adapter), input_adapter, system_adapter


def test_execute_search_builds_query_url() -> None:
    executor, _input_adapter, system_adapter = _executor()
    message = executor.execute(Intent(kind=IntentKind.SEARCH_WEB, query="cat videos"))
    assert system_adapter.events == [
        ("open_url", "https://www.google.com/search?q=cat+videos")
    ]
    assert "cat videos" in message


def test_execute_type_text_with_submit() -> None:
    executor, input_adapter, _system_adapter = _executor()
    executor.execute(Intent(kind=IntentKind.TYPE_TEXT, text="hi", submit=True))
    assert ("type_text", "hi") in input_adapter.events
    assert ("press_enter", None) in input_adapter.events


def test_execute_type_text_without_submit() -> None:
    executor, input_adapter, _system_adapter = _executor()
    executor.execute(Intent(kind=IntentKind.TYPE_TEXT, text="hi", submit=False))
    assert ("type_text", "hi") in input_adapter.events
    assert ("press_enter", None) not in input_adapter.events


def test_execute_scroll_defaults_down() -> None:
    executor, input_adapter, _system_adapter = _executor()
    executor.execute(Intent(kind=IntentKind.SCROLL))
    assert input_adapter.events == [("scroll", -6)]


def test_agent_runs_all_intents_and_reports() -> None:
    executor, _input_adapter, system_adapter = _executor()
    agent = VoiceCommandAgent(RuleBasedIntentParser(), executor)
    result = agent.handle("open github dot com")
    assert system_adapter.events == [("open_url", "github.com")]
    assert "github.com" in result.spoken
    assert result.used_fallback is False


def test_agent_pause_intent_sets_flag_without_executing() -> None:
    executor, input_adapter, system_adapter = _executor()
    agent = VoiceCommandAgent(RuleBasedIntentParser(), executor)
    result = agent.handle("stop listening")
    assert result.pause_requested is True
    assert input_adapter.events == []
    assert system_adapter.events == []


class ExplodingParser:
    def parse(self, transcript: str) -> list[Intent]:
        raise ParserError("cloud is down")


def test_agent_falls_back_to_rules_when_parser_fails() -> None:
    executor, input_adapter, _system_adapter = _executor()
    agent = VoiceCommandAgent(ExplodingParser(), executor)
    result = agent.handle("hello world")
    assert result.used_fallback is True
    assert ("type_text", "hello world") in input_adapter.events


def test_agent_empty_transcript() -> None:
    executor, input_adapter, _system_adapter = _executor()
    agent = VoiceCommandAgent(RuleBasedIntentParser(), executor)
    result = agent.handle("   ")
    assert result.spoken == "No speech detected"
    assert input_adapter.events == []
