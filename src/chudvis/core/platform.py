from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PlatformInfo:
    display_available: bool
    session_type: str
    screen_size: tuple[int, int] | None


def configure_process_for_desktop_input() -> None:
    """Use physical desktop coordinates on Windows before opening any UI."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        # Per-monitor-v2 awareness keeps Tk/OpenCV screen geometry and the
        # absolute pynput controller in the same physical-pixel coordinate space.
        if bool(ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))):
            return
    except (AttributeError, OSError):
        pass
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def get_screen_size() -> tuple[int, int]:
    configure_process_for_desktop_input()
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        size = (int(root.winfo_screenwidth()), int(root.winfo_screenheight()))
        root.destroy()
        return size
    except Exception as exc:
        raise RuntimeError(
            "Could not determine screen size. Ensure a graphical desktop session is active."
        ) from exc


def inspect_platform() -> PlatformInfo:
    display_available = bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or os.name == "nt"
    )
    session_type = os.environ.get("XDG_SESSION_TYPE", "unknown").lower()
    size = None
    if display_available:
        try:
            size = get_screen_size()
        except RuntimeError:
            pass
    return PlatformInfo(display_available, session_type, size)


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in release or "wsl" in release


def list_video_devices(dev_root: Path = Path("/dev")) -> tuple[Path, ...]:
    return tuple(sorted(dev_root.glob("video*")))
