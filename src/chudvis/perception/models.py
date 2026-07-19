from __future__ import annotations

import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

MODEL_URLS = {
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task"
    ),
    "hand_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
        "hand_landmarker/float16/1/hand_landmarker.task"
    ),
}


def default_model_dir() -> Path:
    root = os.environ.get("XDG_CACHE_HOME")
    return (
        Path(root) / "chudvis" / "models"
        if root
        else Path.home() / ".cache" / "chudvis" / "models"
    )


def ensure_model(name: str, directory: Path | None = None) -> Path:
    if name not in MODEL_URLS:
        raise ValueError(f"Unknown model asset: {name}")
    directory = directory or default_model_dir()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / name
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    print(f"Downloading MediaPipe model {name}...")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            with urllib.request.urlopen(MODEL_URLS[name], timeout=60) as response:
                shutil.copyfileobj(response, temporary)
        temporary_path.replace(destination)
    except Exception as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Could not download {name}. Check the network connection and retry."
        ) from exc
    return destination
