from __future__ import annotations

import queue
import threading
from time import monotonic, sleep
from typing import Any

import numpy as np

from chudvis.core.config import VoiceSettings
from chudvis.speech.realtime_voice import (
    VoiceEvent,
    VoiceEventType,
    VoiceSession,
    VoiceState,
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

    def push(self, value: float) -> None:
        samples = np.full((1600, 1), value, dtype=np.float32)
        self.callback(samples, len(samples), None, None)

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


class FakeSpeaker:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.spoken: list[str] = []

    def speak(self, text: str, cancelled: threading.Event) -> None:
        assert not cancelled.is_set()
        self.spoken.append(text)
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
            event.type == VoiceEventType.PARTIAL and event.text == "open"
            for event in events
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
        assert harness.session.state == VoiceState.READY
    finally:
        harness.close()
