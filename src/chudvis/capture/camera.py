from __future__ import annotations

import sys
from threading import Condition, Event, Thread
from time import monotonic
from typing import Any


class CameraError(RuntimeError):
    pass


class OpenCVCamera:
    def __init__(
        self,
        index: int = 0,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        fourcc: str = "MJPG",
        mirror: bool = True,
    ) -> None:
        self.index = index
        self.width = width
        self.height = height
        self.fps = fps
        self.fourcc = fourcc
        self.mirror = mirror
        self._capture: Any | None = None
        self._reader: Thread | None = None
        self._stop_reader = Event()
        self._frame_ready = Condition()
        self._latest_frame: Any | None = None
        self._latest_frame_at = 0.0
        self._read_frame_at = 0.0
        self._latest_sequence = 0
        self._read_sequence = 0
        self._reader_error: CameraError | None = None
        self._dropped_frames = 0

    def start(self) -> None:
        import cv2

        if self._capture is not None or (self._reader is not None and self._reader.is_alive()):
            raise CameraError("Camera has already been started")
        if sys.platform.startswith("linux"):
            capture = cv2.VideoCapture(self.index, cv2.CAP_V4L2)
        else:
            capture = cv2.VideoCapture(self.index)
        if len(self.fourcc) == 4:
            capture.set(
                cv2.CAP_PROP_FOURCC,
                cv2.VideoWriter_fourcc(*self.fourcc),  # type: ignore[attr-defined]
            )
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_FPS, self.fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not capture.isOpened():
            capture.release()
            raise CameraError(f"Could not open camera index {self.index}")
        self._capture = capture

        self._stop_reader = Event()
        with self._frame_ready:
            self._latest_frame = None
            self._latest_frame_at = 0.0
            self._read_frame_at = 0.0
            self._latest_sequence = 0
            self._read_sequence = 0
            self._reader_error = None
            self._dropped_frames = 0
        self._reader = Thread(
            target=self._capture_latest_frames,
            args=(capture, self._stop_reader),
            name=f"chudvis-camera-{self.index}",
            daemon=True,
        )
        self._reader.start()

    def _capture_latest_frames(self, capture: Any, stop_reader: Event) -> None:
        """Continuously drain the driver and retain only the newest camera frame."""
        consecutive_failures = 0
        while not stop_reader.is_set():
            try:
                ok, frame = capture.read()
            except Exception as exc:
                with self._frame_ready:
                    self._reader_error = CameraError(f"Camera read failed: {exc}")
                    self._frame_ready.notify_all()
                return

            if not ok or frame is None:
                consecutive_failures += 1
                if consecutive_failures < 3:
                    stop_reader.wait(0.01)
                    continue
                with self._frame_ready:
                    if not stop_reader.is_set():
                        self._reader_error = CameraError("Camera did not return a frame")
                    self._frame_ready.notify_all()
                return

            consecutive_failures = 0
            captured_at = monotonic()
            with self._frame_ready:
                self._latest_frame = frame
                self._latest_frame_at = captured_at
                self._latest_sequence += 1
                self._frame_ready.notify_all()

    def read(self, timeout_seconds: float = 2.0) -> Any:
        if self._capture is None:
            raise CameraError("Camera has not been started")
        if timeout_seconds <= 0.0:
            raise ValueError("Camera read timeout must be positive")

        deadline = monotonic() + timeout_seconds
        with self._frame_ready:
            while (
                self._latest_sequence <= self._read_sequence
                and self._reader_error is None
                and not self._stop_reader.is_set()
            ):
                remaining = deadline - monotonic()
                if remaining <= 0.0:
                    raise CameraError(
                        f"Camera index {self.index} did not produce a fresh frame within "
                        f"{timeout_seconds:.1f}s"
                    )
                self._frame_ready.wait(remaining)

            if self._reader_error is not None:
                raise self._reader_error
            if self._latest_frame is None or self._latest_sequence <= self._read_sequence:
                raise CameraError("Camera stopped before returning a fresh frame")

            skipped = self._latest_sequence - self._read_sequence - 1
            if self._read_sequence > 0:
                self._dropped_frames += max(skipped, 0)
            self._read_sequence = self._latest_sequence
            frame = self._latest_frame
            self._read_frame_at = self._latest_frame_at

        import cv2

        return cv2.flip(frame, 1) if self.mirror else frame

    @property
    def latest_frame_at(self) -> float:
        """Monotonic timestamp recorded when the latest delivered frame was captured."""
        with self._frame_ready:
            return self._read_frame_at

    @property
    def dropped_frames(self) -> int:
        """Frames intentionally skipped to keep inference on the live camera edge."""
        with self._frame_ready:
            return self._dropped_frames

    def stop(self) -> None:
        capture = self._capture
        reader = self._reader
        if capture is None and reader is None:
            return

        self._stop_reader.set()
        with self._frame_ready:
            self._frame_ready.notify_all()
        if capture is not None:
            capture.release()
        if reader is not None and reader.is_alive():
            reader.join(timeout=2.0)
        self._reader = None
        self._capture = None

    def __enter__(self) -> OpenCVCamera:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
