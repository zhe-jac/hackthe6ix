from __future__ import annotations

import queue
import select
import socket
from collections.abc import Callable, Mapping
from threading import Event, Lock, Thread
from typing import Any

from gazemotion.ide.protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    decode_message,
    encode_message,
    notification,
)

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class IdeTransport:
    """Non-blocking JSON notification client for the local editor extension."""

    def __init__(
        self,
        host: str,
        port: int,
        session_token: str = "",
        reconnect_delay_seconds: float = 1.0,
        max_message_bytes: int = 262_144,
        status: Callable[[str], None] = print,
    ) -> None:
        if host not in _LOCAL_HOSTS:
            raise ValueError("IDE transport must bind to a loopback host")
        if not 1 <= port <= 65535:
            raise ValueError("IDE transport port must be between 1 and 65535")
        self.host = host
        self.port = port
        self.session_token = session_token
        self.reconnect_delay_seconds = max(reconnect_delay_seconds, 0.05)
        self.max_message_bytes = max(max_message_bytes, 1024)
        self.status = status
        self._outbound: queue.Queue[dict[str, object]] = queue.Queue(maxsize=256)
        self._inbound: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=256)
        self._stop = Event()
        self._connected = Event()
        self._thread: Thread | None = None
        self._thread_lock = Lock()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(target=self._run, name="gazemotion-ide", daemon=True)
            self._thread.start()

    def notify(
        self,
        method: str,
        params: Mapping[str, object] | None = None,
        *,
        continuous: bool = False,
    ) -> bool:
        message = notification(method, params)
        try:
            self._outbound.put_nowait(message)
            return True
        except queue.Full:
            if not continuous:
                self.status(f"IDE command dropped because the bridge queue is full: {method}")
            return False

    def poll(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        while True:
            try:
                messages.append(self._inbound.get_nowait())
            except queue.Empty:
                return messages

    def _discard_outbound(self) -> None:
        while True:
            try:
                self._outbound.get_nowait()
            except queue.Empty:
                return

    def _queue_inbound(self, message: dict[str, Any]) -> None:
        try:
            self._inbound.put_nowait(message)
        except queue.Full:
            try:
                self._inbound.get_nowait()
            except queue.Empty:
                pass
            self._inbound.put_nowait(message)

    def _hello(self) -> bytes:
        return encode_message(
            notification(
                "bridge.hello",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "client": "gazemotion-python",
                    "sessionToken": self.session_token,
                },
            ),
            self.max_message_bytes,
        )

    def _connected_loop(self, connection: socket.socket) -> None:
        connection.setblocking(False)
        outgoing = bytearray(self._hello())
        incoming = bytearray()
        self._connected.set()
        self.status(f"Connected to IDE extension at {self.host}:{self.port}")
        while not self._stop.is_set():
            while len(outgoing) < self.max_message_bytes * 2:
                try:
                    message = self._outbound.get_nowait()
                except queue.Empty:
                    break
                outgoing.extend(encode_message(message, self.max_message_bytes))

            readable, writable, exceptional = select.select(
                [connection],
                [connection] if outgoing else [],
                [connection],
                0.05,
            )
            if exceptional:
                raise ConnectionError("IDE extension socket failed")
            if writable:
                sent = connection.send(outgoing)
                del outgoing[:sent]
            if readable:
                chunk = connection.recv(65_536)
                if not chunk:
                    raise ConnectionError("IDE extension closed the connection")
                incoming.extend(chunk)
                if len(incoming) > self.max_message_bytes and b"\n" not in incoming:
                    raise ProtocolError("Unterminated IDE message exceeds the size limit")
                while b"\n" in incoming:
                    raw_line, _, remainder = incoming.partition(b"\n")
                    incoming = bytearray(remainder)
                    if raw_line:
                        self._queue_inbound(
                            decode_message(bytes(raw_line), self.max_message_bytes)
                        )

    def _run(self) -> None:
        announced_waiting = False
        while not self._stop.is_set():
            connection: socket.socket | None = None
            try:
                connection = socket.create_connection((self.host, self.port), timeout=1.0)
                announced_waiting = False
                self._connected_loop(connection)
            except (OSError, ConnectionError, ProtocolError) as exc:
                if not announced_waiting and not self._stop.is_set():
                    self.status(f"Waiting for IDE extension at {self.host}:{self.port}: {exc}")
                    announced_waiting = True
            finally:
                self._connected.clear()
                if connection is not None:
                    try:
                        connection.close()
                    except OSError:
                        pass
                # Commands captured for an old editor state are unsafe after reconnecting.
                self._discard_outbound()
            self._stop.wait(self.reconnect_delay_seconds)

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._connected.clear()
