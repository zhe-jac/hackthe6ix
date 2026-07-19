#!/usr/bin/env python3
"""Standalone microphone test for the proposed "chudvis" wake word.

This is deliberately not imported by Chudvis. Run it with ephemeral dependencies:

From WSL (recommended, since the microphone belongs to Windows):

    ./scripts/test-chudvis-wake-word-windows.sh

From native Linux:

    uv run --no-project \
      --with sherpa-onnx==1.13.4 \
      --with sherpa-onnx-bin==1.13.4 \
      --with sherpa-onnx-core==1.13.4 \
      --with 'numpy>=1.24,<3' \
      --with 'sentencepiece>=0.2' \
      --with 'sounddevice>=0.4.7' \
      -- python scripts/test-chudvis-wake-word.py

The first run downloads the small English keyword-spotting model to
~/.cache/chudvis/wake-word-test. Nothing is added to the project environment.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import sys
import tarfile
import time
import urllib.request
from collections import Counter
from pathlib import Path

MODEL_NAME = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/"
    f"{MODEL_NAME}.tar.bz2"
)
MODEL_ARCHIVE_SHA256 = "f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a"
ENCODER = "encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
DECODER = "decoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
JOINER = "joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
MODEL_FILE_SHA256 = {
    "tokens.txt": "fd2ded4050a55d2b1578870ba8697d02371980217806b7558bd0a5cc60f3ba53",
    "bpe.model": "c8a2a0129c4ab8e463164c142f82d25649661b122c8cd0b7aab5c9e80b90ad24",
    ENCODER: "1e721676515bcd42a186979733981213c66c80db680e1cc582dfedf3be76e678",
    DECODER: "e40ff43297abe815e8898494c17e71bba2152d9d40fa3eb803f75d0f7533329a",
    JOINER: "eae9da0c7e1e6c6a3f4cc42d167899c388f6c6701b94cb96320e4f55df79624c",
}
SAMPLE_RATE = 16_000
SAMPLES_PER_READ = 1_600  # 100 ms
DEFAULT_SPELLINGS = ("CHUDVIS", "CHUD VIS", "CHUD VIZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Try the proposed chudvis wake word without changing Chudvis.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=60.0,
        help="test duration; use 0 to listen until Ctrl+C",
    )
    parser.add_argument(
        "--expected",
        type=int,
        default=10,
        help="how many times you plan to intentionally say the wake word",
    )
    parser.add_argument(
        "--spelling",
        action="append",
        dest="spellings",
        help=(
            "acoustic spelling to accept; repeat for variants. The defaults try "
            "CHUDVIS, CHUD VIS, and CHUD VIZ"
        ),
    )
    parser.add_argument(
        "--score",
        type=float,
        default=1.5,
        help="token boost; larger is more sensitive and may cause more false triggers",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.20,
        help="trigger threshold from 0 to 1; lower is more sensitive",
    )
    parser.add_argument(
        "--device",
        help="sounddevice input device ID or name; omit to use the default microphone",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="list audio devices and exit without downloading the model",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "chudvis" / "wake-word-test",
        help="where to cache the downloaded model and generated keyword files",
    )
    args = parser.parse_args()
    if args.seconds < 0:
        parser.error("--seconds must be 0 or greater")
    if args.expected < 0:
        parser.error("--expected must be 0 or greater")
    if not 0 < args.threshold <= 1:
        parser.error("--threshold must be greater than 0 and at most 1")
    if args.score <= 0:
        parser.error("--score must be greater than 0")
    return args


def load_dependencies() -> tuple[object, object, object]:
    try:
        import numpy as np
        import sherpa_onnx
    except ImportError as exc:
        print(f"Missing dependency: {exc.name}", file=sys.stderr)
        print("Run this script with:", file=sys.stderr)
        print(
            "  uv run --no-project --with sherpa-onnx==1.13.4 "
            "--with sherpa-onnx-bin==1.13.4 "
            "--with sherpa-onnx-core==1.13.4 "
            "--with 'numpy>=1.24,<3' "
            "--with 'sentencepiece>=0.2' "
            "--with 'sounddevice>=0.4.7' -- "
            "python scripts/test-chudvis-wake-word.py",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    try:
        import sounddevice as sd
    except OSError as exc:
        print(f"Could not load microphone support: {exc}", file=sys.stderr)
        if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
            print(
                "This test is running inside WSL. Use the Windows microphone with: "
                "./scripts/test-chudvis-wake-word-windows.sh",
                file=sys.stderr,
            )
        elif sys.platform.startswith("linux"):
            print(
                "On Ubuntu, install PortAudio once with: "
                "sudo apt install libportaudio2",
                file=sys.stderr,
            )
        raise SystemExit(2) from exc
    return np, sherpa_onnx, sd


def download_model(cache_dir: Path) -> Path:
    model_dir = cache_dir / MODEL_NAME
    required = (
        model_dir / "tokens.txt",
        model_dir / "bpe.model",
        model_dir / ENCODER,
        model_dir / DECODER,
        model_dir / JOINER,
    )
    if all(
        path.is_file()
        and hashlib.sha256(path.read_bytes()).hexdigest()
        == MODEL_FILE_SHA256[path.name]
        for path in required
    ):
        return model_dir

    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / f"{MODEL_NAME}.tar.bz2"
    partial = archive.with_suffix(archive.suffix + ".part")
    print(f"Downloading the sherpa-onnx wake-word model to {cache_dir} ...")
    try:
        digest = hashlib.sha256()
        with urllib.request.urlopen(MODEL_URL) as response, partial.open("wb") as output:
            total = int(response.headers.get("Content-Length", 0))
            received = 0
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if total:
                    percent = received * 100 / total
                    print(
                        f"\r  {received / 1_048_576:.1f}/{total / 1_048_576:.1f} MiB "
                        f"({percent:.0f}%)",
                        end="",
                        flush=True,
                    )
        partial.replace(archive)
        print()
        if digest.hexdigest() != MODEL_ARCHIVE_SHA256:
            archive.unlink(missing_ok=True)
            raise RuntimeError("Downloaded wake-word archive failed checksum validation")
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    print("Extracting model ...")
    cache_root = cache_dir.resolve()
    with tarfile.open(archive, "r:bz2") as bundle:
        for member in bundle.getmembers():
            target = (cache_dir / member.name).resolve()
            try:
                target.relative_to(cache_root)
            except ValueError as exc:
                raise RuntimeError(f"Unsafe path in model archive: {member.name}") from exc
            if member.issym() or member.islnk():
                raise RuntimeError(f"Unexpected link in model archive: {member.name}")
        if sys.version_info >= (3, 12):
            bundle.extractall(cache_dir, filter="data")
        else:
            bundle.extractall(cache_dir)
    archive.unlink(missing_ok=True)

    invalid = [
        str(path)
        for path in required
        if not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_FILE_SHA256[path.name]
    ]
    if invalid:
        raise RuntimeError("Downloaded model failed asset validation: " + ", ".join(invalid))
    return model_dir


def make_keywords_file(model_dir: Path, spellings: list[str], cache_dir: Path) -> Path:
    normalized = list(dict.fromkeys(value.strip().upper() for value in spellings if value.strip()))
    if not normalized:
        raise RuntimeError("At least one non-empty --spelling is required")

    keywords_file = cache_dir / "chudvis-keywords.txt"
    try:
        import sentencepiece as spm
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "sentencepiece is missing. Run through the full uv command in this script's help."
        ) from exc

    processor = spm.SentencePieceProcessor(model_file=str(model_dir / "bpe.model"))
    encoded = processor.encode(normalized, out_type=str)
    known_tokens = {
        line.split()[0]
        for line in (model_dir / "tokens.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    unknown = sorted({token for tokens in encoded for token in tokens if token not in known_tokens})
    if unknown:
        raise RuntimeError(f"Wake-word spellings produced unknown model tokens: {unknown}")
    keywords_file.write_text(
        "\n".join(" ".join(str(token) for token in tokens) for tokens in encoded) + "\n",
        encoding="utf-8",
    )
    return keywords_file


def parse_device(device: str | None) -> str | int | None:
    if device is None:
        return None
    try:
        return int(device)
    except ValueError:
        return device


def level_meter(np: object, samples: object, width: int = 20) -> tuple[str, float]:
    rms = float(np.sqrt(np.mean(np.square(samples))))
    dbfs = 20 * math.log10(max(rms, 1e-7))
    filled = max(0, min(width, round((dbfs + 60) / 60 * width)))
    return "█" * filled + "·" * (width - filled), dbfs


def clear_status_line() -> None:
    if sys.stdout.isatty():
        print("\r\033[2K", end="")


def show_detection(number: int, result: str, elapsed: float) -> None:
    clear_status_line()
    print("\a", end="", flush=True)
    print("┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
    print(f"┃  🎙  CHUDVIS HEARD  #{number:<3}          ┃")
    print(f"┃  matched {result!r:<20} {elapsed:6.1f}s ┃")
    print("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")


def print_summary(detections: list[tuple[float, str]], expected: int, elapsed: float) -> None:
    clear_status_line()
    print("\nWake-word test summary")
    print(f"  listened:   {elapsed:.1f} seconds")
    print(f"  detections: {len(detections)}")
    if expected:
        print(f"  intended:   {expected} spoken attempts (your planned value)")
        ratio = len(detections) / expected * 100
        print(f"  rough ratio: {ratio:.0f}% (includes any false triggers)")
    if detections:
        aliases = Counter(result for _, result in detections)
        print("  matches:    " + ", ".join(f"{name} ×{count}" for name, count in aliases.items()))
    print()
    print("If it misses too often:   --score 2.0 --threshold 0.15")
    print("If it false-triggers:     --score 1.0 --threshold 0.30")


def run_test(args: argparse.Namespace, np: object, sherpa_onnx: object, sd: object) -> None:
    devices = sd.query_devices()
    if len(devices) == 0:
        if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
            raise RuntimeError(
                "No Linux audio devices were found because this is WSL. "
                "Run ./scripts/test-chudvis-wake-word-windows.sh so Windows Python can use "
                "the laptop microphone."
            )
        raise RuntimeError("No audio devices were found")
    if args.list_devices:
        print(devices)
        return

    model_dir = download_model(args.cache_dir)
    spellings = args.spellings or list(DEFAULT_SPELLINGS)
    keywords_file = make_keywords_file(model_dir, spellings, args.cache_dir)

    spotter = sherpa_onnx.KeywordSpotter(
        tokens=str(model_dir / "tokens.txt"),
        encoder=str(model_dir / ENCODER),
        decoder=str(model_dir / DECODER),
        joiner=str(model_dir / JOINER),
        keywords_file=str(keywords_file),
        num_threads=max(1, min(4, os.cpu_count() or 1)),
        max_active_paths=4,
        keywords_score=args.score,
        keywords_threshold=args.threshold,
        num_trailing_blanks=1,
        provider="cpu",
    )
    stream = spotter.create_stream()
    input_device = parse_device(args.device)
    selected = sd.query_devices(input_device, "input")

    duration = "until Ctrl+C" if args.seconds == 0 else f"for {args.seconds:g} seconds"
    print()
    print(f"Microphone: {selected['name']}")
    print(f"Accepted spellings: {', '.join(spellings)}")
    print(f"Sensitivity: score={args.score:g}, threshold={args.threshold:g}")
    print(f"Listening {duration}. Say 'chudvis' {args.expected} times, then try normal speech.")
    print("A terminal bell and large mic banner appear for every detection. Press Ctrl+C to stop.")
    print()

    detections: list[tuple[float, str]] = []
    overflow_count = 0
    started = time.monotonic()
    try:
        with sd.InputStream(
            channels=1,
            dtype="float32",
            samplerate=SAMPLE_RATE,
            blocksize=SAMPLES_PER_READ,
            device=input_device,
        ) as microphone:
            while args.seconds == 0 or time.monotonic() - started < args.seconds:
                samples, overflowed = microphone.read(SAMPLES_PER_READ)
                overflow_count += int(overflowed)
                samples = samples.reshape(-1)
                stream.accept_waveform(SAMPLE_RATE, samples)
                while spotter.is_ready(stream):
                    spotter.decode_stream(stream)
                    result = spotter.get_result(stream)
                    if result:
                        elapsed = time.monotonic() - started
                        detections.append((elapsed, result))
                        show_detection(len(detections), result, elapsed)
                        spotter.reset_stream(stream)
                meter, dbfs = level_meter(np, samples)
                print(
                    f"\r🎙  [{meter}] {dbfs:6.1f} dBFS  detections: {len(detections)}",
                    end="",
                    flush=True,
                )
    except KeyboardInterrupt:
        pass
    finally:
        elapsed = time.monotonic() - started
        print_summary(detections, args.expected, elapsed)
        if overflow_count:
            print(f"Warning: the microphone buffer overflowed {overflow_count} time(s).")


def main() -> int:
    for output in (sys.stdout, sys.stderr):
        if hasattr(output, "reconfigure"):
            output.reconfigure(errors="replace")
    args = parse_args()
    np, sherpa_onnx, sd = load_dependencies()
    try:
        run_test(args, np, sherpa_onnx, sd)
    except (OSError, RuntimeError) as exc:
        clear_status_line()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
