from __future__ import annotations

import base64
import json
import os
import queue
import threading
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from time import monotonic
from typing import Any, Protocol, cast
from urllib.parse import quote, urlencode

from chudvis.core.config import VoiceSettings
from chudvis.speech.wake_word import WakeWordDetector


class VoiceState(str, Enum):
    READY = "ready"
    CONNECTING = "connecting"
    LISTENING = "listening"
    UNDERSTANDING = "understanding"
    EDITING = "editing"
    SPEAKING = "speaking"
    ERROR = "error"
    PAUSED = "paused"


class VoiceEventType(str, Enum):
    STATE = "state"
    PARTIAL = "partial"
    REQUEST = "request"


@dataclass(frozen=True, slots=True)
class VoiceEvent:
    type: VoiceEventType
    request_id: str | None = None
    state: VoiceState | None = None
    text: str = ""
    detail: str = ""


class RealtimeSttTransport(Protocol):
    def connect(self) -> None: ...

    def send_audio(self, pcm: bytes, *, commit: bool = False) -> None: ...

    def receive(self, timeout_seconds: float) -> dict[str, object] | None: ...

    def close(self) -> None: ...


class TtsSpeaker(Protocol):
    def speak(self, text: str, cancelled: threading.Event) -> None: ...


class AudioInputStream(Protocol):
    def start(self) -> object: ...

    def stop(self) -> object: ...

    def close(self) -> object: ...


class VoiceSessionService(Protocol):
    @property
    def state(self) -> VoiceState: ...

    @property
    def request_id(self) -> str | None: ...

    def start(self) -> None: ...

    def poll(self, max_events: int = 64) -> list[VoiceEvent]: ...

    def cancel(self, request_id: str | None = None) -> bool: ...

    def complete(self, request_id: str, status: str, spoken_summary: str = "") -> bool: ...

    def set_paused(self, paused: bool) -> None: ...

    def close(self) -> None: ...


AudioCallback = Callable[[Any, int, Any, Any], None]
AudioStreamFactory = Callable[[AudioCallback], AudioInputStream]
SttTransportFactory = Callable[[], RealtimeSttTransport]


def float_samples_to_pcm16(samples: Sequence[float] | Any) -> bytes:
    import numpy as np

    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    return (np.clip(values, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def _bounded_text(value: object, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


class ElevenLabsRealtimeTransport:
    """Small synchronous adapter around the ElevenLabs realtime STT WebSocket."""

    def __init__(self, settings: VoiceSettings, api_key: str) -> None:
        self._api_key = api_key
        self._timeout = settings.network_timeout_seconds
        self._max_event_bytes = 262_144
        query = urlencode(
            {
                "model_id": settings.elevenlabs_stt_model,
                "audio_format": f"pcm_{settings.sample_rate}",
                "commit_strategy": "vad",
                "vad_silence_threshold_secs": settings.vad_silence_seconds,
            }
        )
        self._url = f"{settings.elevenlabs_stt_url}?{query}"
        self._socket: Any | None = None

    def connect(self) -> None:
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("websocket-client is required for ElevenLabs realtime STT") from exc
        self._socket = websocket.create_connection(
            self._url,
            header=[f"xi-api-key: {self._api_key}"],
            timeout=self._timeout,
            enable_multithread=True,
        )

    def send_audio(self, pcm: bytes, *, commit: bool = False) -> None:
        if self._socket is None:
            raise RuntimeError("ElevenLabs realtime socket is not connected")
        payload = {
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(pcm).decode("ascii"),
            "commit": commit,
            "sample_rate": 16_000,
        }
        self._socket.send(json.dumps(payload, separators=(",", ":")))

    def receive(self, timeout_seconds: float) -> dict[str, object] | None:
        if self._socket is None:
            return None
        try:
            import websocket

            self._socket.settimeout(max(timeout_seconds, 0.001))
            raw = self._socket.recv()
        except (TimeoutError, websocket.WebSocketTimeoutException):
            return None
        if isinstance(raw, bytes):
            if len(raw) > self._max_event_bytes:
                raise RuntimeError("ElevenLabs realtime event exceeded the size limit")
            raw = raw.decode("utf-8")
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > self._max_event_bytes:
            raise RuntimeError("Invalid ElevenLabs realtime event")
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise RuntimeError("Invalid ElevenLabs realtime event payload")
        return decoded

    def close(self) -> None:
        socket = self._socket
        self._socket = None
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass


class ElevenLabsTtsSpeaker:
    """Stream ElevenLabs PCM into an output device without blocking UI/capture threads."""

    def __init__(self, settings: VoiceSettings, api_key: str) -> None:
        self._voice_id = settings.elevenlabs_tts_voice_id
        self._model = settings.elevenlabs_tts_model
        self._api_key = api_key
        self._sample_rate = settings.sample_rate
        self._timeout = settings.network_timeout_seconds
        self._max_audio_bytes = 4 * 1024 * 1024

    def speak(self, text: str, cancelled: threading.Event) -> None:
        if not self._voice_id:
            return
        try:
            import requests
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("requests and sounddevice are required for ElevenLabs TTS") from exc
        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/{quote(self._voice_id)}/stream"
            f"?output_format=pcm_{self._sample_rate}"
        )
        body: Any = {
            "text": text,
            "model_id": self._model,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.75},
        }
        received = 0
        with requests.post(
            url,
            headers={"xi-api-key": self._api_key, "Content-Type": "application/json"},
            json=body,
            stream=True,
            timeout=(self._timeout, self._timeout),
        ) as response:
            response.raise_for_status()
            with sd.RawOutputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="int16",
            ) as output:
                for chunk in response.iter_content(chunk_size=4096):
                    if cancelled.is_set():
                        return
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > self._max_audio_bytes:
                        raise RuntimeError("ElevenLabs TTS response exceeded the size limit")
                    output.write(chunk)


class VoiceSession:
    """Own one microphone stream and move audio through wake, STT, request, and TTS states."""

    def __init__(
        self,
        settings: VoiceSettings,
        wake_detector: WakeWordDetector,
        transport_factory: SttTransportFactory,
        speaker: TtsSpeaker | None = None,
        stream_factory: AudioStreamFactory | None = None,
    ) -> None:
        if settings.sample_rate != 16_000:
            raise ValueError("ElevenLabs realtime voice currently requires a 16 kHz sample rate")
        if settings.audio_chunk_ms < 20 or settings.audio_chunk_ms > 1000:
            raise ValueError("Voice audio chunks must be between 20 and 1000 ms")
        if settings.audio_queue_chunks < 2 or settings.audio_queue_chunks > 1000:
            raise ValueError("Voice audio queue must contain between 2 and 1000 chunks")
        if settings.max_transcript_chars < 1 or settings.max_transcript_chars > 64_000:
            raise ValueError("Voice transcript limit must be between 1 and 64,000 characters")
        if (
            settings.no_speech_timeout_seconds <= 0
            or settings.max_request_seconds < settings.no_speech_timeout_seconds
            or settings.max_request_seconds > 300
        ):
            raise ValueError("Voice request timeouts are invalid")
        self.settings = settings
        self._wake = wake_detector
        self._transport_factory = transport_factory
        self._speaker = speaker
        self._stream_factory = stream_factory or self._default_stream_factory
        self._audio: queue.Queue[Any] = queue.Queue(maxsize=settings.audio_queue_chunks)
        self._events: queue.Queue[VoiceEvent] = queue.Queue(maxsize=256)
        self._commands: queue.Queue[tuple[str, str, str]] = queue.Queue(maxsize=32)
        self._stop = threading.Event()
        self._cancelled = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream: AudioInputStream | None = None
        self._transport: RealtimeSttTransport | None = None
        self._state = VoiceState.PAUSED
        self._request_id: str | None = None
        self._completed: deque[str] = deque(maxlen=32)
        self._completion_pending: set[str] = set()
        self._lock = threading.Lock()
        self._tts_warned = False
        self.dropped_audio_chunks = 0

    @property
    def state(self) -> VoiceState:
        with self._lock:
            return self._state

    @property
    def request_id(self) -> str | None:
        with self._lock:
            return self._request_id

    def _default_stream_factory(self, callback: AudioCallback) -> AudioInputStream:
        try:
            import sounddevice as sd
        except (ModuleNotFoundError, OSError) as exc:
            raise RuntimeError("sounddevice is required for Chudvis microphone input") from exc
        device: str | int | None = self.settings.input_device or None
        if isinstance(device, str):
            try:
                device = int(device)
            except ValueError:
                pass
        blocksize = self.settings.sample_rate * self.settings.audio_chunk_ms // 1000
        return cast(
            AudioInputStream,
            sd.InputStream(
                samplerate=self.settings.sample_rate,
                blocksize=blocksize,
                channels=1,
                dtype="float32",
                device=device,
                callback=callback,
            ),
        )

    def _audio_callback(
        self,
        samples: Any,
        _frames: int,
        _time_info: Any,
        _status: Any,
    ) -> None:
        if self._stop.is_set():
            return
        copied = samples.copy().reshape(-1)
        try:
            self._audio.put_nowait(copied)
        except queue.Full:
            try:
                self._audio.get_nowait()
            except queue.Empty:
                pass
            self.dropped_audio_chunks += 1
            try:
                self._audio.put_nowait(copied)
            except queue.Full:
                self.dropped_audio_chunks += 1

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._cancelled.clear()
        stream = self._stream_factory(self._audio_callback)
        self._stream = stream
        self._thread = threading.Thread(target=self._run, name="chudvis-voice", daemon=True)
        try:
            stream.start()
            self._thread.start()
        except Exception:
            self._thread = None
            self._stream = None
            try:
                stream.close()
            finally:
                raise

    def _emit(self, event: VoiceEvent) -> None:
        try:
            self._events.put_nowait(event)
        except queue.Full:
            try:
                self._events.get_nowait()
            except queue.Empty:
                pass
            self._events.put_nowait(event)

    def _set_state(self, state: VoiceState, detail: str = "") -> None:
        with self._lock:
            self._state = state
            request_id = self._request_id
        self._emit(
            VoiceEvent(
                VoiceEventType.STATE,
                request_id=request_id,
                state=state,
                detail=detail[:500],
            )
        )

    def poll(self, max_events: int = 64) -> list[VoiceEvent]:
        events: list[VoiceEvent] = []
        for _ in range(max(1, min(max_events, 256))):
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def cancel(self, request_id: str | None = None) -> bool:
        with self._lock:
            active = self._request_id
        if active is None or (request_id is not None and request_id != active):
            return False
        self._cancelled.set()
        transport = self._transport
        if transport is not None:
            transport.close()
        try:
            self._commands.put_nowait(("cancel", active, ""))
        except queue.Full:
            pass
        return True

    def complete(self, request_id: str, status: str, spoken_summary: str = "") -> bool:
        with self._lock:
            active = self._request_id
            duplicate = request_id in self._completed or request_id in self._completion_pending
        if duplicate:
            return True
        if active != request_id:
            return False
        if status not in {"succeeded", "failed", "cancelled"}:
            return False
        summary = spoken_summary.strip()[:160] if status in {"succeeded", "failed"} else ""
        with self._lock:
            self._completion_pending.add(request_id)
        try:
            self._commands.put_nowait((status, request_id, summary))
        except queue.Full:
            with self._lock:
                self._completion_pending.discard(request_id)
            return False
        return True

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._cancelled.set()
            transport = self._transport
            if transport is not None:
                transport.close()
        try:
            self._commands.put_nowait(("pause" if paused else "resume", "", ""))
        except queue.Full:
            pass

    def _activate(self) -> None:
        with self._lock:
            self._request_id = str(uuid.uuid4())
        self._cancelled.clear()
        self._set_state(VoiceState.CONNECTING)
        transport = self._transport_factory()
        self._transport = transport
        transport.connect()
        if self._cancelled.is_set():
            raise InterruptedError
        self._set_state(VoiceState.LISTENING)

    @staticmethod
    def _message_kind(message: dict[str, object]) -> str:
        value = message.get("message_type", message.get("type", ""))
        return value if isinstance(value, str) else ""

    def _handle_stt_event(self, message: dict[str, object]) -> bool:
        kind = self._message_kind(message)
        text = _bounded_text(message.get("text"), self.settings.max_transcript_chars).strip()
        if kind in {"partial_transcript", "partial"} and text:
            self._emit(
                VoiceEvent(VoiceEventType.PARTIAL, request_id=self.request_id, text=text)
            )
            return False
        if kind in {
            "committed_transcript",
            "committed_transcript_with_timestamps",
            "final_transcript",
        }:
            if not text:
                self._rearm("No speech detected")
                return True
            request_id = self.request_id
            self._set_state(VoiceState.UNDERSTANDING)
            self._emit(VoiceEvent(VoiceEventType.REQUEST, request_id=request_id, text=text))
            return True
        if kind in {"error", "auth_error", "quota_exceeded"}:
            detail = _bounded_text(message.get("error", message.get("message")), 500)
            raise RuntimeError(detail or "ElevenLabs realtime transcription failed")
        return False

    def _listen(self) -> None:
        transport = self._transport
        if transport is None:
            return
        started = monotonic()
        heard_speech = False
        while not self._stop.is_set() and not self._cancelled.is_set():
            elapsed = monotonic() - started
            if elapsed >= self.settings.max_request_seconds:
                self._rearm("Voice request timed out")
                return
            if not heard_speech and elapsed >= self.settings.no_speech_timeout_seconds:
                self._rearm("No speech detected")
                return
            try:
                samples = self._audio.get(timeout=0.02)
            except queue.Empty:
                samples = None
            if samples is not None:
                transport.send_audio(float_samples_to_pcm16(samples))
            message = transport.receive(0.005)
            if message is None:
                continue
            if self._message_kind(message) in {"partial_transcript", "partial"}:
                heard_speech = True
            if self._handle_stt_event(message):
                transport.close()
                self._transport = None
                return
        if self._cancelled.is_set():
            self._rearm("Voice request cancelled")

    def _handle_command(self, command: tuple[str, str, str]) -> None:
        status, request_id, summary = command
        if status == "pause":
            transport = self._transport
            self._transport = None
            if transport is not None:
                transport.close()
            self._clear_audio()
            self._wake.reset()
            with self._lock:
                self._request_id = None
            self._set_state(VoiceState.PAUSED)
            return
        if status == "resume":
            if self.state == VoiceState.PAUSED:
                self._rearm()
            return
        if request_id != self.request_id:
            with self._lock:
                self._completion_pending.discard(request_id)
            return
        if status == "cancel":
            self._rearm("Voice request cancelled")
            return
        if summary and self._speaker is not None:
            self._set_state(VoiceState.SPEAKING)
            try:
                self._speaker.speak(summary, self._cancelled)
            except Exception:
                if not self._tts_warned:
                    self._tts_warned = True
                    self._set_state(VoiceState.ERROR, "Spoken summary unavailable")
        with self._lock:
            self._completed.append(request_id)
            self._completion_pending.discard(request_id)
        self._rearm()

    def _clear_audio(self) -> None:
        while True:
            try:
                self._audio.get_nowait()
            except queue.Empty:
                return

    def _rearm(self, detail: str = "") -> None:
        transport = self._transport
        self._transport = None
        if transport is not None:
            transport.close()
        self._cancelled.clear()
        self._clear_audio()
        self._wake.reset()
        with self._lock:
            if self._request_id is not None:
                self._completion_pending.discard(self._request_id)
            self._request_id = None
        self._set_state(VoiceState.READY, detail)

    def _run(self) -> None:
        self._set_state(VoiceState.READY)
        while not self._stop.is_set():
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                command = None
            if command is not None:
                self._handle_command(command)
                continue
            if self.state not in {VoiceState.READY, VoiceState.LISTENING}:
                self._stop.wait(0.02)
                continue
            try:
                samples = self._audio.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                if self.state == VoiceState.READY:
                    if self._wake.accept(samples):
                        self._activate()
                        self._listen()
                elif self.state == VoiceState.LISTENING:
                    self._listen()
            except InterruptedError:
                self._rearm("Voice request cancelled")
            except Exception as exc:
                if self._cancelled.is_set():
                    self._rearm("Voice request cancelled")
                else:
                    self._set_state(VoiceState.ERROR, str(exc))
                    self._rearm("Voice service recovered")

    def close(self) -> None:
        self._stop.set()
        self._cancelled.set()
        transport = self._transport
        if transport is not None:
            transport.close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
        stream = self._stream
        self._stream = None
        self._thread = None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        self._set_state(VoiceState.PAUSED)


def create_elevenlabs_voice_session(settings: VoiceSettings) -> VoiceSession:
    from pathlib import Path

    from chudvis.speech.wake_word import SherpaWakeWordDetector

    api_key = os.environ.get(settings.elevenlabs_api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(
            f"{settings.elevenlabs_api_key_env} is not configured; using local dictation fallback"
        )
    cache_dir = (
        Path(settings.wake_word_cache_dir).expanduser()
        if settings.wake_word_cache_dir
        else None
    )
    wake = SherpaWakeWordDetector(
        settings.wake_word_spellings,
        settings.wake_word_score,
        settings.wake_word_threshold,
        cache_dir,
    )
    speaker: TtsSpeaker | None = None
    if settings.elevenlabs_tts_enabled:
        speaker = ElevenLabsTtsSpeaker(settings, api_key)
    return VoiceSession(
        settings,
        wake,
        lambda: ElevenLabsRealtimeTransport(settings, api_key),
        speaker,
    )
