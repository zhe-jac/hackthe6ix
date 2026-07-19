from __future__ import annotations

import io
import tarfile

import pytest

from chudvis.speech.wake_word import (
    ensure_wake_model,
    extract_model_archive,
    validate_model_files,
)


class FakeResponse:
    headers: dict[str, str] = {}

    def __init__(self, content: bytes) -> None:
        self._content = io.BytesIO(content)

    def read(self, size: int = -1) -> bytes:
        return self._content.read(size)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def test_model_cache_rejects_missing_or_modified_assets(tmp_path) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "tokens.txt").write_text("modified", encoding="utf-8")

    assert not validate_model_files(model)


def test_download_rejects_archive_with_wrong_checksum(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="checksum"):
        ensure_wake_model(tmp_path, urlopen=lambda _url: FakeResponse(b"not the model"))

    assert not (tmp_path / "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2").exists()


def test_archive_traversal_is_rejected_before_extraction(tmp_path) -> None:
    archive = tmp_path / "malicious.tar.bz2"
    with tarfile.open(archive, "w:bz2") as bundle:
        member = tarfile.TarInfo("../../outside.txt")
        content = b"unsafe"
        member.size = len(content)
        bundle.addfile(member, io.BytesIO(content))

    with pytest.raises(RuntimeError, match="Unsafe path"):
        extract_model_archive(archive, tmp_path / "cache")

    assert not (tmp_path / "outside.txt").exists()


def test_archive_links_are_rejected(tmp_path) -> None:
    archive = tmp_path / "link.tar.bz2"
    with tarfile.open(archive, "w:bz2") as bundle:
        member = tarfile.TarInfo("model/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        bundle.addfile(member)

    with pytest.raises(RuntimeError, match="Unsupported entry"):
        extract_model_archive(archive, tmp_path / "cache")
