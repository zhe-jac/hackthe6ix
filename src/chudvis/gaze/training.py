from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from chudvis.core.events import GazeFeatures, Point
from chudvis.gaze.model import CalibrationProfile


@dataclass(frozen=True, slots=True)
class TargetSamples:
    target: Point
    features: tuple[GazeFeatures, ...]


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    target_count: int
    mean_error_px: float
    median_error_px: float
    p95_error_px: float
    max_error_px: float

    @property
    def selection_score(self) -> float:
        return 0.70 * self.median_error_px + 0.30 * self.p95_error_px


def robust_sample_subset(
    samples: list[GazeFeatures] | tuple[GazeFeatures, ...],
    maximum_samples: int,
    minimum_samples: int,
) -> tuple[GazeFeatures, ...]:
    """Reject inconsistent frames and retain evenly spaced, representative samples."""
    if maximum_samples < minimum_samples or minimum_samples < 1:
        raise ValueError("Sample limits must be positive and maximum must be at least minimum")
    if len(samples) < minimum_samples:
        return ()

    feature_count = len(samples[0].values)
    if any(len(sample.values) != feature_count for sample in samples):
        raise ValueError("All target samples must use the same feature count")
    matrix = np.asarray([sample.values for sample in samples], dtype=float)
    if not np.all(np.isfinite(matrix)):
        raise ValueError("Target samples must contain only finite values")

    median = np.median(matrix, axis=0)
    deviations = np.abs(matrix - median)
    scales = 1.4826 * np.median(deviations, axis=0)
    positive_scales = scales[scales > 1e-9]
    scale_floor = (
        max(float(np.median(positive_scales)) * 0.10, 1e-6) if positive_scales.size else 1e-6
    )
    scales = np.maximum(scales, scale_floor)
    frame_scores = np.median(deviations / scales, axis=1)
    score_median = float(np.median(frame_scores))
    score_mad = float(np.median(np.abs(frame_scores - score_median)))
    cutoff = score_median + max(3.5 * 1.4826 * score_mad, 0.35)
    inlier_indices = np.flatnonzero(frame_scores <= cutoff)

    if inlier_indices.size < minimum_samples:
        inlier_indices = np.argsort(frame_scores)[:minimum_samples]
        inlier_indices.sort()
    retain_count = min(maximum_samples, int(inlier_indices.size))
    positions = np.linspace(0, inlier_indices.size - 1, retain_count, dtype=int)
    selected_indices = inlier_indices[positions]
    return tuple(samples[int(index)] for index in selected_indices)


def flatten_balanced_groups(
    groups: list[TargetSamples] | tuple[TargetSamples, ...],
) -> list[tuple[GazeFeatures, Point]]:
    if not groups:
        raise ValueError("At least one calibration target is required")
    samples_per_target = min(len(group.features) for group in groups)
    if samples_per_target == 0:
        raise ValueError("Every calibration target must have at least one usable sample")

    flattened: list[tuple[GazeFeatures, Point]] = []
    for group in groups:
        positions = np.linspace(0, len(group.features) - 1, samples_per_target, dtype=int)
        flattened.extend((group.features[int(index)], group.target) for index in positions)
    return flattened


def evaluate_profile(
    profile: CalibrationProfile,
    groups: list[TargetSamples] | tuple[TargetSamples, ...],
    screen_size: tuple[int, int],
) -> CalibrationMetrics:
    if not groups:
        raise ValueError("At least one validation target is required")

    width, height = screen_size
    errors: list[float] = []
    for group in groups:
        if not group.features:
            raise ValueError("Every validation target must have usable samples")
        predictions = []
        for features in group.features:
            point = profile.predict(features)
            predictions.append((point.x, point.y))
        prediction_values = np.asarray(predictions, dtype=float)
        predicted = np.median(prediction_values, axis=0)
        dx = (float(predicted[0]) - group.target.x) * width
        dy = (float(predicted[1]) - group.target.y) * height
        errors.append(float(np.hypot(dx, dy)))

    values = np.asarray(errors, dtype=float)
    return CalibrationMetrics(
        target_count=len(groups),
        mean_error_px=float(values.mean()),
        median_error_px=float(np.median(values)),
        p95_error_px=float(np.percentile(values, 95)),
        max_error_px=float(values.max()),
    )


def _alpha_candidates(base_alpha: float) -> tuple[float, ...]:
    if base_alpha < 0.0:
        raise ValueError("Ridge alpha must be non-negative")
    if base_alpha == 0.0:
        values: tuple[float, ...] = (0.0, 0.1, 1.0)
    else:
        values = (base_alpha / 10.0, base_alpha, base_alpha * 10.0)
    return tuple(dict.fromkeys(values))


def _apply_metrics(
    profile: CalibrationProfile,
    metrics: CalibrationMetrics,
    training_groups: list[TargetSamples] | tuple[TargetSamples, ...],
) -> CalibrationProfile:
    profile.calibration_target_count = len(training_groups)
    profile.samples_per_target = min(len(group.features) for group in training_groups)
    profile.validation_target_count = metrics.target_count
    profile.validation_mean_error_px = metrics.mean_error_px
    profile.validation_median_error_px = metrics.median_error_px
    profile.validation_p95_error_px = metrics.p95_error_px
    profile.validation_max_error_px = metrics.max_error_px
    return profile


def select_best_profile(
    training_groups: list[TargetSamples] | tuple[TargetSamples, ...],
    validation_groups: list[TargetSamples] | tuple[TargetSamples, ...],
    screen_size: tuple[int, int],
    camera_index: int,
    ridge_alpha: float,
    kernel_improvement_required: float = 0.05,
) -> CalibrationProfile:
    """Select hyperparameters on independent targets and require a real nonlinear gain."""
    if not 0.0 <= kernel_improvement_required < 1.0:
        raise ValueError("Kernel improvement threshold must be in [0, 1)")
    training_samples = flatten_balanced_groups(training_groups)

    linear_candidates: list[tuple[CalibrationMetrics, CalibrationProfile]] = []
    for alpha in _alpha_candidates(ridge_alpha):
        profile = CalibrationProfile.fit(training_samples, screen_size, camera_index, alpha)
        linear_candidates.append(
            (evaluate_profile(profile, validation_groups, screen_size), profile)
        )
    linear_metrics, linear_profile = min(
        linear_candidates,
        key=lambda candidate: candidate[0].selection_score,
    )

    kernel_candidates: list[tuple[CalibrationMetrics, CalibrationProfile]] = []
    kernel_alpha = max(ridge_alpha, 1e-4)
    for gamma_multiplier in (0.5, 1.0, 2.0):
        try:
            profile = CalibrationProfile.fit_kernel(
                training_samples,
                screen_size,
                camera_index,
                kernel_alpha,
                gamma_multiplier,
            )
        except (ValueError, np.linalg.LinAlgError):
            continue
        metrics = evaluate_profile(profile, validation_groups, screen_size)
        kernel_candidates.append((metrics, profile))
    if not kernel_candidates:
        return _apply_metrics(linear_profile, linear_metrics, training_groups)
    kernel_metrics, kernel_profile = min(
        kernel_candidates,
        key=lambda candidate: candidate[0].selection_score,
    )

    required_score = linear_metrics.selection_score * (1.0 - kernel_improvement_required)
    if kernel_metrics.selection_score < required_score:
        return _apply_metrics(kernel_profile, kernel_metrics, training_groups)
    return _apply_metrics(linear_profile, linear_metrics, training_groups)
