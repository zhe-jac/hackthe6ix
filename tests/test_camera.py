from __future__ import annotations

from queue import Queue
from threading import Event

import cv2
import numpy as np

from chudvis.capture.camera import OpenCVCamera


class _FakeCapture:
    def __init__(self) -> None:
        self.frames: Queue[object] = Queue()
        self.read_count = 0
        self.expected_reads = 0
        self.reads_complete = Event()
        self.released = False
        self._stop = object()

    def set(self, _property: int, _value: object) -> bool:
        return True

    def isOpened(self) -> bool:  # noqa: N802 - OpenCV API spelling
        return True

    def read(self):
        frame = self.frames.get(timeout=2.0)
        if frame is self._stop:
            return False, None
        self.read_count += 1
        if self.read_count >= self.expected_reads:
            self.reads_complete.set()
        return True, frame

    def release(self) -> None:
        if not self.released:
            self.released = True
            self.frames.put(self._stop)

    def push(self, *values: int) -> None:
        self.expected_reads = self.read_count + len(values)
        self.reads_complete.clear()
        for value in values:
            self.frames.put(np.full((2, 2, 3), value, dtype=np.uint8))


def test_camera_keeps_only_the_latest_frame_when_inference_is_slower(monkeypatch) -> None:
    capture = _FakeCapture()
    monkeypatch.setattr(cv2, "VideoCapture", lambda *_args: capture)
    camera = OpenCVCamera(width=2, height=2, mirror=False)
    camera.start()

    try:
        capture.push(1, 2, 3)
        assert capture.reads_complete.wait(1.0)
        first = camera.read()

        capture.push(4, 5)
        assert capture.reads_complete.wait(1.0)
        second = camera.read()

        assert np.all(first == 3)
        assert np.all(second == 5)
        assert camera.dropped_frames == 1
        assert camera.latest_frame_at > 0.0
    finally:
        camera.stop()

    assert capture.released is True
