from __future__ import annotations

import queue
import sys
import threading
from time import monotonic, sleep
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from chudvis.core.config import VoiceSettings
from chudvis.speech.realtime_voice import (
    AudioCaptureStatus,
    ElevenLabsTtsSpeaker,
    SpokenFeedbackUnavailableError,
    VoiceEvent,
    VoiceEventType,
    VoiceSession,
    VoiceState,
    _isolated_audio_capture_worker,
    float_samples_to_pcm16,
)


class FakeWakeDetector:
    def __init__(self) -> None:
        self.resets = 0

    def accept(self, samples: Any) -> bool:
        return bool(np.max(samples) > 0.9)

    def reset(self) -> None:
        self.resets += 1


class FakeTransport:
    def __init__(self, connect_gate: threading.Event | None = None) -> None:
        self.connect_gate = connect_gate
        self.connected = False
        self.closed = False
        self.sent: list[bytes] = []
        self.inbound: queue.Queue[dict[str, object]] = queue.Queue()

    def connect(self) -> None:
        if self.connect_gate is not None:
            self.connect_gate.wait(timeout=2.0)
        self.connected = True

    def send_audio(self, pcm: bytes, *, commit: bool = False) -> None:
        del commit
        self.sent.append(pcm)

    def receive(self, timeout_seconds: float) -> dict[str, object] | None:
        try:
            return self.inbound.get(timeout=timeout_seconds)
        except queue.Empty:
            return None

    def close(self) -> None:
        self.closed = True


class FakeInputStream:
    def __init__(self, callback: Any) -> None:
        self.callback = callback
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def push(self, value: float, status: Any = None) -> None:
        samples = np.full((1600, 1), value, dtype=np.float32)
        self.callback(samples, len(samples), None, status)

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


class FakeSpeaker:
    def __init__(self, fail: bool = False, unavailable: bool = False) -> None:
        self.fail = fail
        self.unavailable = unavailable
        self.spoken: list[str] = []

    def speak(self, text: str, cancelled: threading.Event) -> None:
        assert not cancelled.is_set()
        self.spoken.append(text)
        if self.unavailable:
            raise SpokenFeedbackUnavailableError("Spoken feedback disabled for this session")
        if self.fail:
            raise RuntimeError("speaker failed")


class Harness:
    def __init__(
        self,
        *,
        gate: threading.Event | None = None,
        speaker: FakeSpeaker | None = None,
        queue_chunks: int = 16,
    ) -> None:
        self.wake = FakeWakeDetector()
        self.transport = FakeTransport(gate)
        self.streams: list[FakeInputStream] = []
        settings = VoiceSettings(
            audio_queue_chunks=queue_chunks,
            no_speech_timeout_seconds=2.0,
            max_request_seconds=3.0,
        )

        def stream_factory(callback: Any) -> FakeInputStream:
            stream = FakeInputStream(callback)
            self.streams.append(stream)
            return stream

        self.session = VoiceSession(
            settings,
            self.wake,
            lambda: self.transport,
            speaker,
            stream_factory,
        )
        self.session.start()

    @property
    def stream(self) -> FakeInputStream:
        return self.streams[0]

    def events_until(
        self,
        predicate: Any,
        timeout: float = 2.0,
    ) -> list[VoiceEvent]:
        events: list[VoiceEvent] = []
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            events.extend(self.session.poll())
            if predicate(events):
                return events
            sleep(0.01)
        raise AssertionError(f"voice event timeout; saw {events}")

    def close(self) -> None:
        self.session.close()


def state_seen(events: list[VoiceEvent], state: VoiceState) -> bool:
    return any(event.type == VoiceEventType.STATE and event.state == state for event in events)


def test_float_audio_is_clipped_and_encoded_as_little_endian_pcm16() -> None:
    encoded = float_samples_to_pcm16([-2.0, -1.0, 0.0, 0.5, 1.0, 2.0])
    values = np.frombuffer(encoded, dtype="<i2").tolist()

    assert values == [-32767, -32767, 0, 16383, 32767, 32767]


def test_microphone_level_is_reported_after_capture_forwarding() -> None:
    harness = Harness()
    try:
        harness.events_until(lambda events: state_seen(events, VoiceState.READY))
        harness.stream.push(0.1)
        events = harness.events_until(
            lambda values: any(event.type == VoiceEventType.LEVEL for event in values)
        )

        level = next(event for event in events if event.type == VoiceEventType.LEVEL)
        assert level.dbfs == pytest.approx(-20.0, abs=0.1)
        assert level.level == pytest.approx(2 / 3, abs=0.01)
    finally:
        harness.close()


def test_elevenlabs_tts_buffers_pcm_samples_split_across_http_chunks(
    monkeypatch: Any,
) -> None:
    writes: list[bytes] = []

    class FakeResponse:
        status_code = 200

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def raise_for_status(self) -> None:
            pass

        def iter_content(self, chunk_size: int) -> list[bytes]:
            assert chunk_size == 4096
            return [b"\x01", b"\x02\x03", b"\x04"]

    class FakeOutput:
        def __enter__(self) -> FakeOutput:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def write(self, data: bytes) -> None:
            assert len(data) % 2 == 0
            writes.append(data)

    fake_requests = SimpleNamespace(post=lambda *_args, **_kwargs: FakeResponse())
    fake_sounddevice = SimpleNamespace(RawOutputStream=lambda **_kwargs: FakeOutput())
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice)

    speaker = ElevenLabsTtsSpeaker(VoiceSettings(), "test-key", "test-voice")
    speaker.speak("Created test.py", threading.Event())

    assert writes == [b"\x01\x02", b"\x03\x04"]


def test_isolated_capture_worker_uses_blocking_contiguous_reads(monkeypatch: Any) -> None:
    class StopAfterOneRead:
        checks = 0

        def is_set(self) -> bool:
            self.checks += 1
            return self.checks > 1

    class FakeMicrophone:
        def __enter__(self) -> FakeMicrophone:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def read(self, frames: int) -> tuple[np.ndarray, bool]:
            return np.full((frames, 1), 0.25, dtype=np.float32), True

    class RecordingPipe:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        def send(self, message: tuple[str, str]) -> None:
            self.messages.append(message)

        def close(self) -> None:
            pass

    class RecordingQueue:
        def __init__(self) -> None:
            self.items: list[tuple[object, ...]] = []

        def put(self, item: tuple[object, ...], timeout: float) -> None:
            del timeout
            self.items.append(item)

    fake_sounddevice = SimpleNamespace(
        query_devices=lambda _device, _kind: {"name": "Test microphone"},
        InputStream=lambda **_kwargs: FakeMicrophone(),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice)
    chunks = RecordingQueue()
    started = RecordingPipe()

    _isolated_audio_capture_worker(
        16_000,
        1_600,
        "",
        StopAfterOneRead(),
        chunks,
        started,
    )

    assert started.messages == [("ready", "Test microphone")]
    assert len(chunks.items) == 1
    kind, raw, overflowed, dropped = chunks.items[0]
    assert kind == "audio"
    assert isinstance(raw, bytes)
    assert np.allclose(np.frombuffer(raw, dtype="<f4"), 0.25)
    assert overflowed is True
    assert dropped == 0


def test_no_transport_or_audio_exists_before_wake_activation() -> None:
    harness = Harness()
    try:
        harness.stream.push(0.1)
        sleep(0.05)

        assert not harness.transport.connected
        assert harness.transport.sent == []
        assert len(harness.streams) == 1
    finally:
        harness.close()


def test_post_activation_audio_is_buffered_during_handshake_then_transcribed() -> None:
    gate = threading.Event()
    harness = Harness(gate=gate)
    try:
        harness.stream.push(1.0)
        harness.events_until(lambda events: state_seen(events, VoiceState.CONNECTING))
        harness.stream.push(0.25)
        harness.stream.push(0.30)
        gate.set()
        harness.events_until(lambda events: state_seen(events, VoiceState.LISTENING))

        deadline = monotonic() + 1.0
        while len(harness.transport.sent) < 2 and monotonic() < deadline:
            sleep(0.01)
        harness.transport.inbound.put({"message_type": "partial_transcript", "text": "open"})
        harness.transport.inbound.put(
            {"message_type": "committed_transcript", "text": "open file README.md"}
        )
        events = harness.events_until(
            lambda values: any(event.type == VoiceEventType.REQUEST for event in values)
        )

        assert len(harness.transport.sent) >= 2
        assert any(
            event.type == VoiceEventType.PARTIAL and event.text == "open" for event in events
        )
        request = next(event for event in events if event.type == VoiceEventType.REQUEST)
        assert request.text == "open file README.md"
        assert request.request_id
    finally:
        gate.set()
        harness.close()


def test_completion_speaks_once_then_rearms_wake_detection() -> None:
    speaker = FakeSpeaker()
    harness = Harness(speaker=speaker)
    try:
        harness.stream.push(1.0)
        harness.events_until(lambda events: state_seen(events, VoiceState.LISTENING))
        harness.transport.inbound.put(
            {"message_type": "committed_transcript", "text": "fix the parser"}
        )
        events = harness.events_until(
            lambda values: any(event.type == VoiceEventType.REQUEST for event in values)
        )
        request = next(event for event in events if event.type == VoiceEventType.REQUEST)
        assert request.request_id is not None

        assert harness.session.complete(
            request.request_id,
            "succeeded",
            "Updated the parser error handling.",
        )
        finished = harness.events_until(lambda values: state_seen(values, VoiceState.READY))

        assert state_seen(finished, VoiceState.SPEAKING)
        assert speaker.spoken == ["Updated the parser error handling."]
        assert harness.wake.resets >= 1
        assert harness.session.complete(request.request_id, "succeeded", "duplicate")
        assert speaker.spoken == ["Updated the parser error handling."]
    finally:
        harness.close()


def test_explicit_speech_feedback_works_while_waiting_for_the_wake_word() -> None:
    speaker = FakeSpeaker()
    harness = Harness(speaker=speaker)
    try:
        assert harness.session.speak("Chudvis voice feedback is ready.")
        finished = harness.events_until(
            lambda values: state_seen(values, VoiceState.SPEAKING) and bool(speaker.spoken)
        )

        assert state_seen(finished, VoiceState.SPEAKING)
        assert speaker.spoken == ["Chudvis voice feedback is ready."]
    finally:
        harness.close()


def test_cancel_rearms_and_stale_completion_is_rejected() -> None:
    harness = Harness()
    try:
        harness.stream.push(1.0)
        events = harness.events_until(lambda values: state_seen(values, VoiceState.LISTENING))
        request_id = next(
            event.request_id
            for event in events
            if event.type == VoiceEventType.STATE and event.state == VoiceState.LISTENING
        )
        assert request_id is not None
        assert harness.session.cancel(request_id)
        harness.events_until(lambda values: state_seen(values, VoiceState.READY))

        assert not harness.session.complete(request_id, "succeeded", "stale")
    finally:
        harness.close()


def test_bounded_audio_queue_drops_oldest_chunks_without_blocking_callback() -> None:
    gate = threading.Event()
    harness = Harness(gate=gate, queue_chunks=2)
    try:
        harness.stream.push(1.0)
        harness.events_until(lambda events: state_seen(events, VoiceState.CONNECTING))
        for index in range(20):
            harness.stream.push(index / 100)

        assert harness.session.dropped_audio_chunks > 0
    finally:
        gate.set()
        harness.close()


def test_audio_capture_loss_is_counted_and_reported() -> None:
    harness = Harness()
    try:
        harness.stream.push(
            0.1,
            AudioCaptureStatus(input_overflow=True, dropped_chunks=1),
        )
        events = harness.events_until(
            lambda values: any("Microphone lost" in event.detail for event in values)
        )

        assert harness.session.capture_overflows == 1
        assert harness.session.capture_dropped_chunks == 1
        assert any("wake recognition may miss words" in event.detail for event in events)
    finally:
        harness.close()


def test_audio_is_discarded_without_loss_warnings_while_request_is_processing() -> None:
    harness = Harness(queue_chunks=2)
    try:
        harness.stream.push(1.0)
        harness.events_until(lambda events: state_seen(events, VoiceState.LISTENING))
        harness.transport.inbound.put(
            {"message_type": "committed_transcript", "text": "edit test.py"}
        )
        events = harness.events_until(
            lambda values: any(event.type == VoiceEventType.REQUEST for event in values)
        )
        request_id = next(
            event.request_id for event in events if event.type == VoiceEventType.REQUEST
        )
        assert request_id is not None

        for index in range(20):
            harness.stream.push(index / 100)
        sleep(0.05)

        assert harness.session.dropped_audio_chunks == 0
        assert not any("Microphone lost" in event.detail for event in harness.session.poll())
        assert harness.session.complete(request_id, "failed")
        harness.events_until(lambda values: state_seen(values, VoiceState.READY))
    finally:
        harness.close()


def test_pause_stops_wake_detection_until_explicit_resume() -> None:
    harness = Harness()
    try:
        harness.session.set_paused(True)
        harness.events_until(lambda events: state_seen(events, VoiceState.PAUSED))
        harness.stream.push(1.0)
        sleep(0.05)
        assert not harness.transport.connected

        harness.session.set_paused(False)
        harness.events_until(lambda events: state_seen(events, VoiceState.READY))
        harness.stream.push(1.0)
        harness.events_until(lambda events: state_seen(events, VoiceState.LISTENING))
        assert harness.transport.connected
    finally:
        harness.close()


def test_tts_failure_does_not_undo_completion_or_prevent_rearming() -> None:
    speaker = FakeSpeaker(fail=True)
    harness = Harness(speaker=speaker)
    try:
        harness.stream.push(1.0)
        harness.events_until(lambda events: state_seen(events, VoiceState.LISTENING))
        harness.transport.inbound.put(
            {"message_type": "committed_transcript", "text": "change the function"}
        )
        events = harness.events_until(
            lambda values: any(event.type == VoiceEventType.REQUEST for event in values)
        )
        request_id = next(
            event.request_id for event in events if event.type == VoiceEventType.REQUEST
        )
        assert request_id is not None
        harness.session.complete(request_id, "succeeded", "Updated one function.")
        completed = harness.events_until(lambda values: state_seen(values, VoiceState.READY))

        assert state_seen(completed, VoiceState.ERROR)
        assert any(
            event.state == VoiceState.READY and "speaker failed" in event.detail
            for event in completed
        )
        assert harness.session.state == VoiceState.READY
    finally:
        harness.close()


def test_unavailable_tts_disables_spoken_feedback_without_erroring_completion() -> None:
    speaker = FakeSpeaker(unavailable=True)
    harness = Harness(speaker=speaker)
    try:
        harness.stream.push(1.0)
        harness.events_until(lambda events: state_seen(events, VoiceState.LISTENING))
        harness.transport.inbound.put(
            {"message_type": "committed_transcript", "text": "create test.py"}
        )
        events = harness.events_until(
            lambda values: any(event.type == VoiceEventType.REQUEST for event in values)
        )
        request_id = next(
            event.request_id for event in events if event.type == VoiceEventType.REQUEST
        )
        assert request_id is not None

        assert harness.session.complete(request_id, "succeeded", "Created test.py")
        completed = harness.events_until(lambda values: state_seen(values, VoiceState.READY))

        assert not state_seen(completed, VoiceState.ERROR)
        assert any(
            event.state == VoiceState.READY and "disabled" in event.detail for event in completed
        )
        assert not harness.session.speak("This should remain visual only")
    finally:
        harness.close()


def test_elevenlabs_tts_surfaces_payment_detail_without_exposing_api_key(
    monkeypatch: Any,
) -> None:
    class PaymentRequiredResponse:
        status_code = 402
        headers = {"request-id": "tts-request-123"}

        def __enter__(self) -> PaymentRequiredResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def json(self) -> object:
            return {
                "detail": {
                    "status": "payment_required",
                    "message": "The selected voice requires a paid plan.",
                }
            }

    captured: dict[str, object] = {}

    def post(url: str, **kwargs: object) -> PaymentRequiredResponse:
        captured["url"] = url
        captured.update(kwargs)
        return PaymentRequiredResponse()

    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(post=post))
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace())
    speaker = ElevenLabsTtsSpeaker(
        VoiceSettings(elevenlabs_tts_voice_id="available-voice"),
        "secret-api-key",
    )

    with pytest.raises(SpokenFeedbackUnavailableError) as raised:
        speaker.speak("Done.", threading.Event())

    message = str(raised.value)
    assert "HTTP 402" in message
    assert "payment_required: The selected voice requires a paid plan." in message
    assert "tts-request-123" in message
    assert "secret-api-key" not in message
    assert captured["url"] == (
        "https://api.elevenlabs.io/v1/text-to-speech/available-voice/stream?output_format=pcm_16000"
    )
    assert captured["headers"] == {
        "xi-api-key": "secret-api-key",
        "Content-Type": "application/json",
    }
