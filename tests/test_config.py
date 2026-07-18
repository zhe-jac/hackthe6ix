from __future__ import annotations

from gazemotion.core.config import AppConfig


def test_config_round_trip(tmp_path) -> None:
    path = tmp_path / "config.json"
    config = AppConfig(camera_index=2, camera_width=640)
    config.gestures.pinch_on = 0.2

    config.save(path)
    loaded = AppConfig.load(path)

    assert loaded.camera_index == 2
    assert loaded.camera_width == 640
    assert loaded.gestures.pinch_on == 0.2
