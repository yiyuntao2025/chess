from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chess_engine import ChessGame


class FenDialog(QDialog):
    def __init__(
        self,
        fen: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.fen = fen
        self.setWindowTitle("FEN 局面")
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        hint = QLabel(
            "粘贴或编辑标准 6 字段 FEN 后点击“加载”。加载会从该局面开始新对局。"
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.fen_edit = QLineEdit(fen)
        self.fen_edit.setPlaceholderText(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        )
        self.fen_edit.selectAll()
        root.addWidget(self.fen_edit)

        button_row = QHBoxLayout()
        self.copy_button = QPushButton("复制当前 FEN")
        self.paste_button = QPushButton("从剪贴板粘贴")
        self.load_button = QPushButton("加载")
        self.cancel_button = QPushButton("取消")
        self.copy_button.clicked.connect(self._copy_current)
        self.paste_button.clicked.connect(self._paste_clipboard)
        self.load_button.clicked.connect(self._load)
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.copy_button)
        button_row.addWidget(self.paste_button)
        button_row.addStretch()
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.load_button)
        root.addLayout(button_row)

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
                padding: 7px;
                font-family: Consolas, "Courier New", monospace;
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
            """
        )

    def _copy_current(self) -> None:
        QApplication.clipboard().setText(self.fen_edit.text().strip())

    def _paste_clipboard(self) -> None:
        text = QApplication.clipboard().text().strip()
        if text:
            self.fen_edit.setText(" ".join(text.split()))

    def _load(self) -> None:
        text = " ".join(self.fen_edit.text().split())
        if not text:
            QMessageBox.warning(self, "FEN 无效", "请输入 FEN。")
            return
        try:
            ChessGame().load_fen(text)
        except ValueError as exc:
            QMessageBox.warning(self, "FEN 无效", str(exc))
            return
        self.fen = text
        self.accept()
