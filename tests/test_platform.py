from __future__ import annotations

from chudvis.core.platform import is_wsl, list_video_devices


def test_is_wsl_detects_wsl_environment(monkeypatch) -> None:
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")

    assert is_wsl()


def test_list_video_devices(tmp_path) -> None:
    (tmp_path / "video2").touch()
    (tmp_path / "video0").touch()
    (tmp_path / "not-video").touch()

    assert [path.name for path in list_video_devices(tmp_path)] == ["video0", "video2"]
