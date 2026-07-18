from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

from gazemotion.core.config import SpeechOutputSettings


class Speaker:
    """No-op speaker used when spoken feedback is unavailable."""

    def speak(self, text: str) -> None:  # noqa: ARG002 - interface parity
        return

    def close(self) -> None:
        return


class ElevenLabsSpeaker(Speaker):
    """Speak short confirmations through the ElevenLabs text-to-speech API.

    Audio is requested as raw PCM so it can be played directly through the
    existing sounddevice dependency, and synthesis runs on a worker thread so
    the camera loop never blocks. Repeated identical messages inside a short
    window are dropped to avoid chatter.
    """

    def __init__(
        self,
        settings: SpeechOutputSettings,
        api_key: str,
        transport: Callable[[str], bytes] | None = None,
    ) -> None:
        self.settings = settings
        self.api_key = api_key
        self._transport = transport or self._fetch_audio
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-out")
        self._last_text = ""
        self._last_at = 0.0
        self._failed = False

    def _fetch_audio(self, text: str) -> bytes:
        import requests

        response = requests.post(
            "https://api.elevenlabs.io/v1/text-to-speech/"
            f"{self.settings.voice_id}?output_format={self.settings.output_format}",
            json={"text": text, "model_id": self.settings.model_id},
            headers={"xi-api-key": self.api_key, "Content-Type": "application/json"},
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        return response.content

    def _play(self, text: str) -> None:
        try:
            audio = self._transport(text)
            import numpy as np
            import sounddevice

            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            sounddevice.play(samples, samplerate=self.settings.sample_rate)
            sounddevice.wait()
        except Exception as exc:
            if not self._failed:
                print(f"Spoken feedback failed; continuing silently: {exc}")
            self._failed = True

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text or self._failed:
            return
        now = monotonic()
        if (
            text == self._last_text
            and now - self._last_at < self.settings.duplicate_window_seconds
        ):
            return
        self._last_text = text
        self._last_at = now
        self._executor.submit(self._play, text)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def build_speaker(settings: SpeechOutputSettings) -> tuple[Speaker, str]:
    """Create the configured speaker and describe the choice for startup logs."""
    if not settings.enabled:
        return Speaker(), "disabled"
    api_key = os.environ.get(settings.api_key_env, "")
    if not api_key:
        return Speaker(), f"disabled ({settings.api_key_env} is not set)"
    try:
        import sounddevice  # noqa: F401
    except (ImportError, OSError):
        return Speaker(), "disabled (sounddevice unavailable; run `uv sync --extra voice`)"
    return ElevenLabsSpeaker(settings, api_key), f"ElevenLabs voice {settings.voice_id}"
