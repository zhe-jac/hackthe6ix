from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def default_config_dir() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME")
    return Path(root) / "chudvis" if root else Path.home() / ".config" / "chudvis"


@dataclass(slots=True)
class GestureSettings:
    pinch_on: float = 0.32
    pinch_off: float = 0.46
    pinch_min_seconds: float = 0.05
    pinch_lost_grace_seconds: float = 0.10
    drag_lost_grace_seconds: float = 0.30
    drag_hold_seconds: float = 0.55
    drag_scale: float = 2.0
    scroll_arm_seconds: float = 0.30
    scroll_deadzone: float = 0.012
    scroll_activation_distance: float = 0.035
    scroll_event_interval_seconds: float = 0.16
    scroll_scale: float = 55.0
    open_hold_seconds: float = 1.25
    open_stillness: float = 0.018
    thumbs_hold_seconds: float = 0.65
    event_cooldown_seconds: float = 0.45


@dataclass(slots=True)
class GazeSettings:
    smoothing_median_window: int = 3
    smoothing_min_cutoff: float = 1.25
    smoothing_beta: float = 8.0
    smoothing_derivative_cutoff: float = 1.0
    smoothing_deadzone: float = 0.0035
    stable_speed_threshold: float = 0.12
    minimum_confidence: float = 0.55
    max_sample_age_seconds: float = 0.30
    ridge_alpha: float = 1.0


@dataclass(slots=True)
class VoiceSettings:
    enabled: bool = True
    wake_word_enabled: bool = True
    wake_word_cache_dir: str = ""
    wake_word_score: float = 1.5
    wake_word_threshold: float = 0.20
    wake_word_spellings: list[str] = field(
        default_factory=lambda: ["CHUDVIS", "CHUD VIS", "CHUD VIZ"]
    )
    input_device: str = ""
    elevenlabs_api_key_env: str = "ELEVENLABS_API_KEY"
    elevenlabs_stt_model: str = "scribe_v2_realtime"
    elevenlabs_stt_url: str = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
    elevenlabs_tts_enabled: bool = True
    elevenlabs_tts_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_tts_model: str = "eleven_flash_v2_5"
    audio_chunk_ms: int = 100
    vad_silence_seconds: float = 1.2
    no_speech_timeout_seconds: float = 8.0
    max_request_seconds: float = 30.0
    network_timeout_seconds: float = 10.0
    max_transcript_chars: int = 16_000
    audio_queue_chunks: int = 128
    model: str = "tiny.en"
    sample_rate: int = 16000
    device: str = "cpu"
    compute_type: str = "int8"


@dataclass(slots=True)
class TrackingSettings:
    face_detection_confidence: float = 0.5
    face_presence_confidence: float = 0.5
    face_tracking_confidence: float = 0.5
    hand_detection_confidence: float = 0.72
    hand_presence_confidence: float = 0.72
    hand_tracking_confidence: float = 0.65
    hand_confirmation_frames: int = 3
    hand_candidate_max_jump: float = 0.25
    gaze_ear_history_frames: int = 50
    gaze_blink_threshold_ratio: float = 0.80
    gaze_blink_min_history_frames: int = 15
    gaze_full_confidence_inter_eye_distance: float = 0.08


@dataclass(slots=True)
class IdeSettings:
    editor: str = "vscode"
    host: str = "127.0.0.1"
    port: int = 8765
    session_token: str = ""
    navigator_hand: str = "left"
    editor_hand: str = "right"
    navigation_cooldown_seconds: float = 0.35
    selection_timeout_seconds: float = 0.60
    reconnect_delay_seconds: float = 1.0
    max_message_bytes: int = 262_144


@dataclass(slots=True)
class AppConfig:
    camera_index: int = 0
    camera_width: int = 1280
    camera_height: int = 720
    camera_fps: int = 30
    camera_fourcc: str = "MJPG"
    mirror_camera: bool = True
    gaze: GazeSettings = field(default_factory=GazeSettings)
    gestures: GestureSettings = field(default_factory=GestureSettings)
    tracking: TrackingSettings = field(default_factory=TrackingSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    ide: IdeSettings = field(default_factory=IdeSettings)

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        path = path or default_config_dir() / "config.json"
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        gaze_data = dict(data.get("gaze", {}))
        legacy_smoothing = any(
            key in gaze_data
            for key in ("smoothing_slow", "smoothing_fast", "fast_speed_threshold")
        )
        for legacy_key in ("smoothing_slow", "smoothing_fast", "fast_speed_threshold"):
            gaze_data.pop(legacy_key, None)
        if legacy_smoothing:
            gaze_data.pop("stable_speed_threshold", None)
            gaze_data.pop("ridge_alpha", None)
        return cls(
            camera_index=int(data.get("camera_index", 0)),
            camera_width=int(data.get("camera_width", 1280)),
            camera_height=int(data.get("camera_height", 720)),
            camera_fps=int(data.get("camera_fps", 30)),
            camera_fourcc=str(data.get("camera_fourcc", "MJPG")),
            mirror_camera=bool(data.get("mirror_camera", True)),
            gaze=GazeSettings(**gaze_data),
            gestures=GestureSettings(**data.get("gestures", {})),
            tracking=TrackingSettings(**data.get("tracking", {})),
            voice=VoiceSettings(**data.get("voice", {})),
            ide=IdeSettings(**data.get("ide", {})),
        )

    def save(self, path: Path | None = None) -> Path:
        path = path or default_config_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        return path

    def merged(self, values: dict[str, Any]) -> AppConfig:
        """Apply supported command-line overrides without mutating the loaded config."""
        data = asdict(self)
        for key, value in values.items():
            if value is not None and key in data:
                data[key] = value
        return AppConfig(
            camera_index=data["camera_index"],
            camera_width=data["camera_width"],
            camera_height=data["camera_height"],
            camera_fps=data["camera_fps"],
            camera_fourcc=data["camera_fourcc"],
            mirror_camera=data["mirror_camera"],
            gaze=GazeSettings(**data["gaze"]),
            gestures=GestureSettings(**data["gestures"]),
            tracking=TrackingSettings(**data["tracking"]),
            voice=VoiceSettings(**data["voice"]),
            ide=IdeSettings(**data["ide"]),
        )
