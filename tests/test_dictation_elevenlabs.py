from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("sounddevice")

from gazemotion.speech.dictation import ElevenLabsDictationService  # noqa: E402


def _service(transport) -> ElevenLabsDictationService:
    return ElevenLabsDictationService(
        api_key="test", sample_rate=16000, transport=transport
    )


def test_transcribe_sends_wav_and_returns_text() -> None:
    seen: list[Path] = []

    def transport(wav_path: Path) -> str:
        seen.append(wav_path)
        assert wav_path.exists()
        return "open notepad"

    service = _service(transport)
    audio = np.zeros(16000, dtype=np.float32)  # one second of silence
    assert service._transcribe(audio) == "open notepad"
    assert len(seen) == 1
    assert not seen[0].exists()  # recording is deleted after the request
    service.close()


def test_transcribe_skips_too_short_audio() -> None:
    def transport(_wav_path: Path) -> str:
        raise AssertionError("transport should not be called for short audio")

    service = _service(transport)
    assert service._transcribe(np.zeros(100, dtype=np.float32)) == ""
    service.close()
