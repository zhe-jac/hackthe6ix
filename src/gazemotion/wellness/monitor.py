from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread
from time import monotonic, sleep
from typing import Any, Protocol

from gazemotion.core.config import WellnessSettings


class VitalsClient(Protocol):
    """Subset of the Presage Physiology client used by the monitor."""

    def queue_processing_hr_rr(self, video_path: str) -> str: ...

    def retrieve_result(self, video_id: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class WellnessReport:
    pulse_bpm: float
    breathing_bpm: float
    assessment: str
    suggestions: tuple[str, ...]
    timestamp: float


@dataclass(slots=True)
class _ClipRecorder:
    path: Path
    writer: Any
    started_at: float
    frames: int = 0
    last_sample_at: float = field(default=0.0)


def _mean_metric(metric: Any) -> float | None:
    """Average a Presage metric that may be a mapping or list of readings."""
    values: list[float] = []
    if isinstance(metric, dict):
        candidates = metric.values()
    elif isinstance(metric, (list, tuple)):
        candidates = metric
    else:
        return None
    for item in candidates:
        if isinstance(item, dict):
            item = item.get("value", item.get("hr", item.get("rr")))
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if number > 0:
            values.append(number)
    if not values:
        return None
    return sum(values) / len(values)


def assess_vitals(
    pulse: float,
    breathing: float,
    baseline_pulse: float | None,
    baseline_breathing: float | None,
    session_minutes: float,
    settings: WellnessSettings,
) -> tuple[str, tuple[str, ...]]:
    """Turn a vitals reading into a plain-language assessment and suggestions."""
    suggestions: list[str] = []
    elevated = False
    if baseline_pulse and pulse >= baseline_pulse * settings.pulse_alert_ratio:
        elevated = True
        suggestions.append("Your heart rate is running above your session baseline.")
    if baseline_breathing and breathing >= baseline_breathing * settings.breathing_alert_ratio:
        elevated = True
        suggestions.append("Your breathing is faster than earlier; try a slow breath.")
    if session_minutes >= settings.break_reminder_minutes:
        suggestions.append(
            f"You have been controlling the desktop for {session_minutes:.0f} minutes; "
            "consider a short break."
        )
    if elevated:
        assessment = "elevated"
    elif suggestions:
        assessment = "break-due"
    else:
        assessment = "steady"
    return assessment, tuple(suggestions)


class WellnessMonitor:
    """Contactless vitals sampling built on the Presage Physiology API.

    Every `interval_seconds` the monitor records a short clip straight from the
    frames the control loop is already capturing, uploads it in a background
    thread, and turns the returned pulse/breathing rates into gentle fatigue
    feedback. No video is ever kept: clips are deleted right after upload.
    """

    def __init__(
        self,
        settings: WellnessSettings,
        client: VitalsClient,
        clip_dir: Path | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.clip_dir = clip_dir or Path(tempfile.gettempdir())
        self.session_started_at: float | None = None
        self.baseline_pulse: float | None = None
        self.baseline_breathing: float | None = None
        self._recorder: _ClipRecorder | None = None
        self._next_record_at: float | None = None
        self._processing = False
        self._lock = Lock()
        self._pending: list[WellnessReport | str] = []

    def _open_recorder(self, frame: Any, now: float) -> _ClipRecorder:
        import cv2

        height, width = frame.shape[:2]
        path = self.clip_dir / f"gazemotion-wellness-{os.getpid()}-{int(now)}.mp4"
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            self.settings.clip_fps,
            (width, height),
        )
        return _ClipRecorder(path=path, writer=writer, started_at=now)

    def submit_frame(self, frame: Any, now: float) -> None:
        if self.session_started_at is None:
            self.session_started_at = now
            self._next_record_at = now + self.settings.first_sample_delay_seconds
        if self._recorder is None:
            if (
                self._processing
                or self._next_record_at is None
                or now < self._next_record_at
            ):
                return
            self._recorder = self._open_recorder(frame, now)
        recorder = self._recorder
        if now - recorder.last_sample_at >= 1.0 / self.settings.clip_fps:
            recorder.writer.write(frame)
            recorder.frames += 1
            recorder.last_sample_at = now
        if now - recorder.started_at >= self.settings.clip_seconds:
            recorder.writer.release()
            self._recorder = None
            self._next_record_at = now + self.settings.interval_seconds
            self._processing = True
            Thread(
                target=self._process_clip,
                args=(recorder.path, now),
                name="wellness",
                daemon=True,
            ).start()

    def _process_clip(self, path: Path, recorded_at: float) -> None:
        try:
            video_id = self.client.queue_processing_hr_rr(str(path))
            result = self._poll_result(video_id)
            pulse = _mean_metric(result.get("hr")) if isinstance(result, dict) else None
            breathing = _mean_metric(result.get("rr")) if isinstance(result, dict) else None
            if pulse is None or breathing is None:
                self._push("Wellness check: no vitals detected; keep face and chest in view.")
                return
            self._push(self._build_report(pulse, breathing, recorded_at))
        except Exception as exc:
            self._push(f"Wellness check failed: {exc}")
        finally:
            path.unlink(missing_ok=True)
            self._processing = False

    def _poll_result(self, video_id: str) -> Any:
        deadline = monotonic() + self.settings.poll_timeout_seconds
        while monotonic() < deadline:
            result = self.client.retrieve_result(video_id)
            if result:
                return result
            sleep(self.settings.poll_interval_seconds)
        raise TimeoutError("Presage processing did not finish in time")

    def _build_report(self, pulse: float, breathing: float, now: float) -> WellnessReport:
        session_minutes = 0.0
        if self.session_started_at is not None:
            session_minutes = (now - self.session_started_at) / 60.0
        assessment, suggestions = assess_vitals(
            pulse,
            breathing,
            self.baseline_pulse,
            self.baseline_breathing,
            session_minutes,
            self.settings,
        )
        if self.baseline_pulse is None:
            self.baseline_pulse = pulse
        if self.baseline_breathing is None:
            self.baseline_breathing = breathing
        return WellnessReport(
            pulse_bpm=pulse,
            breathing_bpm=breathing,
            assessment=assessment,
            suggestions=suggestions,
            timestamp=now,
        )

    def _push(self, item: WellnessReport | str) -> None:
        with self._lock:
            self._pending.append(item)

    def poll(self) -> list[WellnessReport | str]:
        with self._lock:
            items = self._pending
            self._pending = []
        return items

    def close(self) -> None:
        if self._recorder is not None:
            self._recorder.writer.release()
            self._recorder.path.unlink(missing_ok=True)
            self._recorder = None


def build_wellness_monitor(
    settings: WellnessSettings,
) -> tuple[WellnessMonitor | None, str]:
    """Create the monitor when Presage credentials and client are available."""
    if not settings.enabled:
        return None, "disabled"
    api_key = os.environ.get(settings.api_key_env, "")
    if not api_key:
        return None, f"disabled ({settings.api_key_env} is not set)"
    from gazemotion.wellness.presage_client import PresagePhysiologyClient

    return (
        WellnessMonitor(settings, PresagePhysiologyClient(api_key)),
        f"Presage vitals every {settings.interval_seconds:.0f}s",
    )
