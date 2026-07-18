from __future__ import annotations

import numpy as np

from gazemotion.core.config import AppConfig
from gazemotion.core.events import GazeFeatures
from gazemotion.gaze.model import CalibrationProfile
from gazemotion.perception.mediapipe_tracker import PerceptionResult
from gazemotion.ui.diagnostics import DiagnosticDashboard


class FakeTracker:
    def draw_debug(self, frame, _result):
        return frame


def test_dashboard_renders_without_calibration_or_detections() -> None:
    dashboard = DiagnosticDashboard(AppConfig(), profile=None)
    result = PerceptionResult(None, 0.0, None, None)
    dashboard.update(result, 1.0)

    rendered = dashboard.render(
        np.zeros((480, 640, 3), dtype=np.uint8),
        FakeTracker(),
        result,
        10.0,
    )

    assert rendered.shape == (900, 1760, 3)
    assert dashboard.frames == 1
    assert dashboard.last_gaze is None


def test_dashboard_estimates_gaze_when_profile_is_loaded() -> None:
    profile = CalibrationProfile(
        weights_x=[0.0] * 9 + [0.25],
        weights_y=[0.0] * 9 + [0.75],
        feature_count=9,
        screen_width=1920,
        screen_height=1080,
        camera_index=0,
        created_at="2026-07-18T00:00:00+00:00",
    )
    dashboard = DiagnosticDashboard(AppConfig(), profile)
    result = PerceptionResult(GazeFeatures((0.0,) * 9), 0.9, None, None)

    dashboard.update(result, 1.0)

    assert dashboard.last_gaze is not None
    assert dashboard.last_gaze.point.x == 0.25
    assert dashboard.last_gaze.point.y == 0.75
