from __future__ import annotations

import json
from pathlib import Path

from chudvis.ide.protocol import notification


def test_shared_protocol_schema_matches_notification_envelope() -> None:
    schema_path = Path(__file__).parents[1] / "protocol" / "ide-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    message = notification("bridge.status", {"message": "ready"})

    assert set(message) == set(schema["required"])
    assert message["jsonrpc"] == schema["properties"]["jsonrpc"]["const"]
    assert "listening" in schema["$defs"]["voiceStateParams"]["properties"]["state"]["enum"]
    assert any(
        rule.get("if", {}).get("properties", {}).get("method", {}).get("const")
        == "voice.complete"
        for rule in schema["allOf"]
    )
