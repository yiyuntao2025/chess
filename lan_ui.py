from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from lan import LanDiscovery, LanManager


class NetworkDialog(QDialog):
    def __init__(
        self, manager: LanManager, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self._state = "idle"
        self._is_host = False
        self._http_address = ""
        self._tcp_address = ""
        self._ws_address = ""
        self._rooms: dict[tuple[str, int], dict] = {}
        self.settings = QSettings("ChessPyQt", "Chess")
        self.discovery = LanDiscovery(self)
        self.discovery.roomFound.connect(self._on_room_found)
        self.discovery.errorOccurred.connect(self._on_discovery_error)
        self._room_timer = QTimer(self)
        self._room_timer.setInterval(3000)
        self._room_timer.timeout.connect(self._prune_rooms)

        self.setWindowTitle("局域网联机")
        self.setModal(False)
        self.setMinimumSize(540, 620)
        self.resize(560, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        hint = QLabel(
            "房主执白，加入方执黑。连接后自动升级为 WebSocket 协议；"
            "关闭本窗口不会断开连接。\n"
            "请确保双方在同一局域网，并允许防火墙放行所选端口"
            "（自动发现还需 UDP 45876）。\n"
            "房间密码只用于握手校验，当前连接未启用 TLS 加密。"
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        host_group = QGroupBox("发起联机")
        host_layout = QVBoxLayout(host_group)
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("端口"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(8765)
        port_row.addWidget(self.port_spin, 1)
        self.host_button = QPushButton("创建房间")
        self.host_button.clicked.connect(self._start_host)
        port_row.addWidget(self.host_button)
        host_layout.addLayout(port_row)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("局时（分钟）"))
        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(1, 180)
        self.minutes_spin.setValue(
            max(
                1,
                min(
                    180,
                    int(self.settings.value("online_clock_minutes", 10)),
                ),
            )
        )
        time_row.addWidget(self.minutes_spin)
        time_row.addWidget(QLabel("加秒（秒/步）"))
        self.increment_spin = QSpinBox()
        self.increment_spin.setRange(0, 60)
        self.increment_spin.setValue(
            max(
                0,
                min(
                    60,
                    int(self.settings.value("online_clock_increment", 0)),
                ),
            )
        )
        time_row.addWidget(self.increment_spin)
        time_row.addStretch()
        host_layout.addLayout(time_row)
        time_hint = QLabel("联机棋钟由房主设置，连接方自动同步。")
        time_hint.setObjectName("HintLabel")
        host_layout.addWidget(time_hint)

        self.host_password_edit = QLineEdit()
        self.host_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.host_password_edit.setPlaceholderText(
            "可选房间密码（留空则不设密码）"
        )
        host_layout.addWidget(self.host_password_edit)

        address_row = QHBoxLayout()
        self.address_display = QLineEdit()
        self.address_display.setReadOnly(True)
        self.address_display.setPlaceholderText("创建房间后显示联机地址")
        address_row.addWidget(self.address_display, 1)
        self.copy_button = QPushButton("复制")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._copy_address)
        address_row.addWidget(self.copy_button)
        host_layout.addLayout(address_row)

        self.tcp_label = QLabel("")
        self.tcp_label.setObjectName("HintLabel")
        self.tcp_label.setWordWrap(True)
        self.tcp_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        host_layout.addWidget(self.tcp_label)
        root.addWidget(host_group)

        connect_group = QGroupBox("加入联机")
        connect_layout = QVBoxLayout(connect_group)
        address_row = QHBoxLayout()
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText(
            "http://192.168.1.10:8765 或 tcp://192.168.1.10:8765"
        )
        self.address_input.returnPressed.connect(self._start_connect)
        address_row.addWidget(self.address_input, 1)
        self.connect_button = QPushButton("连接")
        self.connect_button.clicked.connect(self._start_connect)
        address_row.addWidget(self.connect_button)
        connect_layout.addLayout(address_row)

        self.join_password_edit = QLineEdit()
        self.join_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.join_password_edit.setPlaceholderText(
            "房间密码（如果房主设置了密码）"
        )
        connect_layout.addWidget(self.join_password_edit)

        discovery_row = QHBoxLayout()
        self.search_button = QPushButton("搜索局域网房间")
        self.search_button.clicked.connect(self._toggle_discovery)
        discovery_row.addWidget(self.search_button)
        self.room_combo = QComboBox()
        self.room_combo.setEnabled(False)
        self.room_combo.addItem("未发现房间", None)
        self.room_combo.currentIndexChanged.connect(self._on_room_selected)
        self.room_combo.activated.connect(self._on_room_selected)
        discovery_row.addWidget(self.room_combo, 1)
        connect_layout.addLayout(discovery_row)
        root.addWidget(connect_group)

        self.status_label = QLabel("未连接")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        chat_group = QGroupBox("聊天")
        chat_layout = QVBoxLayout(chat_group)
        self.chat_log = QPlainTextEdit()
        self.chat_log.setReadOnly(True)
        self.chat_log.setPlaceholderText("连接后可以聊天")
        chat_layout.addWidget(self.chat_log, 1)
        chat_row = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("输入聊天内容，回车发送")
        self.chat_input.returnPressed.connect(self._send_chat)
        chat_row.addWidget(self.chat_input, 1)
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self._send_chat)
        chat_row.addWidget(self.send_button)
        chat_layout.addLayout(chat_row)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(6)
        self.quick_buttons: list[QPushButton] = []
        for text in ("你好", "好棋！", "请稍等", "再来一局"):
            button = QPushButton(text)
            button.setObjectName("QuickButton")
            button.setEnabled(False)
            button.clicked.connect(
                lambda _checked=False, value=text: self._send_quick(value)
            )
            quick_row.addWidget(button)
            self.quick_buttons.append(button)
        chat_layout.addLayout(quick_row)
        root.addWidget(chat_group, 1)

        self.disconnect_button = QPushButton("断开连接")
        self.disconnect_button.clicked.connect(self._disconnect)
        root.addWidget(self.disconnect_button)

        self.manager.hosting.connect(self._on_hosting)
        self.manager.connected.connect(self._on_connected)
        self.manager.disconnected.connect(self._on_disconnected)
        self.manager.errorOccurred.connect(self._on_error)
        self.manager.messageReceived.connect(self._on_message)

        self._set_idle()
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog { background-color: #262421; }
            QLabel { color: #e8ddc7; font-size: 13px; }
            QLabel#HintLabel { color: #8d877d; font-size: 12px; }
            QLabel#StatusLabel { color: #d8b26a; font-size: 13px; }
            QGroupBox {
                color: #f0e6d2;
                border: 1px solid #3d3933;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 8px;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #c9c1b4;
            }
            QLineEdit, QSpinBox, QPlainTextEdit {
                background-color: #1d1b19;
                color: #e8ddc7;
                border: 1px solid #3d3933;
                border-radius: 4px;
                padding: 5px;
                font-size: 13px;
            }
            QPushButton {
                background-color: #3b3834;
                color: #f0e6d2;
                border: 1px solid #555049;
                border-radius: 5px;
                padding: 6px 12px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #4a463f; }
            QPushButton:pressed { background-color: #2f2c28; }
            QPushButton:disabled { color: #77716a; border-color: #3a3732; }
            QPushButton#QuickButton {
                padding: 3px 6px;
                font-size: 12px;
            }
            """
        )

    def _set_idle(self) -> None:
        self._state = "idle"
        self.port_spin.setEnabled(True)
        self.host_button.setEnabled(True)
        self.address_input.setEnabled(True)
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.setText("断开连接")
        self.copy_button.setEnabled(False)
        self.search_button.setEnabled(True)
        self.room_combo.setEnabled(bool(self._rooms))
        self.minutes_spin.setEnabled(True)
        self.increment_spin.setEnabled(True)
        self.host_password_edit.setEnabled(True)
        self.join_password_edit.setEnabled(True)
        self.chat_input.setEnabled(False)
        self.send_button.setEnabled(False)
        self._set_quick_enabled(False)
        self.status_label.setText("未连接")
        if self.isVisible() and not self.discovery.is_running():
            self._start_discovery()

    def _set_waiting(self) -> None:
        self._state = "hosting"
        self.port_spin.setEnabled(False)
        self.host_button.setEnabled(False)
        self.address_input.setEnabled(False)
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)
        self.disconnect_button.setText("取消房间")
        self.search_button.setEnabled(False)
        self.room_combo.setEnabled(False)
        self.minutes_spin.setEnabled(False)
        self.increment_spin.setEnabled(False)
        self.host_password_edit.setEnabled(False)
        self.join_password_edit.setEnabled(False)
        self._stop_discovery()
        self.chat_input.setEnabled(False)
        self.send_button.setEnabled(False)
        self._set_quick_enabled(False)
        self.status_label.setText("等待对方连接…")

    def _set_connecting(self) -> None:
        self._state = "connecting"
        self.port_spin.setEnabled(False)
        self.host_button.setEnabled(False)
        self.address_input.setEnabled(False)
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)
        self.disconnect_button.setText("取消连接")
        self.copy_button.setEnabled(False)
        self.search_button.setEnabled(False)
        self.room_combo.setEnabled(False)
        self.minutes_spin.setEnabled(False)
        self.increment_spin.setEnabled(False)
        self.host_password_edit.setEnabled(False)
        self.join_password_edit.setEnabled(False)
        self._stop_discovery()
        self.chat_input.setEnabled(False)
        self.send_button.setEnabled(False)
        self._set_quick_enabled(False)
        self.status_label.setText("正在连接…")

    def _set_connected(self, is_host: bool) -> None:
        self._state = "connected"
        self._is_host = is_host
        self.port_spin.setEnabled(False)
        self.host_button.setEnabled(False)
        self.address_input.setEnabled(False)
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)
        self.disconnect_button.setText("断开连接")
        self.search_button.setEnabled(False)
        self.room_combo.setEnabled(False)
        self.minutes_spin.setEnabled(False)
        self.increment_spin.setEnabled(False)
        self.host_password_edit.setEnabled(False)
        self.join_password_edit.setEnabled(False)
        self._stop_discovery()
        self.chat_input.setEnabled(True)
        self.send_button.setEnabled(True)
        self._set_quick_enabled(True)
        side = "白" if is_host else "黑"
        self.status_label.setText(f"已连接（你执{side}）")
        self.copy_button.setEnabled(bool(self._http_address))
        self.chat_input.setFocus()

    def current_time_control(self) -> tuple[int, int]:
        return (
            self.minutes_spin.value() * 60,
            self.increment_spin.value(),
        )

    def apply_time_control(self, base_seconds: int, increment: int) -> None:
        self.minutes_spin.blockSignals(True)
        self.increment_spin.blockSignals(True)
        self.minutes_spin.setValue(max(1, int(base_seconds) // 60))
        self.increment_spin.setValue(max(0, min(60, int(increment))))
        self.minutes_spin.blockSignals(False)
        self.increment_spin.blockSignals(False)

    def _start_host(self) -> None:
        if self._state != "idle":
            return
        self.settings.setValue(
            "online_clock_minutes", self.minutes_spin.value()
        )
        self.settings.setValue(
            "online_clock_increment", self.increment_spin.value()
        )
        self.settings.sync()
        self._stop_discovery()
        password = self.host_password_edit.text()
        if self.manager.host(self.port_spin.value(), password):
            self._set_waiting()

    def _start_connect(self) -> None:
        if self._state != "idle":
            return
        address = self.address_input.text().strip()
        if not address:
            self._append_system("请输入联机地址")
            return
        self._stop_discovery()
        password = self.join_password_edit.text()
        if self.manager.connect(address, password):
            self._set_connecting()

    def _disconnect(self) -> None:
        self.manager.disconnect()

    def _on_hosting(self, http: str, tcp: str, ws: str) -> None:
        self._http_address = http
        self._tcp_address = tcp
        self._ws_address = ws
        self.address_display.setText(http)
        self.copy_button.setEnabled(True)
        self.tcp_label.setText(
            f"TCP 地址：{tcp}\nWebSocket 地址：{ws}\n"
            "对方输入其中任意一个地址即可。"
        )
        self._set_waiting()
        self._append_system(f"房间已创建：{http}")

    def _on_connected(self, is_host: bool) -> None:
        if not self.manager.is_connected():
            return
        self._set_connected(is_host)
        side = "白" if is_host else "黑"
        self._append_system(f"WebSocket 已连接，你执{side}")
        self._refresh_idle_controls()

    def _on_disconnected(self, reason: str) -> None:
        self._set_idle()
        self._append_system(reason)

    def _on_error(self, message: str) -> None:
        if self._state == "connecting":
            self._set_idle()
        self.status_label.setText(message)
        self._append_system(f"错误：{message}")

    def _on_message(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "chat":
            text = str(message.get("text", ""))[:2000]
            if text:
                self._append_chat("对方：", text)
        elif kind == "new_game":
            if not self._is_host:
                self._append_system("对方开始了新对局")

    def _set_quick_enabled(self, enabled: bool) -> None:
        for button in self.quick_buttons:
            button.setEnabled(enabled)

    def _send_quick(self, text: str) -> None:
        if self._state != "connected":
            return
        self.chat_input.setText(text)
        self._send_chat()

    def _send_chat(self) -> None:
        if self._state != "connected":
            return
        text = self.chat_input.text().strip()
        if not text:
            return
        text = text[:1000]
        if not self.manager.send({"type": "chat", "text": text}):
            self._append_system("聊天发送失败")
            return
        self._append_chat("我：", text)
        self.chat_input.clear()

    def _copy_address(self) -> None:
        if self._http_address:
            QApplication.clipboard().setText(self._http_address)
            self._append_system("联机地址已复制到剪贴板")

    def _toggle_discovery(self) -> None:
        if self.discovery.is_running():
            self._stop_discovery()
        else:
            self._start_discovery()

    def _start_discovery(self) -> None:
        if self._state != "idle":
            return
        was_running = self.discovery.is_running()
        if not was_running:
            self._rooms.clear()
            self.room_combo.blockSignals(True)
            self.room_combo.clear()
            self.room_combo.addItem("搜索中…", None)
            self.room_combo.setEnabled(False)
            self.room_combo.blockSignals(False)
        if not self.discovery.start():
            self.search_button.setText("搜索局域网房间")
            return
        self._room_timer.start()
        self.search_button.setText("停止搜索")
        self.search_button.setEnabled(True)

    def _stop_discovery(self) -> None:
        self.discovery.stop()
        self._room_timer.stop()
        self.search_button.setText("搜索局域网房间")
        if (
            self.room_combo.count() == 1
            and self.room_combo.itemData(0) is None
        ):
            self.room_combo.blockSignals(True)
            self.room_combo.setItemText(0, "未发现房间")
            self.room_combo.blockSignals(False)

    def _on_discovery_error(self, message: str) -> None:
        self._append_system(f"搜索失败：{message}")
        if self._state == "idle":
            self.status_label.setText(message)

    def _on_room_found(self, room: dict) -> None:
        key = (str(room.get("ip")), int(room.get("port", 0)))
        existing = key in self._rooms
        if existing:
            self._rooms[key].update(room)
            self._rooms[key]["last_seen"] = time.monotonic()
            return

        room["last_seen"] = time.monotonic()
        self._rooms[key] = room
        placeholder = (
            self.room_combo.count() == 1
            and self.room_combo.itemData(0) is None
        )
        if placeholder:
            self.room_combo.blockSignals(True)
            self.room_combo.clear()
            self.room_combo.blockSignals(False)
        self.room_combo.blockSignals(True)
        self.room_combo.addItem(
            f"{room['name']}  ({room['ip']}:{room['port']})",
            room,
        )
        self.room_combo.setEnabled(True)
        self.room_combo.blockSignals(False)
        if placeholder and not self.address_input.text().strip():
            self.room_combo.setCurrentIndex(0)
            self._on_room_selected(0)

    def _on_room_selected(self, index: int) -> None:
        room = self.room_combo.itemData(index)
        if not isinstance(room, dict):
            return
        self.address_input.setText(
            f"http://{room['ip']}:{room['port']}"
        )
        self.address_input.setFocus()

    def _prune_rooms(self) -> None:
        now = time.monotonic()
        stale = [
            key
            for key, room in self._rooms.items()
            if now - room.get("last_seen", now) > 9
        ]
        if not stale:
            return
        for key in stale:
            self._rooms.pop(key, None)
        current = self.room_combo.currentData()
        current_key = (
            (str(current.get("ip")), int(current.get("port", 0)))
            if isinstance(current, dict)
            else None
        )
        self.room_combo.blockSignals(True)
        self.room_combo.clear()
        for room in self._rooms.values():
            self.room_combo.addItem(
                f"{room['name']}  ({room['ip']}:{room['port']})",
                room,
            )
        if self.room_combo.count() == 0:
            self.room_combo.addItem("未发现房间", None)
            self.room_combo.setEnabled(False)
        else:
            self.room_combo.setEnabled(self._state == "idle")
            if current_key is not None:
                for index in range(self.room_combo.count()):
                    data = self.room_combo.itemData(index)
                    if isinstance(data, dict) and (
                        str(data.get("ip")),
                        int(data.get("port", 0)),
                    ) == current_key:
                        self.room_combo.setCurrentIndex(index)
                        break
        self.room_combo.blockSignals(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._state == "idle" and not self.discovery.is_running():
            self._start_discovery()

    def _refresh_idle_controls(self) -> None:
        if self._state == "connected":
            self.chat_input.setFocus()

    def focus_connect(self) -> None:
        if self._state == "idle":
            self.address_input.setFocus()
            self.address_input.selectAll()

    def add_system(self, text: str) -> None:
        self._append_system(text)

    def _append_system(self, text: str) -> None:
        self._append_chat("系统：", text)

    def _append_chat(self, prefix: str, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M")
        self.chat_log.appendPlainText(f"[{timestamp}] {prefix}{text}")
        scrollbar = self.chat_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def closeEvent(self, event) -> None:
        self._stop_discovery()
        event.ignore()
        self.hide()
