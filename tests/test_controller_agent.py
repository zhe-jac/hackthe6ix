from __future__ import annotations

import time
from concurrent.futures import Future

from gazemotion.actions.base import RecordingInputAdapter
from gazemotion.agent.agent import VoiceCommandAgent
from gazemotion.agent.intents import IntentExecutor, RecordingSystemAdapter
from gazemotion.agent.parser import RuleBasedIntentParser
from gazemotion.core.config import GestureSettings
from gazemotion.core.controller import InteractionController
from gazemotion.core.events import ControllerState, GestureEvent, GestureType, Point


class FakeDictation:
    def __init__(self, text: str) -> None:
        self.text = text

    def start(self) -> None:
        return

    def finish(self) -> Future[str]:
        result: Future[str] = Future()
        result.set_result(self.text)
        return result

    def cancel(self) -> None:
        return


def _event(kind: GestureType, timestamp: float = 0.0) -> GestureEvent:
    return GestureEvent(kind, timestamp, 0.9, Point(0.0, 0.0))


def _run_command(
    text: str,
) -> tuple[InteractionController, RecordingInputAdapter, RecordingSystemAdapter, list[str]]:
    input_adapter = RecordingInputAdapter()
    system_adapter = RecordingSystemAdapter()
    agent = VoiceCommandAgent(
        RuleBasedIntentParser(), IntentExecutor(input_adapter, system_adapter)
    )
    spoken: list[str] = []
    controller = InteractionController(
        input_adapter,
        (100, 100),
        GestureSettings(),
        dictation=FakeDictation(text),
        status=lambda _message: None,
        agent=agent,
        announce=spoken.append,
    )
    controller.on_gesture(_event(GestureType.DICTATION_TOGGLE))
    controller.on_gesture(_event(GestureType.DICTATION_TOGGLE, 1.0))
    assert controller.state == ControllerState.TRANSCRIBING
    controller.poll()
    assert controller.state == ControllerState.COMMANDING
    deadline = time.monotonic() + 5.0
    while controller.state == ControllerState.COMMANDING and time.monotonic() < deadline:
        controller.poll()
        time.sleep(0.01)
    controller.shutdown()
    return controller, input_adapter, system_adapter, spoken


def test_voice_command_opens_url_instead_of_typing() -> None:
    controller, input_adapter, system_adapter, spoken = _run_command("open github dot com")
    assert controller.state == ControllerState.PAUSED  # shutdown() parks the controller
    assert ("open_url", "github.com") in system_adapter.events
    assert not any(name == "type_text" for name, _ in input_adapter.events)
    assert any("github.com" in line for line in spoken)


def test_voice_dictation_still_types_through_agent() -> None:
    _controller, input_adapter, _system_adapter, _spoken = _run_command("hello world")
    assert ("type_text", "hello world") in input_adapter.events
    assert ("press_enter", None) in input_adapter.events


def test_voice_pause_command_pauses_controller() -> None:
    input_adapter = RecordingInputAdapter()
    system_adapter = RecordingSystemAdapter()
    agent = VoiceCommandAgent(
        RuleBasedIntentParser(), IntentExecutor(input_adapter, system_adapter)
    )
    controller = InteractionController(
        input_adapter,
        (100, 100),
        GestureSettings(),
        dictation=FakeDictation("stop listening"),
        status=lambda _message: None,
        agent=agent,
    )
    controller.on_gesture(_event(GestureType.DICTATION_TOGGLE))
    controller.on_gesture(_event(GestureType.DICTATION_TOGGLE, 1.0))
    controller.poll()
    deadline = time.monotonic() + 5.0
    while controller.state == ControllerState.COMMANDING and time.monotonic() < deadline:
        controller.poll()
        time.sleep(0.01)
    assert controller.state == ControllerState.PAUSED
    controller.shutdown()
