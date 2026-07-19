from __future__ import annotations

import json

from chudvis.core.config import AppConfig


def test_config_round_trip(tmp_path) -> None:
    path = tmp_path / "config.json"
    config = AppConfig(camera_index=2, camera_width=640)
    config.gestures.pinch_on = 0.2
    config.ide.navigator_hand = "right"
    config.ide.editor_hand = "left"

    config.save(path)
    loaded = AppConfig.load(path)

    assert loaded.camera_index == 2
    assert loaded.camera_width == 640
    assert loaded.gestures.pinch_on == 0.2
    assert loaded.ide.navigator_hand == "right"
    assert loaded.ide.editor_hand == "left"


def test_legacy_smoothing_config_migrates_to_time_aware_defaults(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "gaze": {
                    "smoothing_slow": 0.2,
                    "smoothing_fast": 0.62,
                    "fast_speed_threshold": 0.06,
                    "stable_speed_threshold": 0.018,
                    "ridge_alpha": 0.02,
                }
            }
        ),
        encoding="utf-8",
    )

    loaded = AppConfig.load(path)

    assert loaded.gaze.smoothing_min_cutoff == 1.25
    assert loaded.gaze.stable_speed_threshold == 0.12
    assert loaded.gaze.ridge_alpha == 1.0


def test_legacy_voice_config_loads_with_streaming_defaults(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"voice": {"enabled": True, "model": "base.en"}}),
        encoding="utf-8",
    )

    loaded = AppConfig.load(path)

    assert loaded.voice.model == "base.en"
    assert loaded.voice.wake_word_enabled
    assert loaded.voice.wake_word_spellings == ["CHUDVIS", "CHUD VIS", "CHUD VIZ"]
    assert loaded.voice.wake_word_score == 1.5
    assert loaded.voice.wake_word_threshold == 0.20
    assert loaded.voice.elevenlabs_stt_model == "scribe_v2_realtime"
    assert loaded.voice.elevenlabs_tts_voice_id == ""
    assert loaded.voice.audio_chunk_ms == 100
    assert loaded.voice.vad_silence_seconds == 1.2


def test_legacy_scroll_activation_distance_is_ignored(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "gestures": {
                    "scroll_activation_distance": 0.035,
                    "scroll_scale": 120.0,
                }
            }
        ),
        encoding="utf-8",
    )

    loaded = AppConfig.load(path)

    assert loaded.gestures.scroll_scale == 120.0
    assert not hasattr(loaded.gestures, "scroll_activation_distance")


def test_legacy_scroll_defaults_migrate_to_continuous_scrolling(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "gestures": {
                    "scroll_deadzone": 0.012,
                    "scroll_activation_distance": 0.035,
                    "scroll_event_interval_seconds": 0.16,
                    "scroll_scale": 55.0,
                }
            }
        ),
        encoding="utf-8",
    )

    loaded = AppConfig.load(path)

    assert loaded.gestures.scroll_deadzone == 0.008
    assert loaded.gestures.scroll_event_interval_seconds == 0.05
    assert loaded.gestures.scroll_scale == 240.0
