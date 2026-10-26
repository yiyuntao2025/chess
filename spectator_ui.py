from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from board_widgets import ChessBoard
from lan import LanManager
from pgn_import import PGNImportError, parse_pgn


class SpectatorDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.settings = QSettings("ChessPyQt", "Chess")
        self.lan = LanManager(self)
        self.setWindowTitle("观战模式")
        self.setMinimumSize(1000, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        form = QHBoxLayout()
        form.setSpacing(6)
        self.address_edit = QLineEdit(
            str(self.settings.value("spectator_address", ""))
        )
        self.address_edit.setPlaceholderText(
            "ws://192.168.1.10:8766（房主联机端口 + 1）"
        )
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("房间密码（如有）")
        self.connect_button = QPushButton("连接观战")
        self.disconnect_button = QPushButton("断开")
        self.disconnect_button.setEnabled(False)
        self.connect_button.clicked.connect(self._connect)
        self.disconnect_button.clicked.connect(self.lan.disconnect)
        form.addWidget(self.address_edit, 1)
        form.addWidget(self.password_edit, 1)
        form.addWidget(self.connect_button)
        form.addWidget(self.disconnect_button)
        root.addLayout(form)

        self.status_label = QLabel(
            "输入房主提供的观战地址。观战棋盘为只读，不会影响对局。"
        )
        self.status_label.setObjectName("HintLabel")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        body = QHBoxLayout()
        body.setSpacing(10)
        self.board = ChessBoard()
        self.board.input_locked = True
        body.addWidget(self.board, 3)
        self.notation = QTextBrowser()
        self.notation.setReadOnly(True)
        self.notation.setObjectName("Notation")
        body.addWidget(self.notation, 2)
        root.addLayout(body, 1)

        self.lan.connected.connect(self._on_connected)
        self.lan.disconnected.connect(self._on_disconnected)
        self.lan.messageReceived.connect(self._on_message)
        self.lan.errorOccurred.connect(self._on_error)
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog { background-color: #262421; }
            QLabel { color: #e8ddc7; font-size: 13px; }
            QLabel#HintLabel { color: #8d877d; font-size: 12px; }
            QLineEdit {
                background-color: #1d1b19;
                color: #e8ddc7;
                border: 1px solid #3d3933;
                border-radius: 4px;
                padding: 6px;
            }
            QPushButton {
                background-color: #3b3834;
                color: #f0e6d2;
                border: 1px solid #555049;
                border-radius: 5px;
                padding: 6px 12px;
            }
            QPushButton:hover { background-color: #4a463f; }
            QPushButton:disabled { color: #77716a; border-color: #3a3732; }
            QTextBrowser#Notation {
                background-color: #1d1b19;
                color: #e8ddc7;
                border: 1px solid #3d3933;
                border-radius: 6px;
                padding: 8px;
                font-family: Consolas, "Microsoft YaHei", monospace;
                font-size: 12px;
            }
            """
        )

    def _connect(self) -> None:
        address = self.address_edit.text().strip()
        if not address:
            self.status_label.setText("请输入观战地址")
            return
        self.settings.setValue("spectator_address", address)
        self.settings.sync()
        if self.lan.connect(address, self.password_edit.text()):
            self.status_label.setText("正在连接观战…")

    def _on_connected(self, is_host: bool) -> None:
        del is_host
        self.status_label.setText("观战已连接，等待房主同步局面…")
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)
        self.address_edit.setEnabled(False)
        self.password_edit.setEnabled(False)

    def _on_disconnected(self, reason: str) -> None:
        self.status_label.setText(f"观战已断开：{reason}")
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.address_edit.setEnabled(True)
        self.password_edit.setEnabled(True)

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"观战错误：{message}")

    def _on_message(self, message: dict) -> None:
        if message.get("type") != "spectate_state":
            return
        pgn = message.get("pgn")
        if not isinstance(pgn, str) or not pgn.strip():
            return
        try:
            tree = parse_pgn(pgn)
        except PGNImportError:
            return
        node = tree.latest_node()
        game = tree.build_game(node)
        self.board.flipped = bool(message.get("flipped"))
        self.board.set_game(game, reviewing=False)
        self.board.input_locked = True
        self.board.game_over = False
        self.notation.setPlainText(pgn)
        result = str(message.get("result") or tree.result or "")
        result_text = f" · 结果 {result}" if result and result != "*" else ""
        self.status_label.setText(
            f"观战中 · 第 {node.ply} 手 · "
            f"{message.get('white', '白方')} vs "
            f"{message.get('black', '黑方')}{result_text}"
        )

    def closeEvent(self, event) -> None:
        self.lan.shutdown()
        super().closeEvent(event)
