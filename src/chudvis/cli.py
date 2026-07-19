from __future__ import annotations

import argparse
import importlib.util
import os
import socket
import sys
from pathlib import Path

from chudvis import __version__
from chudvis.actions.base import InputAdapter, RecordingInputAdapter
from chudvis.core.config import AppConfig, default_config_dir
from chudvis.core.platform import (
    configure_process_for_desktop_input,
    get_screen_size,
    inspect_platform,
    is_wsl,
    list_video_devices,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chudvis",
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
    doctor.add_argument(
        "--ide",
        action="store_true",
        help="also verify the configured VS Code extension bridge",
    )

    calibrate = subparsers.add_parser("calibrate", help="create a gaze calibration profile")
    calibrate.add_argument("--camera", type=int, default=None)
    calibrate.add_argument(
        "--profile",
        type=Path,
        default=default_config_dir() / "calibration.json",
    )
    calibrate.add_argument(
        "--grid-size",
        type=int,
        choices=(5, 7),
        default=5,
        help="dense calibration grid size; 7 is slower but covers more positions",
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
    test.add_argument(
        "--ide",
        action="store_true",
        help="show and label both hands for IDE role practice",
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

    ide = subparsers.add_parser(
        "ide",
        help="start two-hand, gaze, and voice control for a supported IDE extension",
    )
    ide.add_argument("--camera", type=int, default=None)
    ide.add_argument(
        "--profile",
        type=Path,
        default=default_config_dir() / "calibration.json",
    )
    ide.add_argument("--preview", action="store_true", help="show landmark and state preview")
    ide.add_argument("--dry-run", action="store_true", help="disable gaze pointer and click output")
    ide.add_argument("--no-voice", action="store_true", help="disable microphone and transcription")
    ide.add_argument("--host", default=None, help="IDE extension loopback host")
    ide.add_argument("--port", type=int, default=None, help="IDE extension loopback port")
    ide.add_argument("--session-token", default=None, help="IDE bridge session token")
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
    optional = (
        "sounddevice",
        "faster_whisper",
        "sherpa_onnx",
        "sentencepiece",
        "websocket",
        "requests",
    )
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
    _print_optional(
        "voice/ELEVENLABS_API_KEY",
        bool(os.environ.get(config.voice.elevenlabs_api_key_env, "").strip()),
        (
            f"configured through {config.voice.elevenlabs_api_key_env}"
            if os.environ.get(config.voice.elevenlabs_api_key_env, "").strip()
            else f"not configured; set {config.voice.elevenlabs_api_key_env} for wake streaming"
        ),
    )

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
        str(profile_path) if profile_path.exists() else "not created; run `chudvis calibrate`",
    )

    if not args.skip_camera and importlib.util.find_spec("cv2") is not None:
        from chudvis.capture.camera import OpenCVCamera

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
                    "support before rerunning `uv run chudvis doctor --camera 0`."
                )
        finally:
            camera.stop()

    if args.ide:
        from chudvis.ide.protocol import (
            PROTOCOL_VERSION,
            decode_message,
            encode_message,
            notification,
        )

        connection: socket.socket | None = None
        try:
            connection = socket.create_connection(
                (config.ide.host, config.ide.port),
                timeout=1.5,
            )
            connection.sendall(
                encode_message(
                    notification(
                        "bridge.hello",
                        {
                            "protocolVersion": PROTOCOL_VERSION,
                            "client": "chudvis-doctor",
                            "sessionToken": config.ide.session_token,
                        },
                    ),
                    config.ide.max_message_bytes,
                )
            )
            with connection.makefile("rb") as stream:
                response = decode_message(
                    stream.readline(config.ide.max_message_bytes + 1).rstrip(b"\n"),
                    config.ide.max_message_bytes,
                )
            params = response.get("params", {})
            detail = params.get("message", "bridge responded")
            success &= _print_check(
                "VS Code bridge",
                response.get("method") == "bridge.status",
                str(detail),
            )
        except Exception as exc:
            success &= _print_check(
                "VS Code bridge",
                False,
                f"{exc}; install/start the extension and verify IDE bridge settings",
            )
        finally:
            if connection is not None:
                connection.close()
    return 0 if success else 1


def _calibrate(args: argparse.Namespace, config: AppConfig) -> int:
    from chudvis.capture.camera import OpenCVCamera
    from chudvis.perception.mediapipe_tracker import MediaPipeTracker
    from chudvis.ui.calibration import run_calibration

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
    print(
        f"Starting {args.grid_size}x{args.grid_size} dense calibration plus validation. "
        "Keep your head still and follow each dot with your eyes."
    )
    with camera, MediaPipeTracker(max_hands=1, settings=config.tracking) as tracker:
        profile = run_calibration(
            camera,
            tracker,
            screen_size,
            camera_index,
            config.gaze.ridge_alpha,
            grid_size=args.grid_size,
            minimum_confidence=config.gaze.minimum_confidence,
        )
    saved = profile.save(args.profile)
    median = profile.validation_median_error_px or 0.0
    p95 = profile.validation_p95_error_px or 0.0
    print(
        f"Calibration saved to {saved} (model={profile.model_type}, "
        f"validation median={median:.0f}px, p95={p95:.0f}px)"
    )
    return 0


def _run(args: argparse.Namespace, config: AppConfig) -> int:
    from chudvis.app import ChudvisApplication
    from chudvis.gaze.model import CalibrationProfile

    if not args.profile.exists():
        raise RuntimeError(
            f"Calibration profile not found at {args.profile}. Run `chudvis calibrate` first."
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

    input_adapter: InputAdapter
    if args.dry_run:
        input_adapter = RecordingInputAdapter(announce=False)
        print("Dry-run mode: OS mouse and keyboard events are disabled.")
    else:
        from chudvis.actions.pynput_adapter import PynputInputAdapter

        input_adapter = PynputInputAdapter()

    dictation = None
    if config.voice.enabled and not args.no_voice:
        try:
            from chudvis.speech.dictation import LocalDictationService

            dictation = LocalDictationService(
                config.voice.model,
                config.voice.sample_rate,
                config.voice.device,
                config.voice.compute_type,
            )
        except Exception as exc:
            print(f"Voice disabled: {exc}", file=sys.stderr)

    application = ChudvisApplication(
        config,
        profile,
        input_adapter,
        screen_size,
        dictation,
        args.preview,
    )
    application.run()
    return 0


def _test(args: argparse.Namespace, config: AppConfig) -> int:
    from chudvis.gaze.model import CalibrationProfile
    from chudvis.ui.diagnostics import run_diagnostics

    camera_index = args.camera if args.camera is not None else config.camera_index
    config.camera_index = camera_index
    profile = None
    if args.profile.exists():
        try:
            profile = CalibrationProfile.load(args.profile)
            print(f"Loaded gaze calibration from {args.profile}")
        except ValueError as exc:
            print(f"Gaze calibration disabled: {exc}", file=sys.stderr)
    else:
        print(f"No calibration found at {args.profile}; showing face and gesture diagnostics only.")
    run_diagnostics(config, profile, camera_index, ide_mode=args.ide)
    return 0


def _ide(args: argparse.Namespace, config: AppConfig) -> int:
    from chudvis.gaze.model import CalibrationProfile
    from chudvis.ide.adapter import SocketIdeAdapter
    from chudvis.ide.app import ChudvisIdeApplication
    from chudvis.ide.transport import IdeTransport

    if not args.profile.exists():
        raise RuntimeError(
            f"Calibration profile not found at {args.profile}. Run `chudvis calibrate` first."
        )
    profile = CalibrationProfile.load(args.profile)
    config.camera_index = args.camera if args.camera is not None else config.camera_index
    environment_host = os.environ.get("CHUDVIS_IDE_HOST")
    environment_port = os.environ.get("CHUDVIS_IDE_PORT")
    environment_token = os.environ.get("CHUDVIS_IDE_SESSION_TOKEN")
    if args.host is not None:
        config.ide.host = args.host
    elif environment_host:
        config.ide.host = environment_host
    if args.port is not None:
        config.ide.port = args.port
    elif environment_port:
        try:
            config.ide.port = int(environment_port)
        except ValueError as exc:
            raise ValueError("CHUDVIS_IDE_PORT must be an integer") from exc
    if args.session_token is not None:
        config.ide.session_token = args.session_token
    elif environment_token is not None:
        config.ide.session_token = environment_token

    try:
        screen_size = get_screen_size()
    except RuntimeError:
        if not args.dry_run:
            raise
        screen_size = (profile.screen_width, profile.screen_height)

    input_adapter: InputAdapter
    if args.dry_run:
        input_adapter = RecordingInputAdapter(announce=False)
        print("IDE dry-run mode: OS pointer and click events are disabled.")
    else:
        from chudvis.actions.pynput_adapter import PynputInputAdapter

        input_adapter = PynputInputAdapter()

    dictation = None
    voice_session = None
    if config.voice.enabled and not args.no_voice:
        if config.voice.wake_word_enabled:
            try:
                from chudvis.speech.realtime_voice import create_elevenlabs_voice_session

                voice_session = create_elevenlabs_voice_session(config.voice)
                print(
                    "Chudvis voice is enabled: audio after wake activation is sent to "
                    "ElevenLabs; selected workspace context is sent by the extension to "
                    "the configured model provider."
                )
            except Exception as exc:
                print(f"Wake streaming unavailable: {exc}", file=sys.stderr)
        try:
            from chudvis.speech.dictation import LocalDictationService

            dictation = LocalDictationService(
                config.voice.model,
                config.voice.sample_rate,
                config.voice.device,
                config.voice.compute_type,
            )
            if voice_session is None:
                print("Using local thumbs-up/Whisper voice fallback.")
        except Exception as exc:
            if voice_session is None:
                print(f"Voice disabled: {exc}", file=sys.stderr)
            else:
                print(f"Local Whisper fallback unavailable: {exc}", file=sys.stderr)

    transport = IdeTransport(
        config.ide.host,
        config.ide.port,
        config.ide.session_token,
        config.ide.reconnect_delay_seconds,
        config.ide.max_message_bytes,
    )
    transport.start()
    try:
        adapter = SocketIdeAdapter(transport)
        application = ChudvisIdeApplication(
            config,
            profile,
            input_adapter,
            adapter,
            screen_size,
            dictation,
            voice_session,
            args.preview,
        )
        application.run()
    finally:
        transport.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_process_for_desktop_input()
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
        if args.command == "ide":
            return _ide(args, config)
    except KeyboardInterrupt:
        print("\nStopped safely.")
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 2
