from __future__ import annotations

import pytest

from gazemotion.ide.protocol import ProtocolError, decode_message, encode_message, notification


def test_protocol_notification_round_trip() -> None:
    original = notification("editor.scroll", {"lines": 4})

    decoded = decode_message(encode_message(original, 1024).rstrip(b"\n"), 1024)

    assert decoded == original


def test_protocol_rejects_non_object_params() -> None:
    with pytest.raises(ProtocolError, match="params"):
        decode_message(b'{"jsonrpc":"2.0","method":"bad","params":[]}', 1024)


def test_protocol_enforces_message_limit() -> None:
    with pytest.raises(ProtocolError, match="exceeds"):
        encode_message(notification("request.preview", {"transcript": "x" * 2000}), 1024)
