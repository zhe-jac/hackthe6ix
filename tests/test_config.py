from __future__ import annotations

import json

from gazemotion.core.config import AppConfig


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
