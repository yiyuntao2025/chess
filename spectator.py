from __future__ import annotations

import hashlib
import socket
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from lan import (
    PROTOCOL_VERSION,
    LanError,
    WebSocketConnection,
    _configure_socket,
    _server_handshake,
    get_lan_ip,
)


class SpectatorServer(QObject):
    errorOccurred = pyqtSignal(str)
    hosting = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._lock = threading.RLock()
        self._listener: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._connections: list[WebSocketConnection] = []
        self._state: Optional[dict] = None
        self._send_seq = 0

    def start(self, port: int, password: str = "") -> bool:
        self.stop()
        auth_token = (
            hashlib.sha256(password.encode("utf-8")).hexdigest()
            if password
            else ""
        )
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", int(port)))
            listener.listen(8)
            listener.settimeout(0.5)
        except OSError as exc:
            try:
                listener.close()
            except OSError:
                pass
            self.errorOccurred.emit(f"无法启动观战端口 {port}：{exc}")
            return False

        stop = threading.Event()
        with self._lock:
            self._listener = listener
            self._stop = stop
            self._state = None
            self._send_seq = 0
        self.hosting.emit(f"ws://{get_lan_ip()}:{port}")
        threading.Thread(
            target=self._accept_loop,
            args=(listener, stop, auth_token),
            daemon=True,
        ).start()
        return True

    def _accept_loop(
        self,
        listener: socket.socket,
        stop: threading.Event,
        auth_token: str,
    ) -> None:
        try:
            while not stop.is_set():
                try:
                    client, _address = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                if stop.is_set():
                    try:
                        client.close()
                    except OSError:
                        pass
                    break
                try:
                    client.settimeout(10.0)
                    _configure_socket(client)
                    buffer = bytearray()
                    _server_handshake(client, buffer, auth_token)
                    client.settimeout(None)
                except (OSError, LanError):
                    try:
                        client.close()
                    except OSError:
                        pass
                    continue

                connection = WebSocketConnection(
                    client,
                    buffer,
                    is_client=False,
                    on_message=lambda _text: None,
                    on_close=self._remove_connection,
                )
                with self._lock:
                    if stop.is_set():
                        connection.close()
                        break
                    self._connections.append(connection)
                    state = dict(self._state) if self._state else None
                connection.start()
                if state is not None:
                    try:
                        self._send_to(connection, state)
                    except LanError:
                        connection.close()
                        self._remove_connection("发送观战状态失败")
        finally:
            try:
                listener.close()
            except OSError:
                pass

    def _remove_connection(self, reason: str) -> None:
        del reason
        with self._lock:
            self._connections = [
                item for item in self._connections if not item.closed
            ]

    def _send_to(self, connection: WebSocketConnection, data: dict) -> None:
        with self._lock:
            self._send_seq += 1
            seq = self._send_seq
        payload = dict(data)
        payload["v"] = PROTOCOL_VERSION
        payload["seq"] = seq
        connection.send_json(payload)

    def set_state(self, state: dict) -> None:
        with self._lock:
            self._state = dict(state)
            connections = list(self._connections)
        for connection in connections:
            try:
                self._send_to(connection, state)
            except LanError:
                connection.close()
                self._remove_connection("观战连接已断开")

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            listener = self._listener
            self._listener = None
            connections = list(self._connections)
            self._connections = []
            self._state = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        for connection in connections:
            connection.close()
