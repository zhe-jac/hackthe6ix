from __future__ import annotations

from typing import Any


def window_is_open(cv2: Any, name: str) -> bool:
    """Return false when a user closes an OpenCV window with its window controls."""
    try:
        return cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) >= 1
    except cv2.error:
        return False


def close_window(cv2: Any, name: str) -> None:
    """Destroy a window if it still exists without masking application shutdown."""
    try:
        cv2.destroyWindow(name)
    except cv2.error:
        pass
