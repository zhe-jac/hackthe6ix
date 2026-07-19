from __future__ import annotations

import json

import pytest

from chudvis.core.events import GazeFeatures, GazeSample, Point
from chudvis.gaze.features import FEATURE_COUNT
from chudvis.gaze.model import (
    KERNEL_MODEL,
    AdaptiveGazeSmoother,
    CalibrationProfile,
    GazeConfidenceGate,
)
from chudvis.gaze.training import TargetSamples, select_best_profile


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
    smoother = AdaptiveGazeSmoother(deadzone=0.0, stable_speed_threshold=0.05)

    first, first_stable = smoother.update(Point(0.5, 0.5), 1.0)
    second, second_stable = smoother.update(Point(0.505, 0.505), 1.1)

    assert first == Point(0.5, 0.5)
    assert first_stable is False
    assert second_stable is True
    assert 0.5 < second.x < 0.505


def test_smoother_holds_fixation_jitter_but_reacts_to_a_large_step() -> None:
    smoother = AdaptiveGazeSmoother()
    outputs = []
    for index in range(20):
        offset = 0.002 if index % 2 else -0.002
        point, _stable = smoother.update(
            Point(0.5 + offset, 0.5 - offset),
            index / 30.0,
        )
        outputs.append(point)

    jitter_span = max(point.x for point in outputs) - min(point.x for point in outputs)
    stepped, _stable = smoother.update(Point(0.85, 0.5), 20 / 30.0)

    assert jitter_span < 0.002
    assert stepped.x > 0.70


def test_confidence_gate_tolerates_only_brief_minor_drops() -> None:
    gate = GazeConfidenceGate(minimum_confidence=0.55, grace_seconds=0.30)

    assert gate.accepts(GazeSample(Point(0.5, 0.5), 0.9, True, 1.0))
    assert gate.accepts(GazeSample(Point(0.6, 0.5), 0.5, True, 1.2))
    assert not gate.accepts(GazeSample(Point(0.7, 0.5), 0.2, True, 1.25))
    assert not gate.accepts(GazeSample(Point(0.8, 0.5), 0.5, True, 1.31))


def test_high_dimensional_ridge_fit_supports_fewer_samples_than_features() -> None:
    samples = [
        (GazeFeatures((value, value**2, value**3, value**4)), Point(value, 1.0 - value))
        for value in (0.0, 0.25, 0.5)
    ]

    profile = CalibrationProfile.fit(samples, (1920, 1080), alpha=1.0)
    prediction = profile.predict(GazeFeatures((0.25, 0.25**2, 0.25**3, 0.25**4)))

    assert profile.feature_count == 4
    assert abs(prediction.x - 0.25) < 0.15
    assert abs(prediction.y - 0.75) < 0.15


def test_loading_an_old_profile_requests_recalibration(tmp_path) -> None:
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "weights_x": [0.0, 0.0],
                "weights_y": [0.0, 0.0],
                "feature_count": 1,
                "screen_width": 100,
                "screen_height": 100,
                "camera_index": 0,
                "created_at": "2025-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="calibrate"):
        CalibrationProfile.load(path)


def test_head_normalized_profile_round_trip(tmp_path) -> None:
    path = tmp_path / "calibration.json"
    samples = []
    for value, target in ((0.0, Point(0.1, 0.1)), (0.5, Point(0.5, 0.5)), (1.0, Point(0.9, 0.9))):
        features = [0.0] * FEATURE_COUNT
        features[0] = value
        samples.append((GazeFeatures(tuple(features)), target))

    fitted = CalibrationProfile.fit(samples, (1920, 1080), alpha=1.0)
    fitted.save(path)
    loaded = CalibrationProfile.load(path)

    assert loaded.feature_count == FEATURE_COUNT
    assert loaded.predict(samples[1][0]) == fitted.predict(samples[1][0])


def test_kernel_profile_round_trip(tmp_path) -> None:
    path = tmp_path / "calibration.json"
    samples = []
    for value in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        features = [0.0] * FEATURE_COUNT
        features[0] = value
        features[1] = value**2
        samples.append((GazeFeatures(tuple(features)), Point(value**2, value)))

    fitted = CalibrationProfile.fit_kernel(samples, (1920, 1080), alpha=0.1)
    fitted.save(path)
    loaded = CalibrationProfile.load(path)
    query = samples[3][0]

    assert loaded.model_type == KERNEL_MODEL
    assert loaded.predict(query) == fitted.predict(query)


def test_model_selection_uses_validation_to_choose_nonlinear_mapping() -> None:
    def features(value: float) -> GazeFeatures:
        return GazeFeatures((value,))

    training = [
        TargetSamples(Point(value**2, value), (features(value),) * 3)
        for value in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    ]
    validation = [
        TargetSamples(Point(value**2, value), (features(value),) * 2)
        for value in (0.1, 0.3, 0.5, 0.7, 0.9)
    ]

    profile = select_best_profile(training, validation, (1000, 1000), 0, 0.1)

    assert profile.model_type == KERNEL_MODEL
    assert profile.validation_target_count == 5
    assert profile.validation_median_error_px is not None
    assert profile.validation_median_error_px < 25.0


def test_model_selection_falls_back_when_kernel_features_are_degenerate() -> None:
    fixed = GazeFeatures((0.5,))
    training = [
        TargetSamples(Point(0.1, 0.1), (fixed,) * 3),
        TargetSamples(Point(0.5, 0.5), (fixed,) * 3),
        TargetSamples(Point(0.9, 0.9), (fixed,) * 3),
    ]
    validation = [TargetSamples(Point(0.5, 0.5), (fixed,) * 2)]

    profile = select_best_profile(training, validation, (1000, 1000), 0, 1.0)

    assert profile.model_type == "linear_ridge"
