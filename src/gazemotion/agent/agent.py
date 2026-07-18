from __future__ import annotations

import os
from dataclasses import dataclass, field

from gazemotion.agent.intents import Intent, IntentExecutor, IntentKind
from gazemotion.agent.parser import (
    BackboardIntentParser,
    IntentParser,
    OpenAICompatibleIntentParser,
    ParserError,
    RuleBasedIntentParser,
)
from gazemotion.core.config import AgentSettings


@dataclass(slots=True)
class AgentResult:
    spoken: str = ""
    pause_requested: bool = False
    intents: list[Intent] = field(default_factory=list)
    used_fallback: bool = False


def build_parser(settings: AgentSettings) -> tuple[IntentParser, str]:
    """Choose the intent parser and describe the choice for startup logs."""
    if settings.provider == "backboard":
        api_key = os.environ.get(settings.api_key_env, "")
        if api_key:
            return (
                BackboardIntentParser(settings, api_key),
                f"Backboard ({settings.llm_provider}/{settings.model_name})",
            )
        return (
            RuleBasedIntentParser(),
            f"offline rules ({settings.api_key_env} is not set)",
        )
    if settings.provider == "openai-compatible":
        api_key = os.environ.get(settings.openai_api_key_env, "unused")
        return (
            OpenAICompatibleIntentParser(settings, api_key),
            f"local model at {settings.openai_base_url}",
        )
    return RuleBasedIntentParser(), "offline rules"


class VoiceCommandAgent:
    """Turn a finished dictation transcript into executed desktop intents."""

    def __init__(self, parser: IntentParser, executor: IntentExecutor) -> None:
        self.parser = parser
        self.executor = executor
        self.fallback = RuleBasedIntentParser()

    def handle(self, transcript: str) -> AgentResult:
        transcript = transcript.strip()
        if not transcript:
            return AgentResult(spoken="No speech detected")
        used_fallback = False
        try:
            intents = self.parser.parse(transcript)
        except ParserError:
            intents = self.fallback.parse(transcript)
            used_fallback = True
        if not intents:
            return AgentResult(spoken="No speech detected", used_fallback=used_fallback)

        confirmations: list[str] = []
        pause_requested = False
        for intent in intents:
            if intent.kind == IntentKind.PAUSE:
                pause_requested = True
                confirmations.append("Pausing")
                continue
            confirmations.append(self.executor.execute(intent))
        return AgentResult(
            spoken="; ".join(part for part in confirmations if part),
            pause_requested=pause_requested,
            intents=list(intents),
            used_fallback=used_fallback,
        )
