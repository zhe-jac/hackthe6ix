from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

MODEL_NAME = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/"
    f"{MODEL_NAME}.tar.bz2"
)
MODEL_ARCHIVE_SHA256 = "f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a"
MODEL_LICENSE = "Apache-2.0"
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


class WakeWordDetector(Protocol):
    def accept(self, samples: Sequence[float]) -> bool: ...

    def reset(self) -> None: ...


class UrlResponse(Protocol):
    headers: Any

    def read(self, size: int = -1) -> bytes: ...

    def __enter__(self) -> UrlResponse: ...

    def __exit__(self, *args: object) -> None: ...


UrlOpen = Callable[[str], UrlResponse]


def default_wake_cache_dir() -> Path:
    root = os.environ.get("XDG_CACHE_HOME")
    cache = Path(root) if root else Path.home() / ".cache"
    return cache / "chudvis" / "wake-word"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_model_files(model_dir: Path) -> bool:
    return all(
        (model_dir / name).is_file() and _sha256_file(model_dir / name) == expected
        for name, expected in MODEL_FILE_SHA256.items()
    )


def _safe_members(bundle: tarfile.TarFile, destination: Path) -> list[tarfile.TarInfo]:
    root = destination.resolve()
    members = bundle.getmembers()
    for member in members:
        target = (destination / member.name).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"Unsafe path in wake-word archive: {member.name}") from exc
        if member.issym() or member.islnk() or not (member.isdir() or member.isreg()):
            raise RuntimeError(f"Unsupported entry in wake-word archive: {member.name}")
    return members


def extract_model_archive(archive: Path, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:bz2") as bundle:
        members = _safe_members(bundle, cache_dir)
        for member in members:
            target = cache_dir / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise RuntimeError(f"Could not read wake-word asset: {member.name}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    model_dir = cache_dir / MODEL_NAME
    if not validate_model_files(model_dir):
        raise RuntimeError("Wake-word model assets failed checksum validation")
    return model_dir


def ensure_wake_model(
    cache_dir: Path | None = None,
    *,
    urlopen: UrlOpen = urllib.request.urlopen,
) -> Path:
    cache_dir = cache_dir or default_wake_cache_dir()
    model_dir = cache_dir / MODEL_NAME
    if validate_model_files(model_dir):
        return model_dir

    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / f"{MODEL_NAME}.tar.bz2"
    partial = archive.with_suffix(".tar.bz2.part")
    try:
        digest = hashlib.sha256()
        with urlopen(MODEL_URL) as response, partial.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != MODEL_ARCHIVE_SHA256:
            raise RuntimeError("Downloaded wake-word archive failed checksum validation")
        partial.replace(archive)
        return extract_model_archive(archive, cache_dir)
    finally:
        partial.unlink(missing_ok=True)
        archive.unlink(missing_ok=True)


def make_keywords_file(model_dir: Path, spellings: Sequence[str], cache_dir: Path) -> Path:
    normalized = list(dict.fromkeys(value.strip().upper() for value in spellings if value.strip()))
    if not normalized:
        raise RuntimeError("At least one wake-word spelling is required")
    try:
        import sentencepiece as spm
    except ImportError as exc:
        raise RuntimeError("sentencepiece is required for Chudvis wake-word detection") from exc

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
    keywords_file = cache_dir / "chudvis-keywords.txt"
    keywords_file.write_text(
        "\n".join(" ".join(str(token) for token in tokens) for tokens in encoded) + "\n",
        encoding="utf-8",
    )
    return keywords_file


class SherpaWakeWordDetector:
    """Small local keyword spotter. Network access occurs only while provisioning assets."""

    def __init__(
        self,
        spellings: Sequence[str],
        score: float,
        threshold: float,
        cache_dir: Path | None = None,
    ) -> None:
        if score <= 0 or not 0 < threshold <= 1:
            raise ValueError("Invalid wake-word sensitivity")
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError("sherpa-onnx is required for Chudvis wake-word detection") from exc
        cache = cache_dir or default_wake_cache_dir()
        model_dir = ensure_wake_model(cache)
        keywords = make_keywords_file(model_dir, spellings, cache)
        self._spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(model_dir / "tokens.txt"),
            encoder=str(model_dir / ENCODER),
            decoder=str(model_dir / DECODER),
            joiner=str(model_dir / JOINER),
            keywords_file=str(keywords),
            num_threads=max(1, min(4, os.cpu_count() or 1)),
            max_active_paths=4,
            keywords_score=score,
            keywords_threshold=threshold,
            num_trailing_blanks=1,
            provider="cpu",
        )
        self._stream = self._spotter.create_stream()

    def accept(self, samples: Sequence[float]) -> bool:
        self._stream.accept_waveform(16_000, samples)
        while self._spotter.is_ready(self._stream):
            self._spotter.decode_stream(self._stream)
            if self._spotter.get_result(self._stream):
                self.reset()
                return True
        return False

    def reset(self) -> None:
        self._spotter.reset_stream(self._stream)
