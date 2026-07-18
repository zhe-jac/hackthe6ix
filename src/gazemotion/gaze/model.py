from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from gazemotion.core.config import default_config_dir
from gazemotion.core.events import GazeFeatures, GazeSample, Point


@dataclass(slots=True)
class CalibrationProfile:
    weights_x: list[float]
    weights_y: list[float]
    feature_count: int
    screen_width: int
    screen_height: int
    camera_index: int
    created_at: str

    @classmethod
    def fit(
        cls,
        samples: list[tuple[GazeFeatures, Point]],
        screen_size: tuple[int, int],
        camera_index: int = 0,
        alpha: float = 0.02,
    ) -> CalibrationProfile:
        if not samples:
            raise ValueError("At least one calibration sample is required")
        feature_count = len(samples[0][0].values)
        if len(samples) < feature_count + 1:
            raise ValueError(
                f"At least {feature_count + 1} samples are required; received {len(samples)}"
            )
        if any(len(features.values) != feature_count for features, _ in samples):
            raise ValueError("All calibration samples must use the same number of features")

        x = np.asarray([(*features.values, 1.0) for features, _ in samples], dtype=float)
        y_x = np.asarray([target.x for _, target in samples], dtype=float)
        y_y = np.asarray([target.y for _, target in samples], dtype=float)
        regularizer = np.eye(x.shape[1], dtype=float) * alpha
        regularizer[-1, -1] = 0.0
        system = x.T @ x + regularizer
        weights_x = np.linalg.solve(system, x.T @ y_x)
        weights_y = np.linalg.solve(system, x.T @ y_y)

        return cls(
            weights_x=weights_x.tolist(),
            weights_y=weights_y.tolist(),
            feature_count=feature_count,
            screen_width=int(screen_size[0]),
            screen_height=int(screen_size[1]),
            camera_index=camera_index,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def predict(self, features: GazeFeatures) -> Point:
        if len(features.values) != self.feature_count:
            raise ValueError(
                f"Expected {self.feature_count} gaze features, got {len(features.values)}"
            )
        vector = np.asarray((*features.values, 1.0), dtype=float)
        x = float(vector @ np.asarray(self.weights_x, dtype=float))
        y = float(vector @ np.asarray(self.weights_y, dtype=float))
        return Point(min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0))

    @classmethod
    def load(cls, path: Path | None = None) -> CalibrationProfile:
        path = path or default_config_dir() / "calibration.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    def save(self, path: Path | None = None) -> Path:
        path = path or default_config_dir() / "calibration.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        return path


class AdaptiveGazeSmoother:
    def __init__(
        self,
        slow_alpha: float = 0.20,
        fast_alpha: float = 0.62,
        fast_speed_threshold: float = 0.06,
        stable_speed_threshold: float = 0.018,
    ) -> None:
        self.slow_alpha = slow_alpha
        self.fast_alpha = fast_alpha
        self.fast_speed_threshold = fast_speed_threshold
        self.stable_speed_threshold = stable_speed_threshold
        self._last: Point | None = None

    def update(self, point: Point) -> tuple[Point, bool]:
        if self._last is None:
            self._last = point
            return point, False
        distance = ((point.x - self._last.x) ** 2 + (point.y - self._last.y) ** 2) ** 0.5
        ratio = min(distance / max(self.fast_speed_threshold, 1e-6), 1.0)
        alpha = self.slow_alpha + (self.fast_alpha - self.slow_alpha) * ratio
        smoothed = Point(
            self._last.x + alpha * (point.x - self._last.x),
            self._last.y + alpha * (point.y - self._last.y),
        )
        stable = distance <= self.stable_speed_threshold
        self._last = smoothed
        return smoothed, stable

    def reset(self) -> None:
        self._last = None


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
        point, stable = self.smoother.update(raw)
        return GazeSample(point, confidence, stable, timestamp)
