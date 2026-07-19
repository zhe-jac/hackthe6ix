from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

PROTOCOL_VERSION = 1
JSONRPC_VERSION = "2.0"


class ProtocolError(ValueError):
    pass


def notification(method: str, params: Mapping[str, object] | None = None) -> dict[str, object]:
    if not method or not isinstance(method, str):
        raise ProtocolError("Protocol method must be a non-empty string")
    return {
        "jsonrpc": JSONRPC_VERSION,
        "method": method,
        "params": dict(params or {}),
    }


def encode_message(message: Mapping[str, object], max_bytes: int) -> bytes:
    try:
        encoded = json.dumps(
            dict(message),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"Message is not JSON serializable: {exc}") from exc
    if len(encoded) > max_bytes:
        raise ProtocolError(f"Message exceeds the {max_bytes}-byte limit")
    return encoded + b"\n"


def decode_message(line: bytes, max_bytes: int) -> dict[str, Any]:
    if len(line) > max_bytes:
        raise ProtocolError(f"Message exceeds the {max_bytes}-byte limit")
    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"Invalid protocol JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("Protocol message must be an object")
    if message.get("jsonrpc") != JSONRPC_VERSION:
        raise ProtocolError("Unsupported JSON-RPC version")
    method = message.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolError("Protocol notification requires a method")
    params = message.get("params", {})
    if not isinstance(params, dict):
        raise ProtocolError("Protocol notification params must be an object")
    return message
