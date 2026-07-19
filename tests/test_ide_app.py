from __future__ import annotations

from typing import Any

from chudvis.actions.base import RecordingInputAdapter
from chudvis.core.config import AppConfig
from chudvis.ide import app as app_module
from chudvis.ide.app import ChudvisIdeApplication
from chudvis.perception.mediapipe_tracker import PerceptionResult


def test_runtime_ready_waits_for_microphone_and_first_tracked_frame(monkeypatch: Any) -> None:
    events: list[str] = []

    class FakeCamera:
        latest_frame_at = 1.0

        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeCamera:
            events.append("camera started")
            return self

        def __exit__(self, *_args: object) -> None:
            events.append("camera stopped")

        def read(self) -> object:
            events.append("camera frame")
            return object()

    class FakeTracker:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeTracker:
            events.append("tracker started")
            return self

        def __exit__(self, *_args: object) -> None:
            events.append("tracker stopped")

        def process(self, _frame: object, _timestamp: float) -> PerceptionResult:
            events.append("frame tracked")
            return PerceptionResult(None, 0.0, None)

    class FakeVoiceSession:
        def start(self) -> None:
            events.append("microphone started")

        def close(self) -> None:
            events.append("microphone stopped")

    class FakeController:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def poll(self) -> None:
            events.append("controller polled")

        def shutdown(self) -> None:
            events.append("controller stopped")

    class FakeGestures:
        def __init__(self, *_args: object) -> None:
            pass

        def update(self, _hands: object, _timestamp: float) -> tuple[()]:
            return ()

    class FakeAdapter:
        @property
        def connected(self) -> bool:
            return True

        def runtime_ready(self, detail: str) -> None:
            events.append("runtime ready")
            ready_details.append(detail)
            application.stop()

    monkeypatch.setattr(app_module, "OpenCVCamera", FakeCamera)
    monkeypatch.setattr(app_module, "MediaPipeTracker", FakeTracker)
    monkeypatch.setattr(app_module, "AdaptiveGazeSmoother", lambda **_kwargs: object())
    monkeypatch.setattr(app_module, "GazeEstimator", lambda *_args: object())
    monkeypatch.setattr(app_module, "HandGestureRouter", FakeGestures)
    monkeypatch.setattr(app_module, "IdeInteractionController", FakeController)

    ready_details: list[str] = []
    application = ChudvisIdeApplication(
        AppConfig(),
        object(),  # type: ignore[arg-type]
        RecordingInputAdapter(),
        FakeAdapter(),  # type: ignore[arg-type]
        (1920, 1080),
        voice_session=FakeVoiceSession(),  # type: ignore[arg-type]
    )

    application.run()

    assert ready_details == ["Camera, microphone, and backend are ready"]
    assert events.index("microphone started") < events.index("runtime ready")
    assert events.index("camera frame") < events.index("runtime ready")
    assert events.index("frame tracked") < events.index("runtime ready")
