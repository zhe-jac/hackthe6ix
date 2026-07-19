from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import hypot, pi
from pathlib import Path
from time import monotonic

import numpy as np

from chudvis.core.config import default_config_dir
from chudvis.core.events import GazeFeatures, GazeSample, Point
from chudvis.gaze.features import FEATURE_COUNT as HEAD_NORMALIZED_FEATURE_COUNT

PROFILE_VERSION = 3
FEATURE_BACKEND = "head_normalized_v1"
LINEAR_MODEL = "linear_ridge"
KERNEL_MODEL = "rbf_kernel_ridge"


@dataclass(slots=True)
class CalibrationProfile:
    weights_x: list[float]
    weights_y: list[float]
    feature_means: list[float]
    feature_scales: list[float]
    feature_count: int
    screen_width: int
    screen_height: int
    camera_index: int
    created_at: str
    profile_version: int = PROFILE_VERSION
    feature_backend: str = FEATURE_BACKEND
    model_type: str = LINEAR_MODEL
    model_alpha: float = 1.0
    projection_components: list[list[float]] = field(default_factory=list)
    kernel_centers: list[list[float]] = field(default_factory=list)
    kernel_dual_x: list[float] = field(default_factory=list)
    kernel_dual_y: list[float] = field(default_factory=list)
    kernel_gamma: float = 0.0
    kernel_intercept_x: float = 0.0
    kernel_intercept_y: float = 0.0
    calibration_target_count: int = 0
    samples_per_target: int = 0
    validation_target_count: int = 0
    validation_mean_error_px: float | None = None
    validation_median_error_px: float | None = None
    validation_p95_error_px: float | None = None
    validation_max_error_px: float | None = None

    def __post_init__(self) -> None:
        if self.profile_version != PROFILE_VERSION or self.feature_backend != FEATURE_BACKEND:
            raise ValueError(
                "This calibration profile uses an obsolete gaze model. "
                "Run `chudvis calibrate` to create a head-normalized profile."
            )
        if len(self.feature_means) != self.feature_count:
            raise ValueError("Calibration feature mean count does not match feature_count")
        if len(self.feature_scales) != self.feature_count:
            raise ValueError("Calibration feature scale count does not match feature_count")
        if self.model_alpha < 0.0:
            raise ValueError("Calibration model alpha must be non-negative")
        if self.model_type == LINEAR_MODEL:
            if len(self.weights_x) != self.feature_count + 1:
                raise ValueError("Calibration x weight count does not match feature_count")
            if len(self.weights_y) != self.feature_count + 1:
                raise ValueError("Calibration y weight count does not match feature_count")
        elif self.model_type == KERNEL_MODEL:
            component_count = len(self.projection_components)
            if component_count == 0:
                raise ValueError("Kernel calibration has no projection components")
            if any(
                len(component) != self.feature_count for component in self.projection_components
            ):
                raise ValueError("Kernel projection component width does not match feature_count")
            if not self.kernel_centers:
                raise ValueError("Kernel calibration has no training centers")
            if any(len(center) != component_count for center in self.kernel_centers):
                raise ValueError("Kernel center width does not match projection dimension")
            if len(self.kernel_dual_x) != len(self.kernel_centers):
                raise ValueError("Kernel x coefficient count does not match center count")
            if len(self.kernel_dual_y) != len(self.kernel_centers):
                raise ValueError("Kernel y coefficient count does not match center count")
            if self.kernel_gamma <= 0.0:
                raise ValueError("Kernel gamma must be positive")
        else:
            raise ValueError(f"Unsupported calibration model type: {self.model_type}")

    @staticmethod
    def _training_arrays(
        samples: list[tuple[GazeFeatures, Point]],
    ) -> tuple[np.ndarray, np.ndarray, int]:
        if not samples:
            raise ValueError("At least one calibration sample is required")
        feature_count = len(samples[0][0].values)
        if len(samples) < 3:
            raise ValueError(f"At least 3 samples are required; received {len(samples)}")
        if any(len(features.values) != feature_count for features, _ in samples):
            raise ValueError("All calibration samples must use the same number of features")

        features = np.asarray([item.values for item, _ in samples], dtype=float)
        targets = np.asarray([(target.x, target.y) for _, target in samples], dtype=float)
        if not np.all(np.isfinite(features)) or not np.all(np.isfinite(targets)):
            raise ValueError("Calibration samples must contain only finite values")
        return features, targets, feature_count

    @staticmethod
    def _standardize_training(features: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        means = features.mean(axis=0)
        scales = features.std(axis=0)
        scales[scales < 1e-8] = 1.0
        return (features - means) / scales, means, scales

    @classmethod
    def fit(
        cls,
        samples: list[tuple[GazeFeatures, Point]],
        screen_size: tuple[int, int],
        camera_index: int = 0,
        alpha: float = 1.0,
    ) -> CalibrationProfile:
        if alpha < 0.0:
            raise ValueError("Ridge alpha must be non-negative")

        features, targets, feature_count = cls._training_arrays(samples)
        standardized, feature_means, feature_scales = cls._standardize_training(features)

        intercept = targets.mean(axis=0)
        centered_targets = targets - intercept
        sample_count, dimension = standardized.shape
        if alpha == 0.0:
            coefficients = np.linalg.lstsq(
                standardized,
                centered_targets,
                rcond=None,
            )[0]
        elif dimension > sample_count:
            dual = standardized @ standardized.T
            dual += np.eye(sample_count, dtype=float) * alpha
            coefficients = standardized.T @ np.linalg.solve(dual, centered_targets)
        else:
            system = standardized.T @ standardized
            system += np.eye(dimension, dtype=float) * alpha
            coefficients = np.linalg.solve(system, standardized.T @ centered_targets)

        weights_x = np.concatenate((coefficients[:, 0], (intercept[0],)))
        weights_y = np.concatenate((coefficients[:, 1], (intercept[1],)))

        return cls(
            weights_x=weights_x.tolist(),
            weights_y=weights_y.tolist(),
            feature_means=feature_means.tolist(),
            feature_scales=feature_scales.tolist(),
            feature_count=feature_count,
            screen_width=int(screen_size[0]),
            screen_height=int(screen_size[1]),
            camera_index=camera_index,
            created_at=datetime.now(timezone.utc).isoformat(),
            model_type=LINEAR_MODEL,
            model_alpha=alpha,
        )

    @classmethod
    def fit_kernel(
        cls,
        samples: list[tuple[GazeFeatures, Point]],
        screen_size: tuple[int, int],
        camera_index: int = 0,
        alpha: float = 1.0,
        gamma_multiplier: float = 1.0,
        maximum_components: int = 24,
    ) -> CalibrationProfile:
        if alpha <= 0.0:
            raise ValueError("Kernel ridge alpha must be positive")
        if gamma_multiplier <= 0.0:
            raise ValueError("Kernel gamma multiplier must be positive")
        if maximum_components < 1:
            raise ValueError("Kernel projection must retain at least one component")

        features, targets, feature_count = cls._training_arrays(samples)
        standardized, feature_means, feature_scales = cls._standardize_training(features)
        _left, singular_values, right = np.linalg.svd(standardized, full_matrices=False)
        if singular_values.size == 0 or singular_values[0] <= 1e-10:
            raise ValueError("Calibration features do not vary enough to train a kernel model")

        rank_threshold = max(float(singular_values[0]) * 1e-8, 1e-10)
        rank = int(np.count_nonzero(singular_values > rank_threshold))
        component_limit = min(maximum_components, rank)
        variance = singular_values[:rank] ** 2
        cumulative = np.cumsum(variance) / max(float(variance.sum()), 1e-12)
        variance_components = int(np.searchsorted(cumulative, 0.995) + 1)
        component_count = min(component_limit, max(min(4, rank), variance_components))
        components = right[:component_count]
        projected = standardized @ components.T

        squared_norms = np.sum(projected * projected, axis=1)
        distances = (
            squared_norms[:, None] + squared_norms[None, :] - 2.0 * (projected @ projected.T)
        )
        distances = np.maximum(distances, 0.0)
        positive_distances = distances[np.triu_indices_from(distances, k=1)]
        positive_distances = positive_distances[positive_distances > 1e-12]
        if positive_distances.size == 0:
            raise ValueError("Calibration samples do not span multiple gaze positions")
        gamma = gamma_multiplier / float(np.median(positive_distances))

        kernel = np.exp(-gamma * distances)
        target_intercept = targets.mean(axis=0)
        centered_targets = targets - target_intercept
        system = kernel + np.eye(kernel.shape[0], dtype=float) * alpha
        dual = np.linalg.solve(system, centered_targets)

        return cls(
            weights_x=[],
            weights_y=[],
            feature_means=feature_means.tolist(),
            feature_scales=feature_scales.tolist(),
            feature_count=feature_count,
            screen_width=int(screen_size[0]),
            screen_height=int(screen_size[1]),
            camera_index=camera_index,
            created_at=datetime.now(timezone.utc).isoformat(),
            model_type=KERNEL_MODEL,
            model_alpha=alpha,
            projection_components=components.tolist(),
            kernel_centers=projected.tolist(),
            kernel_dual_x=dual[:, 0].tolist(),
            kernel_dual_y=dual[:, 1].tolist(),
            kernel_gamma=gamma,
            kernel_intercept_x=float(target_intercept[0]),
            kernel_intercept_y=float(target_intercept[1]),
        )

    def predict(self, features: GazeFeatures) -> Point:
        if len(features.values) != self.feature_count:
            raise ValueError(
                f"Expected {self.feature_count} gaze features, got {len(features.values)}"
            )
        values = np.asarray(features.values, dtype=float)
        means = np.asarray(self.feature_means, dtype=float)
        scales = np.asarray(self.feature_scales, dtype=float)
        standardized = (values - means) / scales
        if self.model_type == LINEAR_MODEL:
            vector = np.concatenate((standardized, (1.0,)))
            x = float(vector @ np.asarray(self.weights_x, dtype=float))
            y = float(vector @ np.asarray(self.weights_y, dtype=float))
        else:
            components = np.asarray(self.projection_components, dtype=float)
            projected = components @ standardized
            centers = np.asarray(self.kernel_centers, dtype=float)
            squared_distances = np.sum((centers - projected) ** 2, axis=1)
            kernel = np.exp(-self.kernel_gamma * squared_distances)
            x = self.kernel_intercept_x + float(
                kernel @ np.asarray(self.kernel_dual_x, dtype=float)
            )
            y = self.kernel_intercept_y + float(
                kernel @ np.asarray(self.kernel_dual_y, dtype=float)
            )
        return Point(min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0))

    @classmethod
    def load(cls, path: Path | None = None) -> CalibrationProfile:
        path = path or default_config_dir() / "calibration.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            data.get("profile_version") != PROFILE_VERSION
            or data.get("feature_backend") != FEATURE_BACKEND
            or data.get("feature_count") != HEAD_NORMALIZED_FEATURE_COUNT
        ):
            raise ValueError(
                f"Calibration profile at {path} predates the dense validated gaze model. "
                "Run `chudvis calibrate` again."
            )
        return cls(**data)

    def save(self, path: Path | None = None) -> Path:
        path = path or default_config_dir() / "calibration.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        return path


class AdaptiveGazeSmoother:
    def __init__(
        self,
        min_cutoff: float = 1.25,
        beta: float = 8.0,
        derivative_cutoff: float = 1.0,
        deadzone: float = 0.0035,
        stable_speed_threshold: float = 0.12,
    ) -> None:
        if min_cutoff <= 0.0 or derivative_cutoff <= 0.0:
            raise ValueError("Smoothing cutoffs must be positive")
        if beta < 0.0 or deadzone < 0.0 or stable_speed_threshold < 0.0:
            raise ValueError("Smoothing beta, deadzone, and stable threshold cannot be negative")
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.derivative_cutoff = derivative_cutoff
        self.deadzone = deadzone
        self.stable_speed_threshold = stable_speed_threshold
        self._last_raw: Point | None = None
        self._filtered: Point | None = None
        self._output: Point | None = None
        self._derivative = Point(0.0, 0.0)
        self._last_timestamp: float | None = None

    @staticmethod
    def _alpha(cutoff: float, elapsed: float) -> float:
        time_constant = 1.0 / (2.0 * pi * cutoff)
        return 1.0 / (1.0 + time_constant / elapsed)

    def update(self, point: Point, timestamp: float | None = None) -> tuple[Point, bool]:
        timestamp = monotonic() if timestamp is None else timestamp
        if self._last_raw is None or self._filtered is None or self._output is None:
            self._last_raw = point
            self._filtered = point
            self._output = point
            self._last_timestamp = timestamp
            return point, False

        last_timestamp = self._last_timestamp if self._last_timestamp is not None else timestamp
        elapsed = min(max(timestamp - last_timestamp, 1.0 / 240.0), 0.25)
        raw_derivative = Point(
            (point.x - self._last_raw.x) / elapsed,
            (point.y - self._last_raw.y) / elapsed,
        )
        derivative_alpha = self._alpha(self.derivative_cutoff, elapsed)
        self._derivative = Point(
            self._derivative.x + derivative_alpha * (raw_derivative.x - self._derivative.x),
            self._derivative.y + derivative_alpha * (raw_derivative.y - self._derivative.y),
        )
        speed = hypot(self._derivative.x, self._derivative.y)
        cutoff = self.min_cutoff + self.beta * speed
        position_alpha = self._alpha(cutoff, elapsed)
        candidate = Point(
            self._filtered.x + position_alpha * (point.x - self._filtered.x),
            self._filtered.y + position_alpha * (point.y - self._filtered.y),
        )
        stable = speed <= self.stable_speed_threshold
        output_distance = hypot(candidate.x - self._output.x, candidate.y - self._output.y)
        output = self._output if stable and output_distance <= self.deadzone else candidate

        self._last_raw = point
        self._filtered = candidate
        self._output = output
        self._last_timestamp = timestamp
        return output, stable

    def reset(self) -> None:
        self._last_raw = None
        self._filtered = None
        self._output = None
        self._derivative = Point(0.0, 0.0)
        self._last_timestamp = None


class GazeEstimator:
    def __init__(self, profile: CalibrationProfile, smoother: AdaptiveGazeSmoother) -> None:
        self.profile = profile
        self.smoother = smoother

    def estimate(
        self,
        features: GazeFeatures,
        confidence: float,
        timestamp: float,
    ) -> GazeSample:
        raw = self.profile.predict(features)
        point, stable = self.smoother.update(raw, timestamp)
        return GazeSample(point, confidence, stable, timestamp)


class GazeConfidenceGate:
    """Reject unreliable gaze while tolerating brief confidence flicker."""

    def __init__(
        self,
        minimum_confidence: float,
        grace_seconds: float,
        release_ratio: float = 0.70,
    ) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError("Minimum gaze confidence must be between zero and one")
        if grace_seconds < 0.0:
            raise ValueError("Gaze confidence grace period cannot be negative")
        if not 0.0 <= release_ratio <= 1.0:
            raise ValueError("Gaze confidence release ratio must be between zero and one")
        self.minimum_confidence = minimum_confidence
        self.grace_seconds = grace_seconds
        self.release_confidence = minimum_confidence * release_ratio
        self._last_strong_at: float | None = None

    def accepts(self, sample: GazeSample) -> bool:
        if sample.confidence >= self.minimum_confidence:
            self._last_strong_at = sample.timestamp
            return True
        return (
            self._last_strong_at is not None
            and sample.timestamp - self._last_strong_at <= self.grace_seconds
            and sample.confidence >= self.release_confidence
        )

    def reset(self) -> None:
        self._last_strong_at = None
