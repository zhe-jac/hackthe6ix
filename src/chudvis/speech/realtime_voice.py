from __future__ import annotations

import base64
import json
import multiprocessing
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


class SpokenFeedbackUnavailableError(RuntimeError):
    """The configured TTS service cannot serve this account and should be disabled."""


def _elevenlabs_error_detail(response: Any) -> str:
    """Return a bounded provider error without ever including request headers."""
    try:
        payload: object = response.json()
    except Exception:
        payload = getattr(response, "text", "")
    detail: object = payload
    if isinstance(payload, dict):
        detail = payload.get("detail", payload)
    if isinstance(detail, dict):
        status = detail.get("status") or detail.get("type")
        message = detail.get("message") or detail.get("error")
        if status and message:
            detail = f"{status}: {message}"
        else:
            detail = message or status or ""
    if not isinstance(detail, str):
        detail = ""
    result = " ".join(detail.split())[:320]
    headers = getattr(response, "headers", {})
    request_id = ""
    if hasattr(headers, "get"):
        request_id = str(headers.get("request-id") or headers.get("x-request-id") or "")
        request_id = " ".join(request_id.split())[:120]
    if request_id:
        result = f"{result}; request {request_id}" if result else f"request {request_id}"
    return result


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

    def speak(self, text: str) -> bool: ...

    def set_paused(self, paused: bool) -> None: ...

    def close(self) -> None: ...


AudioCallback = Callable[[Any, int, Any, Any], None]
AudioStreamFactory = Callable[[AudioCallback], AudioInputStream]
SttTransportFactory = Callable[[], RealtimeSttTransport]


@dataclass(frozen=True, slots=True)
class AudioCaptureStatus:
    """Audio health forwarded from the isolated microphone process."""

    input_overflow: bool = False
    dropped_chunks: int = 0
    error: str = ""


def _isolated_audio_capture_worker(
    sample_rate: int,
    blocksize: int,
    input_device: str,
    stop: Any,
    chunks: Any,
    started: Any,
) -> None:
    """Capture contiguous microphone blocks outside the camera/MediaPipe process."""
    announced = False
    try:
        import numpy as np
        import sounddevice as sd

        device: str | int | None = input_device or None
        if isinstance(device, str):
            try:
                device = int(device)
            except ValueError:
                pass
        selected = sd.query_devices(device, "input")
        device_name = str(selected.get("name", device or "default input"))
        dropped_chunks = 0
        with sd.InputStream(
            samplerate=sample_rate,
            blocksize=blocksize,
            channels=1,
            dtype="float32",
            device=device,
        ) as microphone:
            started.send(("ready", device_name))
            announced = True
            while not stop.is_set():
                samples, overflowed = microphone.read(blocksize)
                payload = (
                    "audio",
                    np.asarray(samples, dtype="<f4").reshape(-1).tobytes(),
                    bool(overflowed),
                    dropped_chunks,
                )
                try:
                    chunks.put(payload, timeout=0.05)
                except queue.Full:
                    # Preserve the already-buffered contiguous audio. The next delivered
                    # block carries the cumulative loss count to the parent diagnostics.
                    dropped_chunks += 1
    except Exception as exc:
        detail = str(exc)[:500] or type(exc).__name__
        if not announced:
            try:
                started.send(("error", detail))
            except (BrokenPipeError, EOFError, OSError):
                pass
        else:
            try:
                chunks.put(("error", detail), timeout=0.1)
            except queue.Full:
                pass
    finally:
        try:
            started.close()
        except OSError:
            pass


class IsolatedAudioInputStream:
    """Sounddevice-compatible stream whose capture loop lives in a child process."""

    def __init__(
        self,
        callback: AudioCallback,
        sample_rate: int,
        blocksize: int,
        input_device: str,
        queue_chunks: int,
    ) -> None:
        self._callback = callback
        self._sample_rate = sample_rate
        self._blocksize = blocksize
        self._input_device = input_device
        self._queue_chunks = queue_chunks
        self._stop: Any | None = None
        self._chunks: Any | None = None
        self._process: Any | None = None
        self._bridge: threading.Thread | None = None
        self.device_name = ""

    def start(self) -> IsolatedAudioInputStream:
        if self._process is not None:
            return self
        context = multiprocessing.get_context("spawn")
        stop = context.Event()
        chunks = context.Queue(maxsize=self._queue_chunks)
        ready_receiver, ready_sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_isolated_audio_capture_worker,
            args=(
                self._sample_rate,
                self._blocksize,
                self._input_device,
                stop,
                chunks,
                ready_sender,
            ),
            name="chudvis-audio-capture",
            daemon=True,
        )
        process.start()
        ready_sender.close()
        try:
            if not ready_receiver.poll(10.0):
                raise RuntimeError("Microphone capture process did not start within 10 seconds")
            kind, detail = ready_receiver.recv()
            if kind != "ready":
                raise RuntimeError(f"Could not start microphone capture: {detail}")
            self.device_name = str(detail)
        except Exception:
            stop.set()
            process.join(timeout=1.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
            chunks.cancel_join_thread()
            chunks.close()
            raise
        finally:
            ready_receiver.close()

        self._stop = stop
        self._chunks = chunks
        self._process = process
        self._bridge = threading.Thread(
            target=self._forward_audio,
            name="chudvis-audio-bridge",
            daemon=True,
        )
        self._bridge.start()
        return self

    def _forward_audio(self) -> None:
        import numpy as np

        stop = self._stop
        chunks = self._chunks
        process = self._process
        if stop is None or chunks is None or process is None:
            return
        while not stop.is_set() or process.is_alive():
            try:
                payload = chunks.get(timeout=0.2)
            except queue.Empty:
                continue
            if not isinstance(payload, tuple) or not payload:
                continue
            if payload[0] == "error":
                detail = str(payload[1]) if len(payload) > 1 else "Microphone capture stopped"
                self._callback(
                    np.empty((0, 1), dtype=np.float32),
                    0,
                    None,
                    AudioCaptureStatus(error=detail),
                )
                return
            if payload[0] != "audio" or len(payload) != 4:
                continue
            raw, overflowed, dropped_chunks = payload[1:]
            if not isinstance(raw, bytes):
                continue
            samples = np.frombuffer(raw, dtype="<f4").reshape(-1, 1)
            self._callback(
                samples,
                len(samples),
                None,
                AudioCaptureStatus(
                    input_overflow=bool(overflowed),
                    dropped_chunks=max(int(dropped_chunks), 0),
                ),
            )

    def stop(self) -> None:
        stop = self._stop
        process = self._process
        if stop is not None:
            stop.set()
        if process is not None:
            process.join(timeout=2.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
        bridge = self._bridge
        if bridge is not None and bridge is not threading.current_thread():
            bridge.join(timeout=1.0)
        self._process = None
        self._bridge = None

    def close(self) -> None:
        self.stop()
        chunks = self._chunks
        self._chunks = None
        self._stop = None
        if chunks is not None:
            chunks.cancel_join_thread()
            chunks.close()


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

    def __init__(self, settings: VoiceSettings, api_key: str, voice_id: str = "") -> None:
        self._voice_id = voice_id.strip() or settings.elevenlabs_tts_voice_id
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
            if response.status_code in {400, 401, 402, 403, 404, 422}:
                detail = _elevenlabs_error_detail(response)
                reason = f": {detail}" if detail else ""
                if response.status_code == 402:
                    action = (
                        "Choose a voice available to this account and check both the workspace "
                        "balance and this API key's credit quota."
                    )
                elif response.status_code == 404:
                    action = "Choose another voice; the configured voice is no longer available."
                else:
                    action = "Review the configured ElevenLabs voice, model, and API-key access."
                raise SpokenFeedbackUnavailableError(
                    f"ElevenLabs TTS returned HTTP {response.status_code}{reason}. {action} "
                    "Spoken feedback is disabled for this session."
                )
            response.raise_for_status()
            with sd.RawOutputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="int16",
            ) as output:
                remainder = b""
                for chunk in response.iter_content(chunk_size=4096):
                    if cancelled.is_set():
                        return
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > self._max_audio_bytes:
                        raise RuntimeError("ElevenLabs TTS response exceeded the size limit")
                    buffered = remainder + chunk
                    aligned_length = len(buffered) - (len(buffered) % 2)
                    if aligned_length:
                        output.write(buffered[:aligned_length])
                    remainder = buffered[aligned_length:]


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
        self.dropped_audio_chunks = 0
        self.capture_overflows = 0
        self.capture_dropped_chunks = 0
        self.max_audio_queue_depth = 0
        self._capture_error = ""
        self._last_reported_audio_loss = 0

    @property
    def state(self) -> VoiceState:
        with self._lock:
            return self._state

    @property
    def request_id(self) -> str | None:
        with self._lock:
            return self._request_id

    def _default_stream_factory(self, callback: AudioCallback) -> AudioInputStream:
        blocksize = self.settings.sample_rate * self.settings.audio_chunk_ms // 1000
        return cast(
            AudioInputStream,
            IsolatedAudioInputStream(
                callback,
                self.settings.sample_rate,
                blocksize,
                self.settings.input_device,
                self.settings.audio_queue_chunks,
            ),
        )

    def _report_audio_loss(self) -> None:
        total = self.capture_overflows + self.capture_dropped_chunks + self.dropped_audio_chunks
        if total <= self._last_reported_audio_loss:
            return
        # Report the first loss and then powers of two so a broken device is visible
        # without flooding the bridge/UI from the real-time callback path.
        if self._last_reported_audio_loss and total & (total - 1):
            return
        self._last_reported_audio_loss = total
        self._emit(
            VoiceEvent(
                VoiceEventType.STATE,
                request_id=self.request_id,
                state=self.state,
                detail=(f"Microphone lost {total} audio chunk(s); wake recognition may miss words"),
            )
        )

    def _audio_callback(
        self,
        samples: Any,
        _frames: int,
        _time_info: Any,
        status: Any,
    ) -> None:
        if self._stop.is_set():
            return
        error = getattr(status, "error", "")
        if error:
            self._capture_error = str(error)[:500]
            try:
                self._audio.put_nowait([])
            except queue.Full:
                pass
            return
        if self.state not in {
            VoiceState.READY,
            VoiceState.CONNECTING,
            VoiceState.LISTENING,
        }:
            return
        if bool(getattr(status, "input_overflow", False)):
            self.capture_overflows += 1
        capture_drops = max(int(getattr(status, "dropped_chunks", 0)), 0)
        self.capture_dropped_chunks = max(self.capture_dropped_chunks, capture_drops)
        if self.capture_overflows or self.capture_dropped_chunks:
            self._report_audio_loss()
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
            self._report_audio_loss()
        try:
            self.max_audio_queue_depth = max(self.max_audio_queue_depth, self._audio.qsize())
        except (NotImplementedError, OSError):
            pass

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

    def speak(self, text: str) -> bool:
        summary = text.strip()[:160]
        with self._lock:
            active = self._request_id
        if not summary or self._speaker is None or active is not None:
            return False
        try:
            self._commands.put_nowait(("speak", "", summary))
        except queue.Full:
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
            self._emit(VoiceEvent(VoiceEventType.PARTIAL, request_id=self.request_id, text=text))
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
        if status == "speak":
            self._cancelled.clear()
            self._set_state(VoiceState.SPEAKING)
            rearm_detail, failed = self._speak_summary(summary)
            if failed:
                self._set_state(VoiceState.ERROR, rearm_detail)
            self._rearm(rearm_detail)
            return
        if request_id != self.request_id:
            with self._lock:
                self._completion_pending.discard(request_id)
            return
        if status == "cancel":
            self._rearm("Voice request cancelled")
            return
        rearm_detail = ""
        if summary and self._speaker is not None:
            self._set_state(VoiceState.SPEAKING)
            rearm_detail, failed = self._speak_summary(summary)
            if failed:
                self._set_state(VoiceState.ERROR, rearm_detail)
        with self._lock:
            self._completed.append(request_id)
            self._completion_pending.discard(request_id)
        self._rearm(rearm_detail)

    def _speak_summary(self, summary: str) -> tuple[str, bool]:
        speaker = self._speaker
        if speaker is None:
            return "", False
        try:
            speaker.speak(summary, self._cancelled)
        except SpokenFeedbackUnavailableError as exc:
            self._speaker = None
            return str(exc).strip()[:500], False
        except Exception as exc:
            detail = str(exc).strip()[:420] or type(exc).__name__
            return f"Spoken summary unavailable: {detail}", True
        return "", False

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
        device_name = str(getattr(self._stream, "device_name", "")).strip()
        detail = f"Listening on {device_name}" if device_name else ""
        self._set_state(VoiceState.READY, detail)
        while not self._stop.is_set():
            if self._capture_error:
                self._set_state(VoiceState.ERROR, self._capture_error)
                return
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
            if self._capture_error:
                self._set_state(VoiceState.ERROR, self._capture_error)
                return
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
        Path(settings.wake_word_cache_dir).expanduser() if settings.wake_word_cache_dir else None
    )
    wake = SherpaWakeWordDetector(
        settings.wake_word_spellings,
        settings.wake_word_score,
        settings.wake_word_threshold,
        cache_dir,
    )
    enabled_override = os.environ.get("CHUDVIS_ELEVENLABS_TTS_ENABLED", "").strip().lower()
    tts_enabled = settings.elevenlabs_tts_enabled
    if enabled_override in {"0", "false", "no", "off"}:
        tts_enabled = False
    elif enabled_override in {"1", "true", "yes", "on"}:
        tts_enabled = True
    voice_id = os.environ.get(
        "CHUDVIS_ELEVENLABS_VOICE_ID", settings.elevenlabs_tts_voice_id
    ).strip()
    speaker: TtsSpeaker | None = None
    if tts_enabled and voice_id:
        speaker = ElevenLabsTtsSpeaker(settings, api_key, voice_id)
    return VoiceSession(
        settings,
        wake,
        lambda: ElevenLabsRealtimeTransport(settings, api_key),
        speaker,
    )
