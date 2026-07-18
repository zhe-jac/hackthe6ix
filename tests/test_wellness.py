from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from gazemotion.core.config import WellnessSettings
from gazemotion.wellness.monitor import (
    WellnessMonitor,
    WellnessReport,
    _mean_metric,
    assess_vitals,
)


def test_mean_metric_accepts_mappings_and_lists() -> None:
    assert _mean_metric({"0.0": 60, "1.0": 70}) == 65
    assert _mean_metric([{"value": 12}, {"value": 18}]) == 15
    assert _mean_metric(None) is None
    assert _mean_metric({"0.0": "bad"}) is None


def test_assess_vitals_steady_without_baseline() -> None:
    settings = WellnessSettings()
    assessment, suggestions = assess_vitals(70, 14, None, None, 5.0, settings)
    assert assessment == "steady"
    assert suggestions == ()


def test_assess_vitals_flags_elevated_pulse() -> None:
    settings = WellnessSettings(pulse_alert_ratio=1.2)
    assessment, suggestions = assess_vitals(90, 14, 70.0, 14.0, 5.0, settings)
    assert assessment == "elevated"
    assert any("heart rate" in line for line in suggestions)


def test_assess_vitals_break_reminder() -> None:
    settings = WellnessSettings(break_reminder_minutes=25)
    assessment, suggestions = assess_vitals(70, 14, 70.0, 14.0, 30.0, settings)
    assert assessment == "break-due"
    assert any("break" in line for line in suggestions)


class FakeClient:
    def __init__(self) -> None:
        self.uploaded: list[str] = []

    def queue_processing_hr_rr(self, video_path: str) -> str:
        self.uploaded.append(video_path)
        return "video-1"

    def retrieve_result(self, video_id: str) -> dict:
        return {"hr": {"0.0": 72, "1.0": 74}, "rr": {"0.0": 15}}


def _settings() -> WellnessSettings:
    return WellnessSettings(
        clip_seconds=0.3,
        clip_fps=5,
        interval_seconds=100.0,
        first_sample_delay_seconds=0.0,
        poll_interval_seconds=0.01,
        poll_timeout_seconds=2.0,
    )


def test_monitor_records_clip_and_reports_vitals(tmp_path: Path) -> None:
    client = FakeClient()
    monitor = WellnessMonitor(_settings(), client, clip_dir=tmp_path)
    frame = np.zeros((48, 64, 3), dtype=np.uint8)

    for step in range(4):
        monitor.submit_frame(frame, float(step) * 0.15)

    deadline = time.monotonic() + 5.0
    reports: list[WellnessReport | str] = []
    while time.monotonic() < deadline and not reports:
        reports = monitor.poll()
        time.sleep(0.01)
    monitor.close()

    assert len(client.uploaded) == 1
    assert not Path(client.uploaded[0]).exists()  # clip is deleted after upload
    assert len(reports) == 1
    report = reports[0]
    assert isinstance(report, WellnessReport)
    assert report.pulse_bpm == 73
    assert report.breathing_bpm == 15
    assert monitor.baseline_pulse == 73


def test_monitor_waits_for_interval_before_next_clip(tmp_path: Path) -> None:
    client = FakeClient()
    monitor = WellnessMonitor(_settings(), client, clip_dir=tmp_path)
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    for step in range(4):
        monitor.submit_frame(frame, float(step) * 0.15)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not monitor.poll():
        time.sleep(0.01)

    # Immediately after a clip, the monitor should stay idle until the interval.
    monitor.submit_frame(frame, 1.0)
    monitor.submit_frame(frame, 2.0)
    assert len(client.uploaded) == 1
    monitor.close()
