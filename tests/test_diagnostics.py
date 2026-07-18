from __future__ import annotations

import numpy as np

from gazemotion.core.config import AppConfig
from gazemotion.core.events import GazeFeatures, HandObservation, Point
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


def _hand_result(kind: str, timestamp: float) -> PerceptionResult:
    points = [Point(0.5, 0.7) for _ in range(21)]
    points[0] = Point(0.5, 0.9)
    points[5] = Point(0.4, 0.62)
    points[9] = Point(0.5, 0.58)
    points[13] = Point(0.56, 0.62)
    points[17] = Point(0.6, 0.66)
    if kind == "pinch":
        points[4] = Point(0.49, 0.45)
        points[8] = Point(0.51, 0.45)
    else:
        points[4] = Point(0.3, 0.65)
        points[8] = Point(0.7, 0.75)
        for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
            points[pip] = Point(points[tip].x, 0.64)
            points[tip] = Point(points[tip].x, 0.76)
    hand = HandObservation(tuple(points), "right", 0.95, timestamp)
    return PerceptionResult(None, 0.0, hand, None)


def test_practice_cards_track_completed_gestures() -> None:
    dashboard = DiagnosticDashboard(AppConfig(), profile=None)

    dashboard.update(_hand_result("pinch", 0.0), 0.0)
    dashboard.update(_hand_result("neutral", 0.2), 0.2)

    assert dashboard.completed_at["click"] == 0.2
    assert dashboard.completed_at["drag"] is None


def test_practice_card_reports_tracking_grace() -> None:
    dashboard = DiagnosticDashboard(AppConfig(), profile=None)
    dashboard.update(_hand_result("pinch", 0.0), 0.0)
    dashboard.update(PerceptionResult(None, 0.0, None, None), 0.02)

    status, _progress = dashboard._card_state(
        "click", dashboard.gestures.hold_progress(0.02)
    )

    assert "tracking lost" in status


def test_dashboard_estimates_gaze_when_profile_is_loaded() -> None:
    profile = CalibrationProfile(
        weights_x=[0.0] * 9 + [0.25],
        weights_y=[0.0] * 9 + [0.75],
        feature_means=[0.0] * 9,
        feature_scales=[1.0] * 9,
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
    assert dashboard.full_gaze_overlay is True
    assert dashboard._gaze_canvas_point() == (440, 675)

    dashboard.set_gaze_overlay_geometry((1920, 1080), (100, 50, 1760, 900))

    assert dashboard._gaze_canvas_point() == (380, 760)
    assert dashboard.toggle_gaze_overlay() is False
