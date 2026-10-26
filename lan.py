from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import struct
import threading
import time
from typing import Callable, Optional
from urllib.parse import urlsplit

from PyQt6.QtCore import QObject, pyqtSignal


WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_PORT = 8765
DISCOVERY_PORT = 45876
MAX_MESSAGE_BYTES = 1_000_000
PROTOCOL_VERSION = 2
RATE_LIMIT_MESSAGES = 160
RATE_LIMIT_WINDOW = 1.0


class LanError(Exception):
    pass


def parse_address(address: str, default_port: int = DEFAULT_PORT) -> tuple[str, int]:
    raw = address.strip()
    if not raw:
        raise LanError("请输入联机地址")
    if "://" not in raw:
        raw = "http://" + raw
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise LanError("地址格式不正确") from exc

    scheme = parsed.scheme.lower()
    if scheme in ("https", "wss"):
        raise LanError("暂不支持 TLS（https/wss），请使用 http、tcp 或 ws")
    if scheme not in ("http", "ws", "tcp"):
        raise LanError("地址协议仅支持 http://、tcp:// 或 ws://")

    host = parsed.hostname
    if not host:
        raise LanError("地址中缺少主机名或 IP")
    try:
        port = parsed.port or default_port
    except ValueError as exc:
        raise LanError("端口无效") from exc
    if not 1 <= port <= 65535:
        raise LanError("端口必须在 1-65535 之间")
    return host, port


def get_lan_ip() -> str:
    candidates: list[str] = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            candidates.append(sock.getsockname()[0])
        finally:
            sock.close()
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(
            socket.gethostname(), None, socket.AF_INET
        ):
            candidates.append(info[4][0])
    except OSError:
        pass

    for ip in candidates:
        if ip and not ip.startswith("127."):
            return ip
    return candidates[0] if candidates else "127.0.0.1"


def _recv_exact(sock: socket.socket, buffer: bytearray, size: int) -> bytes:
    while len(buffer) < size:
        chunk = sock.recv(max(4096, size - len(buffer)))
        if not chunk:
            raise LanError("连接已关闭")
        buffer.extend(chunk)
    data = bytes(buffer[:size])
    del buffer[:size]
    return data


def _read_http_headers(
    sock: socket.socket, buffer: bytearray
) -> tuple[str, dict[str, str]]:
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            raise LanError("连接在握手时关闭")
        buffer.extend(chunk)
        if len(buffer) > 65536:
            raise LanError("握手数据过大")

    end = buffer.find(b"\r\n\r\n") + 4
    raw = bytes(buffer[:end])
    del buffer[:end]
    try:
        text = raw.decode("latin-1")
    except UnicodeDecodeError as exc:
        raise LanError("握手数据编码错误") from exc

    lines = text.split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return lines[0], headers


def _send_http_error(
    sock: socket.socket, status: str, message: str
) -> None:
    body = message.encode("utf-8")
    response = (
        f"HTTP/1.1 {status}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body
    try:
        sock.sendall(response)
    except OSError:
        pass


def _server_handshake(
    sock: socket.socket,
    buffer: bytearray,
    auth_token: str = "",
) -> None:
    request_line, headers = _read_http_headers(sock, buffer)
    upgrade = headers.get("upgrade", "").lower()
    connection = headers.get("connection", "").lower()
    key = headers.get("sec-websocket-key")

    if upgrade != "websocket" or "upgrade" not in connection or not key:
        body = (
            "LAN Chess WebSocket endpoint. "
            "Open the app and use the online dialog to connect."
        ).encode("utf-8")
        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii") + body
        try:
            sock.sendall(response)
        except OSError:
            pass
        raise LanError("对方没有发起 WebSocket 升级")

    version = headers.get("x-chess-version", "")
    if version != str(PROTOCOL_VERSION):
        _send_http_error(
            sock,
            "426 Upgrade Required",
            f"Protocol version {PROTOCOL_VERSION} required",
        )
        raise LanError(
            f"协议版本不兼容（需要 {PROTOCOL_VERSION}，收到 {version or '无'}）"
        )

    if auth_token:
        supplied = headers.get("x-chess-token", "")
        if not hmac.compare_digest(supplied, auth_token):
            _send_http_error(sock, "401 Unauthorized", "Invalid room password")
            raise LanError("房间密码错误")

    accept = base64.b64encode(
        hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
    ).decode("ascii")
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    sock.sendall(response.encode("ascii"))


def _client_handshake(
    sock: socket.socket,
    host: str,
    port: int,
    buffer: bytearray,
    auth_token: str = "",
) -> None:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    host_header = f"{host}:{port}"
    if ":" in host and not host.startswith("["):
        host_header = f"[{host}]:{port}"

    auth_header = (
        f"X-Chess-Token: {auth_token}\r\n" if auth_token else ""
    )
    request = (
        "GET / HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"X-Chess-Version: {PROTOCOL_VERSION}\r\n"
        f"{auth_header}"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))

    status_line, headers = _read_http_headers(sock, buffer)
    if " 101 " not in status_line:
        raise LanError(f"WebSocket 升级失败：{status_line}")

    expected = base64.b64encode(
        hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
    ).decode("ascii")
    if headers.get("sec-websocket-accept") != expected:
        raise LanError("WebSocket 握手校验失败")


def _mask_payload(payload: bytes, key: bytes) -> bytes:
    return bytes(byte ^ key[index % 4] for index, byte in enumerate(payload))


def _make_frame(opcode: int, payload: bytes, masked: bool) -> bytes:
    header = bytearray()
    header.append(0x80 | (opcode & 0x0F))
    length = len(payload)
    mask_bit = 0x80 if masked else 0
    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))

    if masked:
        key = os.urandom(4)
        header.extend(key)
        payload = _mask_payload(payload, key)
    return bytes(header) + payload


class WebSocketConnection:
    def __init__(
        self,
        sock: socket.socket,
        buffer: bytearray,
        is_client: bool,
        on_message: Callable[[str], None],
        on_close: Callable[[str], None],
    ) -> None:
        self.sock = sock
        self._buffer = buffer
        self.is_client = is_client
        self._on_message = on_message
        self._on_close = on_close
        self._send_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._closed = False
        self._notified = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._reader_loop, daemon=True
        )
        self._thread.start()

    @property
    def closed(self) -> bool:
        return self._closed

    def send_json(self, data: dict) -> None:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        self._send_frame(0x1, text.encode("utf-8"))

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        with self._send_lock:
            if self._closed:
                raise LanError("连接已关闭")
            try:
                self.sock.sendall(
                    _make_frame(opcode, payload, self.is_client)
                )
            except OSError as exc:
                raise LanError(f"发送失败：{exc}") from exc

    def _reader_loop(self) -> None:
        reason = "对方已断开连接"
        fragments = bytearray()
        fragment_opcode: Optional[int] = None
        try:
            while not self._closed:
                header = _recv_exact(self.sock, self._buffer, 2)
                first, second = header[0], header[1]
                fin = bool(first & 0x80)
                opcode = first & 0x0F
                masked = bool(second & 0x80)
                length = second & 0x7F

                if length == 126:
                    length = struct.unpack(
                        "!H", _recv_exact(self.sock, self._buffer, 2)
                    )[0]
                elif length == 127:
                    length = struct.unpack(
                        "!Q", _recv_exact(self.sock, self._buffer, 8)
                    )[0]

                if length > MAX_MESSAGE_BYTES:
                    raise LanError("收到的消息过大")

                mask_key = (
                    _recv_exact(self.sock, self._buffer, 4)
                    if masked
                    else None
                )
                payload = _recv_exact(self.sock, self._buffer, length)
                if mask_key is not None:
                    payload = _mask_payload(payload, mask_key)

                if opcode == 0x8:
                    reason = "对方已断开连接"
                    break
                if opcode == 0x9:
                    try:
                        self._send_frame(0xA, payload)
                    except LanError:
                        break
                    continue
                if opcode == 0xA:
                    continue

                if opcode in (0x1, 0x2):
                    fragments = bytearray(payload)
                    fragment_opcode = opcode
                elif opcode == 0x0:
                    if fragment_opcode is None:
                        raise LanError("收到无效的 WebSocket 分片")
                    fragments.extend(payload)
                    if len(fragments) > MAX_MESSAGE_BYTES:
                        raise LanError("收到的分片消息过大")
                else:
                    continue

                if fin:
                    message = bytes(fragments)
                    fragments = bytearray()
                    if fragment_opcode == 0x1:
                        self._on_message(message.decode("utf-8", "replace"))
                    fragment_opcode = None
        except (OSError, LanError, ConnectionError) as exc:
            reason = str(exc) if isinstance(exc, LanError) else "连接已中断"
        finally:
            self._notify_close(reason)

    def _notify_close(self, reason: str) -> None:
        with self._state_lock:
            if self._notified:
                return
            self._notified = True
            self._closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        self._on_close(reason)

    def close(self) -> None:
        with self._send_lock:
            if self._closed:
                return
            try:
                self.sock.sendall(
                    _make_frame(0x8, struct.pack("!H", 1000), self.is_client)
                )
            except OSError:
                pass
            self._closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class LanManager(QObject):
    hosting = pyqtSignal(str, str, str)
    connected = pyqtSignal(bool)
    messageReceived = pyqtSignal(dict)
    disconnected = pyqtSignal(str)
    errorOccurred = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._lock = threading.RLock()
        self._token = 0
        self._listener: Optional[socket.socket] = None
        self._conn: Optional[WebSocketConnection] = None
        self._stop = threading.Event()
        self._discovery_stop: Optional[threading.Event] = None
        self._send_seq = 0
        self._recv_seq = 0
        self._rate_start = time.monotonic()
        self._rate_count = 0

    def _stop_discovery(self) -> None:
        with self._lock:
            stop = self._discovery_stop
            self._discovery_stop = None
        if stop is not None:
            stop.set()

    def _prepare_session(self) -> tuple[int, threading.Event]:
        self._stop_discovery()
        with self._lock:
            self._stop.set()
            listener = self._listener
            conn = self._conn
            self._listener = None
            self._conn = None
            self._send_seq = 0
            self._recv_seq = 0
            self._rate_start = time.monotonic()
            self._rate_count = 0
            self._token += 1
            token = self._token
            stop = threading.Event()
            self._stop = stop

        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if conn is not None:
            conn.close()
        return token, stop

    def host(self, port: int, password: str = "") -> bool:
        token, stop = self._prepare_session()
        auth_token = (
            hashlib.sha256(password.encode("utf-8")).hexdigest()
            if password
            else ""
        )
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", int(port)))
            listener.listen(2)
            listener.settimeout(0.5)
        except OSError as exc:
            try:
                listener.close()
            except OSError:
                pass
            self.errorOccurred.emit(f"无法监听端口 {port}：{exc}")
            return False

        with self._lock:
            if token != self._token:
                listener.close()
                return False
            self._listener = listener

        ip = get_lan_ip()
        http = f"http://{ip}:{port}"
        tcp = f"tcp://{ip}:{port}"
        ws = f"ws://{ip}:{port}"
        self.hosting.emit(http, tcp, ws)

        discovery_stop = threading.Event()
        with self._lock:
            self._discovery_stop = discovery_stop
        threading.Thread(
            target=self._broadcast_loop,
            args=(port, ip, discovery_stop),
            daemon=True,
        ).start()

        threading.Thread(
            target=self._accept_loop,
            args=(listener, stop, token, auth_token),
            daemon=True,
        ).start()
        return True

    def _broadcast_loop(
        self, port: int, ip: str, stop: threading.Event
    ) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            payload = json.dumps(
                {
                    "type": "chess_room",
                    "name": f"{socket.gethostname()} 的棋室",
                    "ip": ip,
                    "port": port,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            targets = {"255.255.255.255"}
            if ip.count(".") == 3:
                targets.add(ip.rsplit(".", 1)[0] + ".255")
            while not stop.is_set():
                for target in targets:
                    try:
                        sock.sendto(payload, (target, DISCOVERY_PORT))
                    except OSError:
                        pass
                stop.wait(1.8)
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def _accept_loop(
        self,
        listener: socket.socket,
        stop: threading.Event,
        token: int,
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
                    client.close()
                    return

                try:
                    client.settimeout(10.0)
                    _configure_socket(client)
                    buffer = bytearray()
                    _server_handshake(client, buffer, auth_token)
                    client.settimeout(None)
                except (OSError, LanError) as exc:
                    try:
                        client.close()
                    except OSError:
                        pass
                    if not stop.is_set() and token == self._token:
                        self.errorOccurred.emit(f"连接握手失败：{exc}")
                    continue

                try:
                    listener.close()
                except OSError:
                    pass
                self._stop_discovery()

                connection = WebSocketConnection(
                    client,
                    buffer,
                    is_client=False,
                    on_message=lambda text: self._handle_text(token, text),
                    on_close=lambda reason: self._handle_close(token, reason),
                )
                with self._lock:
                    if token != self._token:
                        connection.close()
                        return
                    self._conn = connection
                    self._listener = None
                connection.start()
                if token == self._token:
                    self.connected.emit(True)
                return
        except OSError:
            pass
        finally:
            try:
                listener.close()
            except OSError:
                pass

    def connect(self, address: str, password: str = "") -> bool:
        try:
            host, port = parse_address(address)
        except LanError as exc:
            self.errorOccurred.emit(str(exc))
            return False

        token, stop = self._prepare_session()
        auth_token = (
            hashlib.sha256(password.encode("utf-8")).hexdigest()
            if password
            else ""
        )
        threading.Thread(
            target=self._connect_loop,
            args=(host, port, token, stop, auth_token),
            daemon=True,
        ).start()
        return True

    def _connect_loop(
        self,
        host: str,
        port: int,
        token: int,
        stop: threading.Event,
        auth_token: str,
    ) -> None:
        sock: Optional[socket.socket] = None
        try:
            sock = socket.create_connection((host, port), timeout=8.0)
            _configure_socket(sock)
            sock.settimeout(10.0)
            buffer = bytearray()
            _client_handshake(sock, host, port, buffer, auth_token)
            sock.settimeout(None)
            if stop.is_set() or token != self._token:
                sock.close()
                return

            connection = WebSocketConnection(
                sock,
                buffer,
                is_client=True,
                on_message=lambda text: self._handle_text(token, text),
                on_close=lambda reason: self._handle_close(token, reason),
            )
            with self._lock:
                if token != self._token:
                    connection.close()
                    return
                self._conn = connection
            connection.start()
            if token == self._token:
                self.connected.emit(False)
        except (OSError, LanError) as exc:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            if not stop.is_set() and token == self._token:
                self.errorOccurred.emit(f"连接失败：{exc}")

    def _handle_text(self, token: int, text: str) -> None:
        if token != self._token:
            return
        now = time.monotonic()
        with self._lock:
            if now - self._rate_start > RATE_LIMIT_WINDOW:
                self._rate_start = now
                self._rate_count = 0
            self._rate_count += 1
            if self._rate_count > RATE_LIMIT_MESSAGES:
                self.errorOccurred.emit("联机消息过于频繁，已忽略")
                return
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(data, dict):
            return
        if data.get("v") != PROTOCOL_VERSION:
            self.errorOccurred.emit("联机协议版本不兼容")
            return
        seq = data.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            return
        with self._lock:
            if seq <= self._recv_seq:
                return
            self._recv_seq = seq
        self.messageReceived.emit(data)

    def _handle_close(self, token: int, reason: str) -> None:
        self._stop_discovery()
        with self._lock:
            if token != self._token:
                return
            self._token += 1
            self._conn = None
            self._stop.set()
            listener = self._listener
            self._listener = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        self.disconnected.emit(reason)

    def send(self, data: dict) -> bool:
        with self._lock:
            connection = self._conn
            if connection is None:
                return False
            self._send_seq += 1
            payload = dict(data)
            payload["v"] = PROTOCOL_VERSION
            payload["seq"] = self._send_seq
        try:
            connection.send_json(payload)
            return True
        except LanError as exc:
            self.errorOccurred.emit(str(exc))
            return False

    def is_connected(self) -> bool:
        with self._lock:
            return self._conn is not None and not self._conn.closed

    def disconnect(self, reason: str = "已断开连接") -> None:
        self._stop_discovery()
        with self._lock:
            self._stop.set()
            listener = self._listener
            conn = self._conn
            self._listener = None
            self._conn = None
            self._token += 1
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if conn is not None:
            conn.close()
        self.disconnected.emit(reason)

    def shutdown(self) -> None:
        self._stop_discovery()
        with self._lock:
            self._stop.set()
            listener = self._listener
            conn = self._conn
            self._listener = None
            self._conn = None
            self._token += 1
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if conn is not None:
            conn.close()


def _configure_socket(sock: socket.socket) -> None:
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        pass


class LanDiscovery(QObject):
    roomFound = pyqtSignal(dict)
    errorOccurred = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.is_running():
            return True
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", DISCOVERY_PORT))
            sock.settimeout(0.5)
        except OSError as exc:
            try:
                sock.close()
            except OSError:
                pass
            self.errorOccurred.emit(f"无法搜索局域网房间：{exc}")
            return False

        self._sock = sock
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, args=(sock, self._stop), daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        self._thread = None

    def _loop(self, sock: socket.socket, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                data, address = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                message = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(message, dict):
                continue
            if message.get("type") != "chess_room":
                continue
            try:
                port = int(message.get("port"))
            except (TypeError, ValueError):
                continue
            if not 1 <= port <= 65535:
                continue
            ip = str(message.get("ip") or address[0])
            name = str(message.get("name") or "国际象棋房间")[:60]
            self.roomFound.emit(
                {"name": name, "ip": ip, "port": port}
            )
