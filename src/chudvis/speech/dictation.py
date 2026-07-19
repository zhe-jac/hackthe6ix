from __future__ import annotations

import tempfile
import wave
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np


class DictationError(RuntimeError):
    pass


class LocalDictationService:
    """Capture a microphone session and transcribe it locally with Whisper."""

    def __init__(
        self,
        model_name: str = "tiny.en",
        sample_rate: int = 16000,
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        try:
            import sounddevice as sounddevice
        except (ImportError, OSError) as exc:
            raise DictationError(
                "Voice dependencies are unavailable; run `uv sync --extra voice`"
            ) from exc
        self._sounddevice = sounddevice
        self.model_name = model_name
        self.sample_rate = sample_rate
        self.device = device
        self.compute_type = compute_type
        self._chunks: list[np.ndarray] = []
        self._lock = Lock()
        self._stream: Any | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dictation")
        self._model: Any | None = None

    def _callback(self, input_data: Any, _frames: int, _time: Any, _status: Any) -> None:
        with self._lock:
            self._chunks.append(np.asarray(input_data[:, 0], dtype=np.float32).copy())

    def start(self) -> None:
        if self._stream is not None:
            raise DictationError("Dictation is already active")
        with self._lock:
            self._chunks.clear()
        try:
            self._stream = self._sounddevice.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise DictationError(f"Could not start microphone capture: {exc}") from exc

    def _stop_capture(self) -> np.ndarray:
        if self._stream is None:
            raise DictationError("Dictation is not active")
        stream = self._stream
        self._stream = None
        stream.stop()
        stream.close()
        with self._lock:
            if not self._chunks:
                return np.asarray([], dtype=np.float32)
            return np.concatenate(self._chunks)

    def finish(self) -> Future[str]:
        audio = self._stop_capture()
        return self._executor.submit(self._transcribe, audio)

    def cancel(self) -> None:
        if self._stream is not None:
            try:
                self._stop_capture()
            except Exception:
                self._stream = None

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise DictationError(
                    "faster-whisper is not installed; run `uv sync --extra voice`"
                ) from exc
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    def _transcribe(self, audio: np.ndarray) -> str:
        if audio.size < self.sample_rate // 4:
            return ""
        clipped = np.clip(audio, -1.0, 1.0)
        pcm = (clipped * 32767).astype(np.int16)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporary:
                temp_path = Path(temporary.name)
            with wave.open(str(temp_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(pcm.tobytes())
            segments, _info = self._get_model().transcribe(
                str(temp_path),
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            return " ".join(segment.text.strip() for segment in segments).strip()
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def close(self) -> None:
        self.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)
