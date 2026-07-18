from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

from gazemotion import __version__
from gazemotion.actions.base import RecordingInputAdapter
from gazemotion.core.config import AppConfig, default_config_dir
from gazemotion.core.platform import get_screen_size, inspect_platform, is_wsl, list_video_devices


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gazemotion",
        description="Control the desktop with gaze, hand gestures, and optional voice dictation.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_dir() / "config.json",
        help="configuration JSON path",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check the local runtime and hardware")
    doctor.add_argument("--camera", type=int, default=None)
    doctor.add_argument("--skip-camera", action="store_true")

    calibrate = subparsers.add_parser("calibrate", help="create a gaze calibration profile")
    calibrate.add_argument("--camera", type=int, default=None)
    calibrate.add_argument(
        "--profile",
        type=Path,
        default=default_config_dir() / "calibration.json",
    )

    test = subparsers.add_parser(
        "test",
        help="view camera tracking, gaze position, and gesture triggers without OS actions",
    )
    test.add_argument("--camera", type=int, default=None)
    test.add_argument(
        "--profile",
        type=Path,
        default=default_config_dir() / "calibration.json",
    )

    run = subparsers.add_parser("run", help="start desktop gaze and gesture control")
    run.add_argument("--camera", type=int, default=None)
    run.add_argument(
        "--profile",
        type=Path,
        default=default_config_dir() / "calibration.json",
    )
    run.add_argument("--preview", action="store_true", help="show landmark and state preview")
    run.add_argument("--dry-run", action="store_true", help="recognize but do not control the OS")
    run.add_argument("--no-voice", action="store_true", help="disable microphone and transcription")
    run.add_argument("--no-agent", action="store_true", help="type transcripts verbatim instead")
    run.add_argument("--no-speak", action="store_true", help="disable spoken ElevenLabs feedback")
    run.add_argument("--no-wellness", action="store_true", help="disable Presage vitals sampling")
    return parser


def _print_check(name: str, ok: bool, detail: str) -> bool:
    marker = "PASS" if ok else "FAIL"
    print(f"[{marker}] {name}: {detail}")
    return ok


def _print_optional(name: str, available: bool, detail: str) -> None:
    marker = "PASS" if available else "WARN"
    print(f"[{marker}] {name}: {detail}")


def _doctor(args: argparse.Namespace, config: AppConfig) -> int:
    required = ("numpy", "cv2", "mediapipe", "pynput")
    optional = ("sounddevice", "faster_whisper")
    success = True
    for module in required:
        found = importlib.util.find_spec(module) is not None
        success &= _print_check(module, found, "installed" if found else "missing; run `uv sync`")
    for module in optional:
        found = importlib.util.find_spec(module) is not None
        _print_optional(
            f"voice/{module}",
            found,
            "installed" if found else "optional; run `uv sync --extra voice`",
        )
    for label, env in (
        ("agent/backboard", config.agent.api_key_env),
        ("speech/elevenlabs", config.speech_output.api_key_env),
        ("wellness/presage", config.wellness.api_key_env),
    ):
        configured = bool(os.environ.get(env))
        _print_optional(label, configured, f"{env} set" if configured else f"{env} not set")

    platform = inspect_platform()
    success &= _print_check(
        "desktop display",
        platform.display_available,
        f"session={platform.session_type}, size={platform.screen_size}",
    )
    if os.name != "nt" and platform.session_type == "wayland":
        print("[WARN] Wayland may deny pynput global input; use X11 or start with --dry-run.")

    profile_path = default_config_dir() / "calibration.json"
    _print_optional(
        "calibration",
        profile_path.exists(),
        str(profile_path) if profile_path.exists() else "not created; run `gazemotion calibrate`",
    )

    if not args.skip_camera and importlib.util.find_spec("cv2") is not None:
        from gazemotion.capture.camera import OpenCVCamera

        camera_index = args.camera if args.camera is not None else config.camera_index
        camera = OpenCVCamera(
            index=camera_index,
            width=640,
            height=480,
            fps=config.camera_fps,
            fourcc=config.camera_fourcc,
            mirror=config.mirror_camera,
        )
        try:
            camera.start()
            frame = camera.read()
            success &= _print_check("camera", frame is not None, f"opened index {camera_index}")
        except Exception as exc:
            success &= _print_check("camera", False, str(exc))
            if is_wsl() and not list_video_devices():
                print(
                    "[HINT] WSL2 has no /dev/video* devices. Windows webcams are not exposed "
                    "to Linux automatically. Run this app from Windows Python, or attach a "
                    "USB webcam to WSL with usbipd-win and ensure the WSL kernel has UVC/video "
                    "support before rerunning `uv run gazemotion doctor --camera 0`."
                )
        finally:
            camera.stop()
    return 0 if success else 1


def _calibrate(args: argparse.Namespace, config: AppConfig) -> int:
    from gazemotion.capture.camera import OpenCVCamera
    from gazemotion.perception.mediapipe_tracker import MediaPipeTracker
    from gazemotion.ui.calibration import run_calibration

    camera_index = args.camera if args.camera is not None else config.camera_index
    screen_size = get_screen_size()
    camera = OpenCVCamera(
        index=camera_index,
        width=config.camera_width,
        height=config.camera_height,
        fps=config.camera_fps,
        fourcc=config.camera_fourcc,
        mirror=config.mirror_camera,
    )
    print("Starting nine-point calibration. Keep your head comfortable and follow each dot.")
    with camera, MediaPipeTracker(max_hands=1, settings=config.tracking) as tracker:
        profile = run_calibration(
            camera,
            tracker,
            screen_size,
            camera_index,
            config.gaze.ridge_alpha,
        )
    saved = profile.save(args.profile)
    print(f"Calibration saved to {saved}")
    return 0


def _run(args: argparse.Namespace, config: AppConfig) -> int:
    from gazemotion.app import GazeMotionApplication
    from gazemotion.gaze.model import CalibrationProfile

    if not args.profile.exists():
        raise RuntimeError(
            f"Calibration profile not found at {args.profile}. Run `gazemotion calibrate` first."
        )
    profile = CalibrationProfile.load(args.profile)
    camera_index = args.camera if args.camera is not None else config.camera_index
    config.camera_index = camera_index

    try:
        screen_size = get_screen_size()
    except RuntimeError:
        if not args.dry_run:
            raise
        screen_size = (profile.screen_width, profile.screen_height)

    if args.dry_run:
        input_adapter = RecordingInputAdapter(announce=False)
        print("Dry-run mode: OS mouse and keyboard events are disabled.")
    else:
        from gazemotion.actions.pynput_adapter import PynputInputAdapter

        input_adapter = PynputInputAdapter()

    dictation = None
    if config.voice.enabled and not args.no_voice:
        try:
            from gazemotion.speech.dictation import (
                ElevenLabsDictationService,
                LocalDictationService,
            )

            stt_key = os.environ.get(config.voice.api_key_env, "")
            if config.voice.provider in ("auto", "elevenlabs") and stt_key:
                dictation = ElevenLabsDictationService(
                    stt_key,
                    config.voice.sample_rate,
                    config.voice.elevenlabs_model,
                )
                print("Speech to text: ElevenLabs Scribe")
            else:
                if config.voice.provider == "elevenlabs":
                    print(
                        f"{config.voice.api_key_env} is not set; using local Whisper instead",
                        file=sys.stderr,
                    )
                dictation = LocalDictationService(
                    config.voice.model,
                    config.voice.sample_rate,
                    config.voice.device,
                    config.voice.compute_type,
                )
                print(f"Speech to text: local Whisper ({config.voice.model})")
        except Exception as exc:
            print(f"Voice disabled: {exc}", file=sys.stderr)

    agent = None
    if config.agent.enabled and not args.no_agent and dictation is not None:
        from gazemotion.agent.agent import VoiceCommandAgent, build_parser
        from gazemotion.agent.intents import (
            DesktopSystemAdapter,
            IntentExecutor,
            RecordingSystemAdapter,
        )

        if args.dry_run:
            system_adapter = RecordingSystemAdapter(announce=True)
        else:
            system_adapter = DesktopSystemAdapter()
        intent_parser, parser_label = build_parser(config.agent)
        agent = VoiceCommandAgent(intent_parser, IntentExecutor(input_adapter, system_adapter))
        print(f"Voice commands: {parser_label}")

    speaker = None
    if not args.no_speak:
        from gazemotion.speech.voice_out import build_speaker

        speaker, speaker_label = build_speaker(config.speech_output)
        print(f"Spoken feedback: {speaker_label}")

    wellness = None
    if not args.no_wellness:
        from gazemotion.wellness.monitor import build_wellness_monitor

        wellness, wellness_label = build_wellness_monitor(config.wellness)
        print(f"Wellness monitor: {wellness_label}")

    application = GazeMotionApplication(
        config,
        profile,
        input_adapter,
        screen_size,
        dictation,
        args.preview,
        agent=agent,
        speaker=speaker,
        wellness=wellness,
    )
    application.run()
    return 0


def _test(args: argparse.Namespace, config: AppConfig) -> int:
    from gazemotion.gaze.model import CalibrationProfile
    from gazemotion.ui.diagnostics import run_diagnostics

    camera_index = args.camera if args.camera is not None else config.camera_index
    config.camera_index = camera_index
    profile = None
    if args.profile.exists():
        profile = CalibrationProfile.load(args.profile)
        print(f"Loaded gaze calibration from {args.profile}")
    else:
        print(f"No calibration found at {args.profile}; showing face and gesture diagnostics only.")
    run_diagnostics(config, profile, camera_index)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = AppConfig.load(args.config)
        if args.command == "doctor":
            return _doctor(args, config)
        if args.command == "calibrate":
            return _calibrate(args, config)
        if args.command == "test":
            return _test(args, config)
        if args.command == "run":
            return _run(args, config)
    except KeyboardInterrupt:
        print("\nStopped safely.")
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 2
