from __future__ import annotations

import queue
import socket
from threading import Thread
from time import monotonic, sleep

from chudvis.ide.protocol import decode_message, encode_message, notification
from chudvis.ide.transport import IdeTransport


def test_transport_handshake_send_and_receive() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(2.0)
    port = listener.getsockname()[1]
    received: queue.Queue[dict[str, object]] = queue.Queue()

    def serve() -> None:
        connection, _address = listener.accept()
        with connection, connection.makefile("rb") as stream:
            received.put(decode_message(stream.readline().rstrip(b"\n"), 4096))
            received.put(decode_message(stream.readline().rstrip(b"\n"), 4096))
            connection.sendall(
                encode_message(
                    notification("bridge.status", {"message": "extension ready"}),
                    4096,
                )
            )

    server = Thread(target=serve, daemon=True)
    server.start()
    transport = IdeTransport(
        "127.0.0.1",
        port,
        "secret",
        reconnect_delay_seconds=0.05,
        max_message_bytes=4096,
        status=lambda _message: None,
    )
    try:
        transport.start()
        assert transport._connected.wait(timeout=2.0)
        assert transport.notify("editor.scroll", {"lines": 3})

        hello = received.get(timeout=2.0)
        command = received.get(timeout=2.0)
        server.join(timeout=2.0)

        assert hello["method"] == "bridge.hello"
        assert hello["params"]["sessionToken"] == "secret"
        assert command["method"] == "editor.scroll"
        messages: list[dict[str, object]] = []
        deadline = monotonic() + 2.0
        while not messages and monotonic() < deadline:
            messages = transport.poll()
            if not messages:
                sleep(0.01)
        assert messages[0]["params"]["message"] == "extension ready"
    finally:
        transport.close()
        listener.close()
