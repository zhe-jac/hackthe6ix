from __future__ import annotations

import sys
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

    def start(self) -> None:
        import cv2

        if sys.platform.startswith("linux"):
            capture = cv2.VideoCapture(self.index, cv2.CAP_V4L2)
        else:
            capture = cv2.VideoCapture(self.index)
        if len(self.fourcc) == 4:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_FPS, self.fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not capture.isOpened():
            capture.release()
            raise CameraError(f"Could not open camera index {self.index}")
        self._capture = capture

    def read(self) -> Any:
        if self._capture is None:
            raise CameraError("Camera has not been started")

        import cv2

        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise CameraError("Camera did not return a frame")
        return cv2.flip(frame, 1) if self.mirror else frame

    def stop(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def __enter__(self) -> OpenCVCamera:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
