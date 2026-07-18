from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def default_config_dir() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME")
    return Path(root) / "gazemotion" if root else Path.home() / ".config" / "gazemotion"


@dataclass(slots=True)
class GestureSettings:
    pinch_on: float = 0.32
    pinch_off: float = 0.46
    pinch_min_seconds: float = 0.05
    hand_lost_grace_seconds: float = 0.30
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
    smoothing_slow: float = 0.20
    smoothing_fast: float = 0.62
    fast_speed_threshold: float = 0.06
    stable_speed_threshold: float = 0.018
    minimum_confidence: float = 0.55
    max_sample_age_seconds: float = 0.30
    ridge_alpha: float = 0.02


@dataclass(slots=True)
class VoiceSettings:
    enabled: bool = True
    provider: str = "local"  # "auto", "elevenlabs", or "local"
    api_key_env: str = "ELEVENLABS_API_KEY"
    elevenlabs_model: str = "scribe_v1"
    model: str = "tiny.en"
    sample_rate: int = 16000
    device: str = "cpu"
    compute_type: str = "int8"


@dataclass(slots=True)
class AgentSettings:
    """Voice command agent that turns transcripts into desktop actions.

    Experimental: disabled by default until the core gesture experience is solid.
    """

    enabled: bool = False
    provider: str = "backboard"  # "backboard", "openai-compatible", or "rules"
    api_key_env: str = "BACKBOARD_API_KEY"
    llm_provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    memory: str = "Auto"
    base_url: str = "https://app.backboard.io/api"
    openai_base_url: str = "http://127.0.0.1:8000/v1"
    openai_model: str = "gazemotion-intents"
    openai_api_key_env: str = "FREESOLO_API_KEY"
    request_timeout_seconds: float = 12.0


@dataclass(slots=True)
class SpeechOutputSettings:
    """Spoken feedback through the ElevenLabs text-to-speech API.

    Experimental: disabled by default until the core gesture experience is solid.
    """

    enabled: bool = False
    api_key_env: str = "ELEVENLABS_API_KEY"
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    model_id: str = "eleven_flash_v2_5"
    output_format: str = "pcm_16000"
    sample_rate: int = 16000
    request_timeout_seconds: float = 10.0
    duplicate_window_seconds: float = 2.0


@dataclass(slots=True)
class WellnessSettings:
    """Contactless vitals monitoring through the Presage Physiology API.

    Experimental: disabled by default until the core gesture experience is solid.
    """

    enabled: bool = False
    api_key_env: str = "PRESAGE_API_KEY"
    clip_seconds: float = 20.0
    clip_fps: int = 15
    interval_seconds: float = 180.0
    first_sample_delay_seconds: float = 20.0
    poll_interval_seconds: float = 10.0
    poll_timeout_seconds: float = 240.0
    pulse_alert_ratio: float = 1.20
    breathing_alert_ratio: float = 1.25
    break_reminder_minutes: float = 25.0
    auto_pause_on_alert: bool = False


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
    agent: AgentSettings = field(default_factory=AgentSettings)
    speech_output: SpeechOutputSettings = field(default_factory=SpeechOutputSettings)
    wellness: WellnessSettings = field(default_factory=WellnessSettings)

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        path = path or default_config_dir() / "config.json"
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            camera_index=int(data.get("camera_index", 0)),
            camera_width=int(data.get("camera_width", 1280)),
            camera_height=int(data.get("camera_height", 720)),
            camera_fps=int(data.get("camera_fps", 30)),
            camera_fourcc=str(data.get("camera_fourcc", "MJPG")),
            mirror_camera=bool(data.get("mirror_camera", True)),
            gaze=GazeSettings(**data.get("gaze", {})),
            gestures=GestureSettings(**data.get("gestures", {})),
            tracking=TrackingSettings(**data.get("tracking", {})),
            voice=VoiceSettings(**data.get("voice", {})),
            agent=AgentSettings(**data.get("agent", {})),
            speech_output=SpeechOutputSettings(**data.get("speech_output", {})),
            wellness=WellnessSettings(**data.get("wellness", {})),
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
            agent=AgentSettings(**data["agent"]),
            speech_output=SpeechOutputSettings(**data["speech_output"]),
            wellness=WellnessSettings(**data["wellness"]),
        )
