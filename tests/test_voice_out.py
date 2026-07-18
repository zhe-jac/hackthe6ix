from __future__ import annotations

import time

from gazemotion.core.config import SpeechOutputSettings
from gazemotion.speech.voice_out import ElevenLabsSpeaker, Speaker, build_speaker


def _speaker(**overrides) -> tuple[ElevenLabsSpeaker, list[str]]:
    settings = SpeechOutputSettings(**overrides)
    speaker = ElevenLabsSpeaker(settings, api_key="test", transport=lambda text: b"")
    played: list[str] = []
    speaker._play = played.append  # bypass audio playback in tests
    return speaker, played


def _drain(speaker: ElevenLabsSpeaker) -> None:
    speaker._executor.submit(lambda: None).result(timeout=2.0)


def test_speak_deduplicates_identical_messages() -> None:
    speaker, played = _speaker(duplicate_window_seconds=5.0)
    speaker.speak("Click")
    speaker.speak("Click")
    speaker.speak("Scrolling down")
    _drain(speaker)
    assert played == ["Click", "Scrolling down"]
    speaker.close()


def test_speak_allows_repeat_after_window() -> None:
    speaker, played = _speaker(duplicate_window_seconds=0.05)
    speaker.speak("Click")
    time.sleep(0.06)
    speaker.speak("Click")
    _drain(speaker)
    assert played == ["Click", "Click"]
    speaker.close()


def test_speak_ignores_empty_text() -> None:
    speaker, played = _speaker()
    speaker.speak("   ")
    _drain(speaker)
    assert played == []
    speaker.close()


def test_build_speaker_without_key_is_silent(monkeypatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    speaker, label = build_speaker(SpeechOutputSettings(enabled=True))
    assert type(speaker) is Speaker
    assert "not set" in label


def test_build_speaker_disabled() -> None:
    speaker, label = build_speaker(SpeechOutputSettings(enabled=False))
    assert type(speaker) is Speaker
    assert label == "disabled"
