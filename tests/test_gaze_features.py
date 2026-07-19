from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from chudvis.gaze.features import FEATURE_COUNT, HeadNormalizedGazeExtractor


@dataclass(frozen=True)
class _Landmark:
    x: float
    y: float
    z: float


def _face(eye_height: float = 0.04) -> tuple[_Landmark, ...]:
    points = [
        _Landmark(
            0.35 + (index % 24) * 0.012,
            0.30 + (index // 24) * 0.012,
            ((index % 7) - 3) * 0.002,
        )
        for index in range(478)
    ]
    points[33] = _Landmark(0.40, 0.50, 0.0)
    points[133] = _Landmark(0.47, 0.50, 0.0)
    points[159] = _Landmark(0.435, 0.50 - eye_height / 2.0, 0.0)
    points[145] = _Landmark(0.435, 0.50 + eye_height / 2.0, 0.0)
    points[362] = _Landmark(0.53, 0.50, 0.0)
    points[263] = _Landmark(0.60, 0.50, 0.0)
    points[386] = _Landmark(0.565, 0.50 - eye_height / 2.0, 0.0)
    points[374] = _Landmark(0.565, 0.50 + eye_height / 2.0, 0.0)
    points[10] = _Landmark(0.50, 0.25, 0.01)
    return tuple(points)


def test_head_normalized_features_have_expected_size_and_are_scale_invariant() -> None:
    face = _face()
    transformed = tuple(
        _Landmark(
            point.x * 1.7 + 0.2,
            point.y * 1.7 - 0.1,
            point.z * 1.7 + 0.05,
        )
        for point in face
    )

    first = HeadNormalizedGazeExtractor().extract(face)
    second = HeadNormalizedGazeExtractor().extract(transformed)

    assert first.features is not None
    assert second.features is not None
    assert len(first.features.values) == FEATURE_COUNT == 486
    assert np.allclose(first.features.values, second.features.values, atol=1e-9)


def test_adaptive_blink_detection_suppresses_gaze_features() -> None:
    extractor = HeadNormalizedGazeExtractor(blink_min_history_frames=5)
    for _ in range(5):
        open_observation = extractor.extract(_face(eye_height=0.04))
        assert open_observation.features is not None

    blink = extractor.extract(_face(eye_height=0.002))

    assert blink.blink_detected is True
    assert blink.features is None
    assert blink.confidence == 0.0
    for _ in range(30):
        sustained_blink = extractor.extract(_face(eye_height=0.002))
        assert sustained_blink.blink_detected is True
        assert sustained_blink.features is None
