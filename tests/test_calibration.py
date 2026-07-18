from __future__ import annotations

import pytest

from gazemotion.core.events import GazeFeatures, Point
from gazemotion.gaze.training import TargetSamples, flatten_balanced_groups, robust_sample_subset
from gazemotion.ui.calibration import dense_grid_targets


def test_dense_grid_is_serpentine_and_respects_margin() -> None:
    targets = dense_grid_targets(5, margin=0.1)

    assert len(targets) == 25
    assert targets[0] == Point(0.1, 0.1)
    assert targets[4] == Point(0.9, 0.1)
    assert targets[5].x == pytest.approx(0.9)
    assert targets[5].y == pytest.approx(0.3)
    assert targets[9].x == pytest.approx(0.1)
    assert targets[9].y == pytest.approx(0.3)
    assert targets[-1] == Point(0.9, 0.9)


def test_robust_sample_subset_rejects_feature_outlier() -> None:
    samples = [GazeFeatures((0.50 + index * 0.001, 0.25)) for index in range(10)]
    outlier = GazeFeatures((50.0, -40.0))
    samples.insert(5, outlier)

    selected = robust_sample_subset(samples, maximum_samples=8, minimum_samples=4)

    assert len(selected) == 8
    assert outlier not in selected


def test_flatten_balanced_groups_gives_every_target_equal_weight() -> None:
    groups = [
        TargetSamples(Point(0.1, 0.1), (GazeFeatures((0.0,)),) * 6),
        TargetSamples(Point(0.9, 0.9), (GazeFeatures((1.0,)),) * 4),
    ]

    flattened = flatten_balanced_groups(groups)

    assert len(flattened) == 8
    assert sum(target == Point(0.1, 0.1) for _, target in flattened) == 4
    assert sum(target == Point(0.9, 0.9) for _, target in flattened) == 4
