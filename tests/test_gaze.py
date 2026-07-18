from __future__ import annotations

from gazemotion.core.events import GazeFeatures, Point
from gazemotion.gaze.model import AdaptiveGazeSmoother, CalibrationProfile


def test_calibration_fits_linear_mapping() -> None:
    samples = [
        (GazeFeatures((0.0, 0.0)), Point(0.0, 0.0)),
        (GazeFeatures((1.0, 0.0)), Point(1.0, 0.0)),
        (GazeFeatures((0.0, 1.0)), Point(0.0, 1.0)),
        (GazeFeatures((1.0, 1.0)), Point(1.0, 1.0)),
    ]
    profile = CalibrationProfile.fit(samples, (1920, 1080), alpha=0.0)

    predicted = profile.predict(GazeFeatures((0.25, 0.75)))

    assert abs(predicted.x - 0.25) < 1e-6
    assert abs(predicted.y - 0.75) < 1e-6


def test_calibration_clamps_predictions_to_screen() -> None:
    samples = [
        (GazeFeatures((0.0,)), Point(0.0, 0.0)),
        (GazeFeatures((0.5,)), Point(0.5, 0.5)),
        (GazeFeatures((1.0,)), Point(1.0, 1.0)),
    ]
    profile = CalibrationProfile.fit(samples, (100, 100), alpha=0.0)

    assert profile.predict(GazeFeatures((-2.0,))) == Point(0.0, 0.0)
    assert profile.predict(GazeFeatures((2.0,))) == Point(1.0, 1.0)


def test_smoother_marks_small_motion_stable() -> None:
    smoother = AdaptiveGazeSmoother(stable_speed_threshold=0.02)

    first, first_stable = smoother.update(Point(0.5, 0.5))
    second, second_stable = smoother.update(Point(0.505, 0.505))

    assert first == Point(0.5, 0.5)
    assert first_stable is False
    assert second_stable is True
    assert 0.5 < second.x < 0.505
