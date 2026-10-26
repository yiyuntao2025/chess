from __future__ import annotations

import html as html_module
import math
import random
import threading
from datetime import date
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app_constants import (
    AI_LEVELS,
    ONLINE_CLOCK_SECONDS,
    ONLINE_MESSAGE_TYPES,
    THEMES,
)
from board_widgets import (
    CapturedPiecesWidget,
    ChessBoard,
    EvalBar,
    EvalGraphWidget,
)
from chess_clock import ChessClock
from chess_engine import ChessGame, Move
from coach_ui import CoachDialog
from fen_dialog import FenDialog
from game_tree import GameNode, GameTree
from lan import LanManager
from lan_ui import NetworkDialog
from pgn_export import build_pgn_tree
from pgn_import import PGNImportError, parse_pgn
from session_store import clear_state, load_state, save_state
from sound_player import SoundPlayer
from stockfish_ai import (
    AnalysisLine,
    AnalysisResult,
    analyse_position,
    ask_stockfish_for_move,
    find_stockfish,
)


class MainWindow(QMainWindow):
    aiResponse = pyqtSignal(int, object, str)
    analysisReady = pyqtSignal(int, object, bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("国际象棋")
        self.setMinimumSize(960, 760)
        self.resize(1180, 940)

        self.ai_enabled = False
        self.ai_thinking = False
        self._ai_paused = False
        self.ai_used_colors: set[str] = set()
        self._ai_request_id = 0
        self._thinking_dots = 0
        self.match_mode = "two"
        self.human_color = "w"
        self.ai_color = "b"
        self.difficulty = "普通"
        self.game_tree = GameTree()
        self.online = False
        self.is_online_host = False
        self.net_game_id = 0
        self.local_color = "w"
        self.remote_color = "b"
        self._online_paused = False
        self._network_dialog: Optional[NetworkDialog] = None
        self._coach_dialog: Optional[CoachDialog] = None
        self.engine_path = find_stockfish()
        self.sound_player = SoundPlayer()
        self.lan = LanManager(self)
        self.clock = ChessClock(ONLINE_CLOCK_SECONDS, 0, self)
        self.clock.updated.connect(self._update_clock_labels)
        self.clock.flag.connect(self._on_clock_flag)
        self._draw_offer_pending = False
        self._undo_request_pending = False
        self._undo_request_target: Optional[int] = None
        self._unread_chat = 0
        self.online_time_control: Optional[tuple[int, int]] = None
        self._clock_pending_move = False
        self._session_restoring = False
        self._session_save_timer = QTimer(self)
        self._session_save_timer.setSingleShot(True)
        self._session_save_timer.setInterval(600)
        self._session_save_timer.timeout.connect(self._save_session)
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setInterval(450)
        self._thinking_timer.timeout.connect(self._tick_thinking)

        self._settings = QSettings("ChessPyQt", "Chess")
        self._loading_settings = True
        self._analysis_token = 0
        self._auto_analysis_token = 0
        self._analysis_cancel = threading.Event()
        self._hint_busy = False
        self._eval_scores: dict[int, int] = {}
        self._eval_display: dict[int, tuple[Optional[int], Optional[int]]] = {}
        self._move_annotations: dict[int, str] = {}
        self._analysis_timer = QTimer(self)
        self._analysis_timer.setSingleShot(True)
        self._analysis_timer.setInterval(280)
        self._analysis_timer.timeout.connect(self._auto_analysis_timeout)

        central = QWidget()
        central.setObjectName("Central")
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        top_bar = QHBoxLayout()
        self.turn_label = QLabel()
        self.turn_label.setObjectName("TurnLabel")
        top_bar.addWidget(self.turn_label)
        top_bar.addStretch()

        self.undo_button = QPushButton("悔棋")
        self.reset_button = QPushButton("重新开始")
        flip_button = QPushButton("翻转棋盘")
        self.fen_button = QPushButton("FEN")
        export_button = QPushButton("导出 PGN")
        self.online_button = QPushButton("联机")
        join_button = QPushButton("连接")
        self.undo_button.clicked.connect(self._undo)
        self.reset_button.clicked.connect(self._new_game)
        flip_button.clicked.connect(self._flip_board)
        self.fen_button.clicked.connect(self._show_fen_dialog)
        export_button.clicked.connect(self._export_pgn)
        self.online_button.clicked.connect(self._show_network_dialog)
        join_button.clicked.connect(self._show_network_dialog_connect)
        top_bar.addWidget(self.online_button)
        top_bar.addWidget(join_button)
        top_bar.addWidget(flip_button)
        top_bar.addWidget(self.fen_button)
        top_bar.addWidget(export_button)
        top_bar.addWidget(self.undo_button)
        top_bar.addWidget(self.reset_button)
        layout.addLayout(top_bar)

        content = QHBoxLayout()
        content.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        clock_row = QHBoxLayout()
        clock_row.setSpacing(8)
        self.clock_caption = QLabel("联机棋钟 · 10 分钟包干")
        self.clock_caption.setObjectName("HintLabel")
        self.white_clock_label = QLabel()
        self.black_clock_label = QLabel()
        for label in (self.white_clock_label, self.black_clock_label):
            label.setObjectName("ClockLabel")
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock_caption.hide()
        self.white_clock_label.hide()
        self.black_clock_label.hide()
        clock_row.addWidget(self.clock_caption)
        clock_row.addWidget(self.white_clock_label)
        clock_row.addWidget(self.black_clock_label)
        clock_row.addStretch()
        left_col.addLayout(clock_row)

        board_row = QHBoxLayout()
        board_row.setSpacing(8)
        self.eval_bar = EvalBar()
        board_row.addWidget(self.eval_bar)
        self.board = ChessBoard()
        board_row.addWidget(self.board, 1)
        left_col.addLayout(board_row, 1)
        self.captured_widget = CapturedPiecesWidget()
        left_col.addWidget(self.captured_widget)
        content.addLayout(left_col, 1)

        sidebar = QWidget()
        sidebar.setFixedWidth(310)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)

        notation_title = QLabel("棋谱")
        notation_title.setObjectName("SideTitle")
        side_layout.addWidget(notation_title)

        self.notation = QTextBrowser()
        self.notation.setObjectName("Notation")
        self.notation.setReadOnly(True)
        self.notation.setOpenLinks(False)
        self.notation.setOpenExternalLinks(False)
        self.notation.anchorClicked.connect(self._on_notation_anchor)
        side_layout.addWidget(self.notation, 1)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        self.first_button = QPushButton("开局")
        self.prev_button = QPushButton("上一步")
        self.next_button = QPushButton("下一步")
        self.latest_button = QPushButton("最新")
        for button in (
            self.first_button,
            self.prev_button,
            self.next_button,
            self.latest_button,
        ):
            button.setObjectName("SmallButton")
            nav_row.addWidget(button)
        self.first_button.clicked.connect(self._go_first)
        self.prev_button.clicked.connect(self._go_previous)
        self.next_button.clicked.connect(self._go_next)
        self.latest_button.clicked.connect(self._go_latest)
        side_layout.addLayout(nav_row)

        game_action_row = QHBoxLayout()
        game_action_row.setSpacing(6)
        self.resign_button = QPushButton("认输")
        self.draw_button = QPushButton("提和")
        self.claim_draw_button = QPushButton("判和")
        self.pause_button = QPushButton("暂停")
        self.rematch_button = QPushButton("再战")
        for button in (
            self.resign_button,
            self.draw_button,
            self.claim_draw_button,
            self.pause_button,
            self.rematch_button,
        ):
            button.setObjectName("SmallButton")
            button.setEnabled(False)
            game_action_row.addWidget(button)
        self.resign_button.setToolTip("联机对局中认输")
        self.draw_button.setToolTip("向对方提议和棋")
        self.claim_draw_button.setToolTip(
            "依据 50 回合或三次重复规则请求判和"
        )
        self.pause_button.setToolTip("请求暂停或继续联机对局")
        self.rematch_button.setToolTip("对局结束后请求再来一局")
        self.resign_button.clicked.connect(self._resign_online)
        self.draw_button.clicked.connect(self._offer_draw)
        self.claim_draw_button.clicked.connect(self._claim_draw)
        self.pause_button.clicked.connect(self._toggle_online_pause)
        self.rematch_button.clicked.connect(self._request_rematch)
        side_layout.addLayout(game_action_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.copy_button = QPushButton("复制棋谱")
        self.import_button = QPushButton("导入 PGN")
        self.hint_button = QPushButton("提示")
        self.coach_button = QPushButton("教练")
        for button in (
            self.copy_button,
            self.import_button,
            self.hint_button,
            self.coach_button,
        ):
            button.setObjectName("SmallButton")
            action_row.addWidget(button)
        self.copy_button.clicked.connect(self._copy_pgn)
        self.import_button.clicked.connect(self._import_pgn)
        self.hint_button.clicked.connect(self._request_hint)
        self.coach_button.clicked.connect(self._show_coach_dialog)
        side_layout.addLayout(action_row)

        self.hint_label = QLabel("提示：--")
        self.hint_label.setObjectName("HintLabel")
        self.hint_label.setWordWrap(True)
        side_layout.addWidget(self.hint_label)

        self.eval_label = QLabel("评估：--")
        self.eval_label.setObjectName("AiStatus")
        self.eval_label.setWordWrap(True)
        side_layout.addWidget(self.eval_label)
        self.eval_graph = EvalGraphWidget()
        side_layout.addWidget(self.eval_graph)
        self.accuracy_label = QLabel("准确率：--")
        self.accuracy_label.setObjectName("HintLabel")
        self.accuracy_label.setWordWrap(True)
        side_layout.addWidget(self.accuracy_label)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("双人对战", "two")
        self.mode_combo.addItem("人机对战", "human")
        self.mode_combo.addItem("引擎互弈", "engine")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        side_layout.addWidget(self.mode_combo)

        side_controls = QHBoxLayout()
        side_controls.setSpacing(6)
        self.side_combo = QComboBox()
        self.side_combo.addItem("你执白", "w")
        self.side_combo.addItem("你执黑", "b")
        self.side_combo.currentIndexChanged.connect(
            self._on_human_side_changed
        )
        self.difficulty_combo = QComboBox()
        for level in AI_LEVELS:
            self.difficulty_combo.addItem(f"难度：{level}", level)
        self.difficulty_combo.currentIndexChanged.connect(
            self._on_difficulty_changed
        )
        side_controls.addWidget(self.side_combo, 1)
        side_controls.addWidget(self.difficulty_combo, 1)
        side_layout.addLayout(side_controls)

        self.ai_status = QLabel("Stockfish：未启用")
        self.ai_status.setObjectName("AiStatus")
        self.ai_status.setWordWrap(True)
        side_layout.addWidget(self.ai_status)

        ai_button_row = QHBoxLayout()
        ai_button_row.setSpacing(6)
        self.cancel_ai_button = QPushButton("取消思考")
        self.retry_ai_button = QPushButton("重试")
        self.cancel_ai_button.setObjectName("SmallButton")
        self.retry_ai_button.setObjectName("SmallButton")
        self.cancel_ai_button.clicked.connect(self._cancel_ai_request)
        self.retry_ai_button.clicked.connect(self._retry_ai)
        ai_button_row.addWidget(self.cancel_ai_button)
        ai_button_row.addWidget(self.retry_ai_button)
        side_layout.addLayout(ai_button_row)

        appearance_row = QHBoxLayout()
        appearance_row.setSpacing(6)
        self.theme_combo = QComboBox()
        for theme in THEMES:
            self.theme_combo.addItem(f"主题：{theme}", theme)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.coords_checkbox = QCheckBox("坐标")
        self.coords_checkbox.setChecked(True)
        self.coords_checkbox.toggled.connect(self.board.set_coordinates)
        appearance_row.addWidget(self.theme_combo, 1)
        appearance_row.addWidget(self.coords_checkbox)
        side_layout.addLayout(appearance_row)

        self.sound_checkbox = QCheckBox("音效")
        self.sound_checkbox.setChecked(self.sound_player.enabled)
        self.sound_checkbox.toggled.connect(self.sound_player.set_enabled)
        side_layout.addWidget(self.sound_checkbox)

        clock_controls = QHBoxLayout()
        clock_controls.setSpacing(6)
        self.clock_checkbox = QCheckBox("棋钟")
        self.clock_checkbox.setToolTip("开启后本局使用计时")
        self.clock_minutes_spin = QSpinBox()
        self.clock_minutes_spin.setRange(1, 180)
        self.clock_minutes_spin.setValue(10)
        self.clock_minutes_spin.setSuffix(" 分")
        self.clock_increment_spin = QSpinBox()
        self.clock_increment_spin.setRange(0, 60)
        self.clock_increment_spin.setValue(0)
        self.clock_increment_spin.setSuffix(" 秒/步")
        self.clock_checkbox.toggled.connect(self._on_clock_toggled)
        self.clock_minutes_spin.valueChanged.connect(
            self._on_clock_settings_changed
        )
        self.clock_increment_spin.valueChanged.connect(
            self._on_clock_settings_changed
        )
        clock_controls.addWidget(self.clock_checkbox)
        clock_controls.addWidget(self.clock_minutes_spin, 1)
        clock_controls.addWidget(self.clock_increment_spin, 1)
        side_layout.addLayout(clock_controls)

        if self.engine_path is not None:
            engine_hint = QLabel(f"引擎：{self.engine_path.name}")
            engine_hint.setToolTip(str(self.engine_path))
        else:
            engine_hint = QLabel(
                "未找到 Stockfish，请放入 stockfish/ 目录或设置 STOCKFISH_PATH"
            )
        engine_hint.setObjectName("HintLabel")
        engine_hint.setWordWrap(True)
        side_layout.addWidget(engine_hint)

        content.addWidget(sidebar)
        layout.addLayout(content, 1)

        self.board.stateChanged.connect(self._on_state_changed)
        self.board.newMovePlayed.connect(self._on_new_move)
        self.board.moveCompleted.connect(self._maybe_request_ai)
        self.board.gameEnded.connect(self._on_game_ended)
        self.board.moveSound.connect(self.sound_player.play)
        self.board.userMovePlayed.connect(self._on_local_move)
        self.aiResponse.connect(self._on_ai_response)
        self.analysisReady.connect(self._on_analysis_ready)
        self.lan.connected.connect(self._on_lan_connected)
        self.lan.disconnected.connect(self._on_lan_disconnected)
        self.lan.messageReceived.connect(self._on_lan_message)
        self.lan.errorOccurred.connect(self._on_lan_error)
        self.board.setToolTip("可拖拽或点击走子")

        self.statusBar().showMessage("点击或拖拽己方棋子走棋，点击棋谱可回放")
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self._go_next)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._new_game)

        self.setStyleSheet(
            """
            QMainWindow { background-color: #262421; }
            QWidget#Central { background-color: #262421; }
            QLabel#TurnLabel {
                color: #f0e6d2;
                font-size: 18px;
                font-weight: 600;
            }
            QLabel#SideTitle {
                color: #f0e6d2;
                font-size: 16px;
                font-weight: 600;
            }
            QLabel#AiStatus { color: #c9c1b4; font-size: 13px; }
            QLabel#HintLabel { color: #b9ab92; font-size: 12px; }
            QLabel#ClockLabel {
                color: #c9c1b4;
                background-color: #1d1b19;
                border: 1px solid #3d3933;
                border-radius: 4px;
                padding: 3px 10px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 15px;
            }
            QPushButton {
                background-color: #3b3834;
                color: #f0e6d2;
                border: 1px solid #555049;
                border-radius: 6px;
                padding: 7px 16px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #4a463f; }
            QPushButton:pressed { background-color: #2f2c28; }
            QPushButton:disabled { color: #77716a; border-color: #3a3732; }
            QPushButton#SmallButton { padding: 5px 8px; font-size: 12px; }
            QCheckBox { color: #f0e6d2; font-size: 13px; spacing: 6px; }
            QComboBox {
                background-color: #3b3834;
                color: #f0e6d2;
                border: 1px solid #555049;
                border-radius: 5px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QComboBox::drop-down { border: 0px; }
            QComboBox:disabled {
                color: #77716a;
                background-color: #2f2c28;
                border-color: #3a3732;
            }
            QComboBox QAbstractItemView {
                background-color: #2b2926;
                color: #f0e6d2;
                selection-background-color: #4a463f;
            }
            QTextBrowser#Notation {
                background-color: #1d1b19;
                color: #e8ddc7;
                border: 1px solid #3d3933;
                border-radius: 6px;
                padding: 6px;
                font-family: Consolas, "Microsoft YaHei", "Courier New", monospace;
                font-size: 12px;
            }
            QStatusBar { color: #c9c1b4; }
            """
        )

        self._load_settings()
        self._loading_settings = False
        if not self._restore_session():
            self._reset_local_clock()
        self._apply_mode_controls()
        self._refresh_locks()
        self._refresh_status()
        self._refresh_notation()
        self._refresh_nav_buttons()
        self._refresh_captured()
        self._update_ai_status()
        self._analysis_token += 1
        self._show_cached_eval(0)
        if self.engine_path is not None:
            self._schedule_auto_analysis()

    def _flip_board(self) -> None:
        self.board.flip()
        self.eval_bar.set_flipped(self.board.flipped)

    def _show_network_dialog(self, focus_connect: bool = False) -> None:
        if self._network_dialog is None:
            self._network_dialog = NetworkDialog(self.lan, self)
        self._network_dialog.show()
        self._network_dialog.raise_()
        self._network_dialog.activateWindow()
        self._unread_chat = 0
        self._update_chat_button()
        if focus_connect:
            self._network_dialog.focus_connect()

    def _show_network_dialog_connect(self) -> None:
        self._show_network_dialog(focus_connect=True)

    def _show_coach_dialog(self) -> None:
        if self._coach_dialog is None:
            self._coach_dialog = CoachDialog(self._settings, self)
        self._coach_dialog.show()
        self._coach_dialog.raise_()
        self._coach_dialog.activateWindow()

    def coach_context(self) -> dict:
        game = self.board.game
        sans, result = self._full_san_result()
        last_ply = len(game.san_history)
        annotations = dict(self._move_annotations)
        evals = dict(self._eval_scores)
        return {
            "sans": sans,
            "result": result,
            "pgn": self._pgn_text(),
            "annotations": annotations,
            "evals": evals,
            "history_sans": list(game.san_history),
            "last_san": game.san_history[-1] if last_ply else "",
            "last_annotation": annotations.get(last_ply, ""),
            "eval_before": evals.get(last_ply - 1) if last_ply > 0 else None,
            "eval_after": evals.get(last_ply),
            "current_fen": game.to_fen(),
        }

    def _update_chat_button(self) -> None:
        if self._unread_chat > 0:
            self.online_button.setText("联机*")
            self.online_button.setToolTip(
                f"{self._unread_chat} 条未读聊天消息"
            )
        else:
            self.online_button.setText("联机")
            self.online_button.setToolTip("")

    def _network_system(self, text: str) -> None:
        if self._network_dialog is not None:
            self._network_dialog.add_system(text)

    def _lan_dialog_parent(self) -> QWidget:
        if (
            self._network_dialog is not None
            and self._network_dialog.isVisible()
        ):
            return self._network_dialog
        return self

    def _online_clock_config(self) -> tuple[int, int]:
        if self.online_time_control is not None:
            return self.online_time_control
        return ONLINE_CLOCK_SECONDS, 0

    def _local_clock_config(self) -> tuple[int, int]:
        return (
            self.clock_minutes_spin.value() * 60,
            self.clock_increment_spin.value(),
        )

    def _active_clock_config(self) -> tuple[int, int]:
        if self.online:
            return self._online_clock_config()
        return self._local_clock_config()

    def _clock_is_enabled(self) -> bool:
        return self.online or self.clock_checkbox.isChecked()

    def _update_clock_caption(self) -> None:
        base, increment = self._active_clock_config()
        minutes = max(1, base // 60)
        prefix = "联机棋钟" if self.online else "棋钟"
        if increment:
            self.clock_caption.setText(
                f"{prefix} · {minutes} 分钟 + {increment} 秒/步"
            )
        else:
            self.clock_caption.setText(f"{prefix} · {minutes} 分钟包干")

    def _update_clock_labels(self) -> None:
        if not self._clock_is_enabled():
            self.clock_caption.hide()
            self.white_clock_label.hide()
            self.black_clock_label.hide()
            return

        self.clock_caption.show()
        self.white_clock_label.show()
        self.black_clock_label.show()
        active = self.clock.active
        for color, label in (
            ("w", self.white_clock_label),
            ("b", self.black_clock_label),
        ):
            prefix = "白" if color == "w" else "黑"
            color_code = "#f0c060" if active == color else "#9c9488"
            label.setText(
                f'<span style="color:{color_code};">'
                f"{prefix} {self.clock.display(color)}</span>"
            )

    def _refresh_clock_controls(self) -> None:
        online = self.online
        enabled = self.clock_checkbox.isChecked()
        self.clock_checkbox.setEnabled(not online)
        editable = not online and enabled and not self.board.game.history
        self.clock_minutes_spin.setEnabled(editable)
        self.clock_increment_spin.setEnabled(editable)

    def _on_clock_toggled(self, checked: bool) -> None:
        if self._loading_settings or self.online:
            return
        self._reset_local_clock()
        self._refresh_clock_controls()

    def _on_clock_settings_changed(self, value: int) -> None:
        if self._loading_settings or self.online:
            return
        if not self.board.game.history:
            self._reset_local_clock()
        self._refresh_clock_controls()

    def _reset_local_clock(self) -> None:
        if self.online:
            return
        self._clock_pending_move = False
        if not self.clock_checkbox.isChecked():
            self.clock.stop()
            self._update_clock_labels()
            self._refresh_clock_controls()
            return

        base, increment = self._local_clock_config()
        self.clock.reset(base, increment)
        game = self.board.game
        if (
            game.history
            and not self.board.game_over
            and not self.board.is_reviewing()
        ):
            self.clock.start(game.turn)
        self._update_clock_caption()
        self._update_clock_labels()
        self._refresh_clock_controls()

    def _refresh_online_actions(self) -> None:
        in_game = self.online and not self.board.game_over
        self.resign_button.setEnabled(in_game)
        self.draw_button.setEnabled(
            in_game and not self._draw_offer_pending
        )
        claimable = (
            not self.board.game_over
            and not self.board.is_reviewing()
            and self.board.game.is_claimable_draw()
        )
        if self.online:
            claimable = (
                claimable
                and self.board.game.turn == self.local_color
            )
        self.claim_draw_button.setEnabled(claimable)
        self.pause_button.setEnabled(in_game)
        self.pause_button.setText("继续" if self._online_paused else "暂停")
        self.rematch_button.setEnabled(self.online and self.board.game_over)

    def _on_clock_flag(self, color: str) -> None:
        if self.board.game_over:
            return
        if not self.online and not self.clock_checkbox.isChecked():
            return
        self.clock.stop()
        self._draw_offer_pending = False
        winner = "黑方" if color == "w" else "白方"
        side = "白方" if color == "w" else "黑方"
        result = "0-1" if color == "w" else "1-0"
        message = f"{side}超时，{winner}获胜"
        if self.online:
            self.lan.send({"type": "timeout", "color": color})
            self._network_system(message)
        self.board.finish_game(message, result)

    def _resign_online(self) -> None:
        if not self.online or self.board.game_over:
            return
        answer = QMessageBox.question(
            self,
            "认输",
            "确认认输吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        color = self.local_color
        result = "0-1" if color == "w" else "1-0"
        self._draw_offer_pending = False
        self.lan.send({"type": "resign", "color": color})
        self._network_system("你已认输")
        self.board.finish_game("你已认输", result)

    def _offer_draw(self) -> None:
        if (
            not self.online
            or self.board.game_over
            or self._draw_offer_pending
        ):
            return
        if self.lan.send({"type": "draw_offer"}):
            self._draw_offer_pending = True
            self._network_system("已向对方提出和棋")
            self.statusBar().showMessage("已向对方提出和棋，等待回应", 5000)
            self._refresh_online_actions()

    def _toggle_online_pause(self) -> None:
        if not self.online or self.board.game_over:
            return
        kind = "resume_request" if self._online_paused else "pause_request"
        if self.lan.send({"type": kind}):
            self.statusBar().showMessage(
                "已请求继续对局，等待对方回应"
                if self._online_paused
                else "已请求暂停对局，等待对方回应",
                5000,
            )

    def _set_online_paused(self, paused: bool) -> None:
        if not self.online:
            return
        self._online_paused = paused
        self.board.input_locked = paused
        self.board.locked_color = None if paused else self.remote_color
        self._clock_pending_move = False
        if paused:
            self.clock.stop()
            self._network_system("对局已暂停")
        elif not self.board.game_over:
            self.clock.start(self.board.game.turn)
            self._network_system("对局已继续")
        self.pause_button.setText("继续" if paused else "暂停")
        self._refresh_status()
        self._refresh_online_actions()

    def _request_rematch(self) -> None:
        if not self.online or not self.board.game_over:
            return
        if self.lan.send({"type": "rematch_request"}):
            self._network_system("已请求再来一局")
            self.statusBar().showMessage("已请求再来一局，等待对方回应", 5000)

    def _claim_draw(self) -> None:
        game = self.board.game
        if self.board.game_over or self.board.is_reviewing():
            return
        if not game.is_claimable_draw():
            return
        if self.online and game.turn != self.local_color:
            return
        reasons: list[str] = []
        if game.is_fifty_move_draw():
            reasons.append("50 回合规则")
        if game.is_threefold_repetition():
            reasons.append("三次重复局面")
        reason = "、".join(reasons)
        message = f"和棋（{reason}）"
        answer = QMessageBox.question(
            self,
            "判和",
            f"确认依据{reason}请求判和吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._draw_offer_pending = False
        if self.online:
            self.lan.send({"type": "claim_draw", "reason": reason})
            self._network_system(message)
        self.board.finish_game(message, "1/2-1/2")

    def _request_online_undo(self) -> None:
        if not self.online or self.board.game_over:
            return
        if self._undo_request_pending:
            self.statusBar().showMessage("已有悔棋请求等待对方回应", 4000)
            return
        history = self.board.game.history
        if not history:
            return
        if self.board.game.turn == self.local_color:
            target = max(0, len(history) - 2)
        else:
            target = max(0, len(history) - 1)
        if target == len(history):
            return
        if self.lan.send({"type": "undo_request", "target": target}):
            self._undo_request_pending = True
            self._undo_request_target = target
            self._network_system(f"已请求悔棋至第 {target} 手")
            self.statusBar().showMessage(
                f"已请求悔棋至第 {target} 手，等待对方同意", 5000
            )
            self._refresh_online_actions()

    def _set_online_controls(self) -> None:
        self.mode_combo.setEnabled(not self.online)
        self.side_combo.setEnabled(
            not self.online and self.match_mode == "human"
        )
        self.difficulty_combo.setEnabled(
            not self.online and self.match_mode in ("human", "engine")
        )
        self.undo_button.setEnabled(not self.online)
        self.import_button.setEnabled(not self.online)
        self.fen_button.setEnabled(not self.online)
        self._refresh_clock_controls()

    def _reset_online_game(
        self, send: bool = False, announce: bool = False
    ) -> None:
        self._ai_request_id += 1
        self._set_ai_thinking(False)
        self._ai_paused = False
        self.ai_used_colors.clear()
        self._reset_analysis_state()
        self.game_tree = GameTree()
        self.board.flipped = self.local_color == "b"
        self.eval_bar.set_flipped(self.board.flipped)
        self.board.new_game()
        self.board.locked_color = self.remote_color
        self.board.input_locked = False
        self._refresh_locks_online()
        self._draw_offer_pending = False
        self._undo_request_pending = False
        self._undo_request_target = None
        self._online_paused = False
        self.pause_button.setText("暂停")
        self._clock_pending_move = False
        base, increment = self._online_clock_config()
        self.clock.reset(base, increment)
        self.clock.start("w")
        self._update_clock_caption()
        self._update_clock_labels()
        self._refresh_clock_controls()
        self._refresh_status()
        self._refresh_notation()
        self._refresh_nav_buttons()
        self._refresh_captured()
        self._show_cached_eval(0)
        self._update_ai_status()
        if send:
            payload = {"type": "new_game", "game": self.net_game_id}
            if not self.lan.send(payload):
                self.lan.disconnect("发送新对局消息失败")
        if announce:
            self._network_system("你开始了新对局")

    def _refresh_locks_online(self) -> None:
        if self.online:
            if self._online_paused:
                self.board.locked_color = None
                self.board.input_locked = True
            else:
                self.board.locked_color = self.remote_color
                self.board.input_locked = False

    def _on_lan_connected(self, is_host: bool) -> None:
        if not self.lan.is_connected():
            return
        self.online = True
        self.is_online_host = is_host
        self.net_game_id = 1
        self.local_color = "w" if is_host else "b"
        self.remote_color = "b" if is_host else "w"
        self.match_mode = "two"
        self.mode_combo.blockSignals(True)
        index = self.mode_combo.findData("two")
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        self.mode_combo.blockSignals(False)
        self.ai_enabled = False
        self._ai_request_id += 1
        self._ai_paused = False
        self._draw_offer_pending = False
        self._online_paused = False
        self.pause_button.setText("暂停")
        self._set_ai_thinking(False)
        if is_host:
            if self._network_dialog is not None:
                base, increment = (
                    self._network_dialog.current_time_control()
                )
            else:
                base, increment = self._online_clock_config()
            self.online_time_control = (base, increment)
            self.lan.send(
                {
                    "type": "time_control",
                    "base": base,
                    "increment": increment,
                }
            )
        self._set_online_controls()
        self._reset_online_game()
        side = "白" if is_host else "黑"
        self.setWindowTitle(f"国际象棋 - 联机（你执{side}）")
        self.ai_status.setText(f"联机：已连接（你执{side}）")
        self.reset_button.setEnabled(self.is_online_host)
        self.statusBar().showMessage(
            f"联机已连接，你执{side}；点击“联机”可打开聊天窗口"
        )

    def _on_lan_disconnected(self, reason: str) -> None:
        if not self.online:
            return
        self.online = False
        self.is_online_host = False
        self.net_game_id = 0
        self.online_time_control = None
        self._clock_pending_move = False
        self._draw_offer_pending = False
        self._undo_request_pending = False
        self._undo_request_target = None
        self._online_paused = False
        self.pause_button.setText("暂停")
        self._unread_chat = 0
        self._update_chat_button()
        self._reset_local_clock()
        self.board.locked_color = None
        self.board.input_locked = False
        self.undo_button.setEnabled(True)
        self.import_button.setEnabled(True)
        self.fen_button.setEnabled(True)
        self.reset_button.setEnabled(True)
        self.setWindowTitle("国际象棋")
        self._apply_mode_controls()
        self._update_ai_status()
        self._refresh_status()
        if self.engine_path is not None:
            self._schedule_auto_analysis()
        self.statusBar().showMessage(f"联机已断开：{reason}")

    def _on_lan_error(self, message: str) -> None:
        self.statusBar().showMessage(f"联机错误：{message}", 6000)

    def _on_local_move(self, uci: str) -> None:
        if not self.online:
            return
        self._clock_pending_move = True
        message = {
            "type": "move",
            "uci": uci,
            "ply": len(self.board.game.history),
            "game": self.net_game_id,
            "fen": self.board.game.to_fen(),
        }
        if not self.lan.send(message):
            self.lan.disconnect("发送着法失败")

    def _apply_time_control_message(self, message: dict) -> None:
        if self.is_online_host:
            return
        try:
            base = int(message.get("base"))
            increment = int(message.get("increment"))
        except (TypeError, ValueError):
            self.lan.disconnect("同步错误：棋钟设置无效")
            return
        if not 60 <= base <= 10800 or not 0 <= increment <= 60:
            self.lan.disconnect("同步错误：棋钟设置超出范围")
            return
        self.online_time_control = (base, increment)
        if self._network_dialog is not None:
            self._network_dialog.apply_time_control(base, increment)
        if self.online:
            if not self.board.game.history:
                self._clock_pending_move = False
                self.clock.reset(base, increment)
                self.clock.start("w")
                self._update_clock_labels()
            else:
                self.clock.increment = increment
            self._update_clock_caption()

    def _on_lan_message(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "time_control":
            self._apply_time_control_message(message)
            return
        if not self.online:
            return
        if not isinstance(kind, str) or kind not in ONLINE_MESSAGE_TYPES:
            return
        game = self.board.game
        if kind == "move":
            game_id = message.get("game")
            if isinstance(game_id, int) and game_id != self.net_game_id:
                return
            if self.board.game_over:
                return
            if game.turn != self.remote_color:
                self.lan.disconnect("同步错误：现在不是对方走棋")
                return
            ply = message.get("ply")
            if isinstance(ply, int) and ply != len(game.history) + 1:
                self.lan.disconnect(
                    f"同步错误：对方步数 {ply} 与本地不一致"
                )
                return
            uci = str(message.get("uci", ""))
            move = game.find_move_by_uci(uci) if uci else None
            if move is None:
                self.lan.disconnect(f"同步错误：对方着法无效 {uci}")
                return
            self._clock_pending_move = True
            self.board.execute_move(move)
            expected_fen = message.get("fen")
            if (
                isinstance(expected_fen, str)
                and expected_fen
                and game.to_fen() != expected_fen
            ):
                self.lan.disconnect("同步错误：局面校验失败")
                return
        elif kind == "new_game":
            if self.is_online_host:
                return
            game_id = message.get("game")
            if isinstance(game_id, int):
                if game_id <= self.net_game_id:
                    return
                self.net_game_id = game_id
            self._reset_online_game()

        elif kind == "resign":
            if message.get("color") != self.remote_color:
                self.lan.disconnect("同步错误：认输消息无效")
                return
            result = "1-0" if self.remote_color == "b" else "0-1"
            self._draw_offer_pending = False
            self._network_system("对方认输")
            self.board.finish_game("对方认输，你获胜", result)

        elif kind == "timeout":
            color = message.get("color")
            if color not in ("w", "b"):
                self.lan.disconnect("同步错误：超时消息无效")
                return
            if self.board.game_over:
                return
            if color == self.local_color and (
                not self.clock.is_running()
                or self.clock.remaining_seconds(color) > 2.0
            ):
                self.lan.disconnect("同步错误：超时时间与本地棋钟不一致")
                return
            result = "0-1" if color == "w" else "1-0"
            loser = "白方" if color == "w" else "黑方"
            winner = "黑方" if color == "w" else "白方"
            message_text = f"{loser}超时，{winner}获胜"
            self._draw_offer_pending = False
            self._network_system(message_text)
            self.board.finish_game(message_text, result)

        elif kind == "claim_draw":
            if (
                game.turn != self.remote_color
                or not game.is_claimable_draw()
            ):
                self.lan.disconnect("同步错误：对方判和条件不成立")
                return
            reason = str(message.get("reason", "50 回合或三次重复规则"))
            self._draw_offer_pending = False
            self._network_system(f"对方请求判和（{reason}）")
            self.board.finish_game(f"和棋（{reason}）", "1/2-1/2")

        elif kind == "draw_offer":
            if self.board.game_over:
                return
            self._network_system("对方提议和棋")
            answer = QMessageBox.question(
                self._lan_dialog_parent(),
                "对方提和",
                "对方提议和棋，是否接受？",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._draw_offer_pending = False
                self.lan.send({"type": "draw_accept"})
                self._network_system("你接受了和棋")
                self.board.finish_game("双方同意和棋", "1/2-1/2")
            else:
                self.lan.send({"type": "draw_decline"})
                self._network_system("你拒绝了和棋")

        elif kind == "draw_accept":
            if not self._draw_offer_pending:
                self._network_system("收到无效的和棋回应，已忽略")
                return
            if self.board.game_over:
                return
            self._draw_offer_pending = False
            self._network_system("对方接受了和棋")
            self.board.finish_game("双方同意和棋", "1/2-1/2")

        elif kind == "draw_decline":
            if not self._draw_offer_pending:
                return
            self._draw_offer_pending = False
            self._network_system("对方拒绝了和棋")
            self._refresh_online_actions()

        elif kind == "undo_request":
            if self.board.game_over:
                return
            target = message.get("target")
            if not isinstance(target, int) or not (
                0 <= target < len(game.history)
            ):
                self.lan.disconnect("同步错误：悔棋目标无效")
                return
            answer = QMessageBox.question(
                self._lan_dialog_parent(),
                "对方请求悔棋",
                f"对方请求悔棋至第 {target} 手，是否同意？",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                node = self._node_at_ply(target)
                if node is None:
                    self.lan.disconnect("同步错误：找不到悔棋目标")
                    return
                self.lan.send({"type": "undo_accept", "target": target})
                self._go_to_node(node, truncate=True)
                self._network_system("你同意了对方悔棋")
            else:
                self.lan.send({"type": "undo_decline"})
                self._network_system("你拒绝了对方悔棋")

        elif kind == "undo_accept":
            if not self._undo_request_pending:
                self._network_system("收到无效的悔棋回应，已忽略")
                return
            requested_target = self._undo_request_target
            self._undo_request_pending = False
            self._undo_request_target = None
            if self.board.game_over:
                return
            target = message.get("target")
            if (
                target != requested_target
                or not isinstance(target, int)
                or not (0 <= target < len(game.history))
            ):
                self.lan.disconnect("同步错误：悔棋目标与请求不一致")
                return
            node = self._node_at_ply(target)
            if node is None:
                self.lan.disconnect("同步错误：找不到悔棋目标")
                return
            self._go_to_node(node, truncate=True)
            self._network_system("对方同意了悔棋")

        elif kind == "undo_decline":
            if not self._undo_request_pending:
                return
            self._undo_request_pending = False
            self._undo_request_target = None
            self._network_system("对方拒绝了悔棋")

        elif kind == "pause_request":
            if self.board.game_over or self._online_paused:
                return
            answer = QMessageBox.question(
                self._lan_dialog_parent(),
                "对方请求暂停",
                "对方请求暂停对局，是否同意？",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.lan.send({"type": "pause_accept"})
                self._set_online_paused(True)
            else:
                self.lan.send({"type": "pause_decline"})
                self._network_system("你拒绝了暂停")

        elif kind == "pause_accept":
            self._set_online_paused(True)

        elif kind == "pause_decline":
            self._network_system("对方拒绝暂停")

        elif kind == "resume_request":
            self.lan.send({"type": "resume_accept"})
            self._set_online_paused(False)

        elif kind == "resume_accept":
            self._set_online_paused(False)

        elif kind == "rematch_request":
            if not self.board.game_over:
                return
            answer = QMessageBox.question(
                self._lan_dialog_parent(),
                "再来一局",
                "对方请求再来一局，是否同意？",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.lan.send({"type": "rematch_decline"})
                self._network_system("你拒绝了再来一局")
                return
            if self.is_online_host:
                self.net_game_id += 1
                self._reset_online_game(send=True, announce=True)
                self._network_system("已开始新对局")
            else:
                self.lan.send({"type": "rematch_accept"})
                self._network_system("已同意再来一局，等待房主开始")

        elif kind == "rematch_accept":
            if not self.is_online_host or not self.board.game_over:
                return
            self.net_game_id += 1
            self._reset_online_game(send=True, announce=True)
            self._network_system("已开始新对局")

        elif kind == "rematch_decline":
            self._network_system("对方拒绝了再来一局")

        elif kind == "chat":
            text = str(message.get("text", ""))[:2000]
            if not text:
                return
            self.sound_player.play("chat")
            if (
                self._network_dialog is None
                or not self._network_dialog.isVisible()
                or not self._network_dialog.isActiveWindow()
            ):
                self._unread_chat += 1
                self._update_chat_button()
                self.statusBar().showMessage(
                    f"收到联机聊天：{text[:60]}", 5000
                )

    def _pgn_names(self) -> tuple[str, str]:
        if self.online:
            if self.local_color == "w":
                return "Host", "Guest"
            return "Guest", "Host"
        white = "Player"
        black = "Player 2"
        if self.match_mode == "human":
            if self.human_color == "w":
                black = "Stockfish"
            else:
                white = "Stockfish"
        elif self.match_mode == "engine":
            white = "Stockfish"
            black = "Stockfish"
        else:
            if "w" in self.ai_used_colors:
                white = "Stockfish"
            if "b" in self.ai_used_colors:
                black = "Stockfish"
        return white, black

    def _full_san_result(self) -> tuple[list[str], str]:
        sans = [node.san for node in self.game_tree.mainline()]
        result = self.board.final_result() or self.game_tree.result
        return sans, result

    def _pgn_text(self) -> str:
        white, black = self._pgn_names()
        if self.game_tree.headers.get("White"):
            white = self.game_tree.headers["White"]
        if self.game_tree.headers.get("Black"):
            black = self.game_tree.headers["Black"]
        result = self.board.final_result() or self.game_tree.result
        extra_headers: dict[str, str] = {}
        if self._clock_is_enabled():
            base, increment = self._active_clock_config()
            extra_headers["TimeControl"] = f"{base}+{increment}"
        return build_pgn_tree(
            self.game_tree,
            result,
            white=white,
            black=black,
            extra_headers=extra_headers,
        )

    def _export_pgn(self) -> None:
        pgn = self._pgn_text()
        default_name = f"chess_{date.today():%Y%m%d}.pgn"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 PGN",
            default_name,
            "PGN 文件 (*.pgn);;所有文件 (*)",
        )
        if not path:
            return
        if not path.lower().endswith(".pgn"):
            path += ".pgn"
        try:
            Path(path).write_text(pgn, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", f"无法写入文件：{exc}")
            return
        self.statusBar().showMessage(f"PGN 已保存：{path}", 5000)

    def _copy_pgn(self) -> None:
        QApplication.clipboard().setText(self._pgn_text())
        self.statusBar().showMessage("棋谱已复制到剪贴板", 4000)

    def _import_pgn(self) -> None:
        if self.online:
            QMessageBox.information(
                self, "联机中", "联机对局中不能导入 PGN，请先断开连接。"
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入 PGN",
            "",
            "PGN 文件 (*.pgn);;所有文件 (*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = Path(path).read_text(encoding="latin-1")
            except OSError as exc:
                QMessageBox.warning(self, "导入失败", f"无法读取文件：{exc}")
                return
        except OSError as exc:
            QMessageBox.warning(self, "导入失败", f"无法读取文件：{exc}")
            return

        try:
            tree = parse_pgn(text)
        except (PGNImportError, ValueError) as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return

        self._ai_request_id += 1
        self._set_ai_thinking(False)
        self._ai_paused = bool(self.ai_enabled)
        self.ai_used_colors.clear()
        self._reset_analysis_state()
        self.game_tree = tree
        node = tree.latest_node()
        tree.current = node
        imported = tree.build_game(node)
        self.board.set_game(imported, reviewing=False)
        self._refresh_locks()
        self._update_ai_status()
        self._show_cached_eval(0)
        self.statusBar().showMessage(
            f"已导入棋谱（主线 {len(tree.mainline())} 手，"
            f"{len(tree.root.children)} 个首着变例），"
            "可点击棋谱节点回放",
            6000,
        )

    def _tick_thinking(self) -> None:
        if not self.ai_thinking:
            return
        self._thinking_dots = (self._thinking_dots + 1) % 4
        self.ai_status.setText("Stockfish：思考中" + "·" * self._thinking_dots)

    def _set_ai_thinking(self, thinking: bool) -> None:
        self.ai_thinking = thinking
        if thinking:
            self._thinking_dots = 0
            self.ai_status.setText("Stockfish：思考中")
            self._thinking_timer.start()
        else:
            self._thinking_timer.stop()

    def _cancel_ai_request(self) -> None:
        if not self.ai_thinking:
            return
        self._ai_request_id += 1
        self._set_ai_thinking(False)
        self._ai_paused = True
        self._refresh_locks()
        self.ai_status.setText("Stockfish：已暂停，可手动走棋或点“重试”")
        self._refresh_status()

    def _retry_ai(self) -> None:
        if not self.ai_enabled or self.ai_thinking or self.board.game_over:
            return
        if self.board.is_reviewing() or self.board.is_animating():
            return
        self._ai_paused = False
        self._refresh_locks()
        self.ai_status.setText("Stockfish：已启用")
        self._maybe_request_ai()

    def _new_game(self) -> None:
        if self.online:
            if not self.is_online_host:
                self._network_system("只有房主可以开始新对局")
                return
            self.net_game_id += 1
            self._reset_online_game(send=True, announce=True)
            return
        self._ai_request_id += 1
        self._set_ai_thinking(False)
        self._ai_paused = False
        self.ai_used_colors.clear()
        self._reset_analysis_state()
        self.game_tree = GameTree()
        self.board.new_game()
        self._reset_local_clock()
        self._refresh_locks()
        self._apply_mode_controls()
        self._update_ai_status()
        self._refresh_status()
        self._maybe_request_ai()

    def _node_at_ply(self, ply: int) -> Optional[GameNode]:
        node = self.game_tree.current
        while node.parent is not None and node.ply > ply:
            node = node.parent
        if node.ply == ply:
            return node
        return None

    def _go_to_node(
        self,
        node: GameNode,
        truncate: bool = False,
        resume_ai: bool = False,
    ) -> None:
        if truncate:
            self.game_tree.truncate_after(node)
        self.game_tree.current = node
        self._prepare_navigation()
        game = self.game_tree.build_game(node)
        self.board.set_game(game, reviewing=bool(node.children))
        self._update_ai_status()
        if resume_ai and not self.board.is_reviewing():
            self._maybe_request_ai()

    def _undo(self) -> None:
        if self.online:
            self._request_online_undo()
            return
        current = self.game_tree.current
        if current.parent is None:
            return
        target = current.parent
        game = self.board.game
        if (
            not self.board.is_reviewing()
            and self.ai_enabled
            and self.match_mode == "human"
            and not self._ai_paused
            and game.turn == self.human_color
        ):
            if target.parent is None:
                return
            target = target.parent
        self._go_to_node(target)

    def _go_previous(self) -> None:
        if self.online:
            return
        parent = self.game_tree.current.parent
        if parent is None:
            return
        self._go_to_node(parent)

    def _go_next(self) -> None:
        if self.online or not self.game_tree.current.children:
            return
        self._go_to_node(
            self.game_tree.current.children[0], resume_ai=True
        )

    def _go_first(self) -> None:
        if self.online:
            return
        self._go_to_node(self.game_tree.root)

    def _go_latest(self) -> None:
        if self.online:
            return
        self._go_to_node(self.game_tree.latest_node(), resume_ai=True)

    def _jump_to_ply(self, ply: int) -> None:
        if self.online:
            self.statusBar().showMessage("联机对局中暂不支持回放", 3000)
            return
        node = self.game_tree.root
        while node.children and node.ply < ply:
            node = node.children[0]
        if node.ply == ply:
            self._go_to_node(node, resume_ai=True)

    def _on_notation_anchor(self, url) -> None:
        text = url.toString()
        if text.startswith("node:"):
            try:
                node_id = int(text[5:])
            except ValueError:
                return
            node = self.game_tree.node_by_id(node_id)
            if node is not None:
                self._go_to_node(node, resume_ai=True)
            return
        if not text.startswith("ply:"):
            return
        try:
            ply = int(text[4:])
        except ValueError:
            return
        self._jump_to_ply(ply)

    def _prepare_navigation(self) -> None:
        self._ai_request_id += 1
        self._clock_pending_move = False
        self._set_ai_thinking(False)
        self._analysis_token += 1
        self._analysis_cancel.set()
        self._analysis_timer.stop()
        self._set_hint_busy(False)
        self.board.set_hint(None)
        self.hint_label.setText("提示：--")

    def _refresh_nav_buttons(self) -> None:
        node = self.game_tree.current
        has_history = node.parent is not None
        can_next = bool(node.children)
        if self.online:
            self.first_button.setEnabled(False)
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.latest_button.setEnabled(False)
        else:
            self.first_button.setEnabled(has_history)
            self.prev_button.setEnabled(has_history)
            self.next_button.setEnabled(can_next)
            self.latest_button.setEnabled(
                node is not self.game_tree.latest_node()
            )
        self.copy_button.setEnabled(bool(self.game_tree.root.children))
        can_undo = has_history and (
            not self.online or not self.board.game_over
        )
        if (
            self.ai_enabled
            and self.match_mode == "human"
            and not self._ai_paused
            and not self.board.is_reviewing()
            and self.board.game.turn == self.human_color
            and node.ply < 2
        ):
            can_undo = False
        self.undo_button.setEnabled(can_undo)
        self.import_button.setEnabled(not self.online)
        self.hint_button.setEnabled(
            self.engine_path is not None
            and not self._hint_busy
            and not self.board.game_over
            and not self.online
        )

    def _on_state_changed(self) -> None:
        self.board.set_hint(None)
        self.hint_label.setText("提示：--")
        self._set_hint_busy(False)
        self._analysis_token += 1
        self._analysis_cancel.set()
        self._analysis_timer.stop()
        self._refresh_status()
        self._refresh_notation()
        self._refresh_nav_buttons()
        self._refresh_captured()
        if self.board.game_over:
            tag = self.board.final_result()
            if tag == "1-0":
                self.eval_bar.set_evaluation(1500, None)
                self.eval_label.setText("评估：白方胜")
            elif tag == "0-1":
                self.eval_bar.set_evaluation(-1500, None)
                self.eval_label.setText("评估：黑方胜")
            else:
                self.eval_bar.set_evaluation(0, None)
                self.eval_label.setText("评估：和棋")
        else:
            self._show_cached_eval(len(self.board.game.history))
        if self.engine_path is not None:
            self._schedule_auto_analysis()
        if self.ai_enabled and not self.ai_thinking:
            if self.board.is_reviewing():
                self.ai_status.setText("Stockfish：复盘暂停")
            elif self._ai_paused:
                self.ai_status.setText(
                    "Stockfish：已暂停，可手动走棋或点“重试”"
                )
        if self._clock_is_enabled():
            if (
                self._online_paused
                or self.board.game_over
                or self.board.is_reviewing()
            ):
                self.clock.stop()
            else:
                QTimer.singleShot(0, self._sync_clock_turn)
        else:
            self.clock.stop()
        self._update_clock_labels()
        self._refresh_clock_controls()
        self._refresh_eval_graph()
        self._refresh_accuracy()
        self._schedule_session_save()
        self._refresh_online_actions()

    def _sync_clock_turn(self) -> None:
        if not self._clock_is_enabled():
            self._clock_pending_move = False
            self.clock.stop()
            return
        if self._online_paused:
            self._clock_pending_move = False
            self.clock.stop()
            return
        if self.board.game_over or self.board.is_reviewing():
            self._clock_pending_move = False
            self.clock.stop()
            return
        game = self.board.game
        if self._clock_pending_move and self.clock.is_running():
            self._clock_pending_move = False
            self.clock.complete_move(game.turn)
            return
        self._clock_pending_move = False
        if self.online:
            self.clock.set_turn(game.turn)
        elif not game.history:
            self.clock.stop()
        elif not self.clock.is_running():
            self.clock.start(game.turn)
        else:
            self.clock.set_turn(game.turn)

    def _on_new_move(self) -> None:
        self._clock_pending_move = True
        game = self.board.game
        move = game.last_move
        if move is not None:
            piece = game.piece_at(move.to_row, move.to_col)
            color = ChessGame.color_of(piece) if piece else game.turn
            san = game.san_history[-1] if game.san_history else ""
            self.game_tree.add_move(
                move, san, color, make_mainline=True
            )
            self.board.reviewing = False
        ply = len(game.history)
        for mapping in (
            self._eval_scores,
            self._eval_display,
            self._move_annotations,
        ):
            for key in [key for key in mapping if key >= ply]:
                del mapping[key]
        self._set_hint_busy(False)

    def _refresh_status(self) -> None:
        text = self.board.status_text()
        if self.ai_thinking:
            text = f"{text} · Stockfish 思考中…"
        if self.online:
            text = f"{text} · 联机"
        self.turn_label.setText(text)

        if self.board.game_over:
            self.statusBar().showMessage(text)
        elif self.ai_thinking:
            self.statusBar().showMessage("正在等待 Stockfish 计算…")
        elif self.online:
            if self.board.game.turn == self.local_color:
                self.statusBar().showMessage("联机：轮到你走棋")
            else:
                self.statusBar().showMessage("联机：等待对方走棋")
        elif self.board.is_reviewing():
            total = len(
                self.game_tree.path_to(
                    self.game_tree.tip_from(self.game_tree.current)
                )
            )
            self.statusBar().showMessage(
                f"复盘：第 {self.game_tree.current.ply} / {total} 手"
            )
        elif self.board.game.in_check(self.board.game.turn):
            self.statusBar().showMessage("将军！请先解除被将军的状态")
        else:
            self.statusBar().showMessage(
                "点击或拖拽走子；可点击棋谱回放，提示按钮会显示最佳着"
            )

        self.cancel_ai_button.setEnabled(self.ai_enabled and self.ai_thinking)
        self.retry_ai_button.setEnabled(
            self.ai_enabled
            and not self.ai_thinking
            and not self.board.game_over
            and not self.board.is_reviewing()
            and not self.board.is_animating()
            and (self._ai_paused or self._ai_is_turn())
        )
        self._refresh_nav_buttons()
        self._refresh_online_actions()

    def _refresh_notation(self) -> None:
        tree = self.game_tree
        current = tree.current
        path_ids = {node.node_id for node in tree.path_to(current)}
        parts = [
            '<div style="margin:0; font-family:Consolas,\'Courier New\',monospace; '
            'font-size:12px; color:#e8ddc7; white-space: pre-wrap;">'
        ]
        tokens = self._notation_children(root=True, force_first=True)
        if not tokens:
            parts.append('<span style="color:#8d877d;">尚无着法</span>')
        else:
            parts.append(" ".join(tokens))
            result = self.board.final_result() or tree.result
            if result:
                parts.append(
                    f'\n<span style="color:#d8b26a;">结果：{result}</span>'
                )
        parts.append("</div>")
        self.notation.setHtml("".join(parts))
        if current.node_id != tree.root.node_id:
            self.notation.scrollToAnchor(f"node-{current.node_id}")
        else:
            self.notation.verticalScrollBar().setValue(0)

    def _notation_children(
        self,
        parent: Optional[GameNode] = None,
        root: bool = False,
        force_first: bool = False,
    ) -> list[str]:
        node = self.game_tree.root if root or parent is None else parent
        if not node.children:
            return []
        current = self.game_tree.current
        path_ids = {
            item.node_id for item in self.game_tree.path_to(current)
        }
        tokens: list[str] = [
            self._notation_node(node.children[0], force_first, path_ids)
        ]
        for variation in node.children[1:]:
            tokens.append("(")
            tokens.append(
                self._notation_node(variation, True, path_ids)
            )
            tokens.extend(self._notation_children(variation))
            tokens.append(")")
        tokens.extend(self._notation_children(node.children[0]))
        return tokens

    def _notation_node(
        self, node: GameNode, force_number: bool, path_ids: set[int]
    ) -> str:
        number = self.game_tree.move_number(node)
        if node.color == "w":
            prefix = f"{number}. "
        elif force_number:
            prefix = f"{number}... "
        else:
            prefix = ""
        style = "color:#e8ddc7; text-decoration:none;"
        if node.node_id not in path_ids:
            style = "color:#77716a; text-decoration:none;"
        if node.node_id == self.game_tree.current.node_id:
            style = (
                "color:#ffffff; text-decoration:none;"
                " background-color:#4d5b35;"
            )
        annotation = self._move_annotations.get(node.ply)
        suffix = ""
        if annotation:
            colors = {
                "??": "#ff6b6b",
                "?": "#ff9f43",
                "?!": "#e8c547",
                "!": "#7bd88f",
            }
            color = colors.get(annotation, "#e8c547")
            suffix = (
                f'<span style="color:{color};">{annotation}</span>'
            )
        nag_symbols = {1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!"}
        if node.nags:
            suffix += "".join(
                nag_symbols.get(nag, f"${nag}") for nag in node.nags
            )
        escaped = html_module.escape(node.san)
        link = (
            f'<a name="node-{node.node_id}" href="node:{node.node_id}" '
            f'style="{style}">{escaped}</a>{suffix}'
        )
        if node.comment:
            link += (
                f' <span style="color:#8d877d;">'
                f"{{{html_module.escape(node.comment)}}}</span>"
            )
        return prefix + link

    def _refresh_captured(self) -> None:
        by_white, by_black = self.board.game.captured_pieces()
        self.captured_widget.set_captured(by_white, by_black)

    def _on_mode_changed(self, index: int) -> None:
        if self._loading_settings or self.online:
            return
        desired = self.mode_combo.itemData(index)
        if desired is None or desired == self.match_mode:
            return
        if desired in ("human", "engine"):
            engine = find_stockfish()
            if engine is None:
                QMessageBox.warning(
                    self,
                    "缺少 Stockfish 引擎",
                    "未找到 Stockfish 可执行文件。请将 stockfish.exe 放入 "
                    "stockfish/ 目录，或设置 STOCKFISH_PATH 环境变量。",
                )
                self._restore_mode_combo()
                return
            self.engine_path = engine
        if self.board.game.history:
            answer = QMessageBox.question(
                self,
                "切换模式",
                "切换模式会重新开始对局，是否继续？",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._restore_mode_combo()
                return

        self.match_mode = desired
        self.ai_enabled = desired in ("human", "engine")
        if desired == "human":
            self.human_color = self.side_combo.currentData() or self.human_color
            self.ai_color = "w" if self.human_color == "b" else "b"
            self.board.flipped = self.human_color == "b"
        elif desired == "engine":
            self.board.flipped = False
        self.eval_bar.set_flipped(self.board.flipped)
        self._new_game()

    def _restore_mode_combo(self) -> None:
        self.mode_combo.blockSignals(True)
        index = self.mode_combo.findData(self.match_mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        self.mode_combo.blockSignals(False)

    def _on_human_side_changed(self, index: int) -> None:
        if self._loading_settings or self.online:
            return
        desired = self.side_combo.itemData(index)
        if desired is None or desired == self.human_color:
            return
        if self.match_mode != "human":
            self.human_color = desired
            self.ai_color = "w" if desired == "b" else "b"
            return
        if self.board.game.history:
            answer = QMessageBox.question(
                self,
                "更换执子",
                "更换执子会重新开始对局，是否继续？",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.side_combo.blockSignals(True)
                previous = self.side_combo.findData(self.human_color)
                if previous >= 0:
                    self.side_combo.setCurrentIndex(previous)
                self.side_combo.blockSignals(False)
                return

        self.human_color = desired
        self.ai_color = "w" if desired == "b" else "b"
        self.board.flipped = desired == "b"
        self.eval_bar.set_flipped(self.board.flipped)
        self._new_game()

    def _on_difficulty_changed(self, index: int) -> None:
        if self._loading_settings or self.online:
            return
        level = self.difficulty_combo.itemData(index)
        if level:
            self.difficulty = level
            self._update_ai_status()

    def _on_theme_changed(self, index: int) -> None:
        if self._loading_settings:
            return
        theme = self.theme_combo.itemData(index)
        if theme:
            self.board.set_theme(theme)

    def _apply_mode_controls(self) -> None:
        human_mode = self.match_mode == "human" and not self.online
        engine_mode = self.match_mode == "engine" and not self.online
        self.mode_combo.setEnabled(not self.online)
        self.side_combo.setEnabled(human_mode)
        self.difficulty_combo.setEnabled(human_mode or engine_mode)
        self._refresh_clock_controls()
        self._refresh_status()

    def _refresh_locks(self) -> None:
        if not self.ai_enabled or self._ai_paused:
            self.board.locked_color = None
            self.board.input_locked = False
        elif self.match_mode == "engine":
            self.board.locked_color = None
            self.board.input_locked = True
        else:
            self.board.locked_color = self.ai_color
            self.board.input_locked = False

    def _update_ai_status(self) -> None:
        if self.ai_thinking:
            return
        if self.online:
            side = "白" if self.local_color == "w" else "黑"
            if self.board.game_over:
                text = "联机：对局结束"
            else:
                text = f"联机：已连接（你执{side}）"
            self.ai_status.setText(text)
            return
        if not self.ai_enabled:
            text = "Stockfish：未启用"
        elif self.board.game_over:
            text = "Stockfish：对局结束"
        elif self._ai_paused:
            text = "Stockfish：已暂停，可手动走棋或点“重试”"
        elif self.board.is_reviewing():
            text = "Stockfish：复盘暂停"
        elif self.match_mode == "engine":
            text = f"Stockfish：引擎互弈（{self.difficulty}）"
        else:
            side = "黑" if self.ai_color == "b" else "白"
            text = f"Stockfish：已启用（AI 执{side}，{self.difficulty}）"
        self.ai_status.setText(text)

    def _ai_is_turn(self) -> bool:
        if not self.ai_enabled or self._ai_paused or self.board.game_over:
            return False
        if self.match_mode == "engine":
            return True
        if self.match_mode == "human":
            return self.board.game.turn == self.ai_color
        return False

    def _show_cached_eval(self, ply: int) -> None:
        data = self._eval_display.get(ply)
        if data is None:
            self.eval_bar.reset()
            self.eval_label.setText("评估：--")
        else:
            self.eval_bar.set_evaluation(*data)
            self.eval_label.setText(self._format_eval(*data))
        self._refresh_eval_graph()
        self._refresh_accuracy()

    @staticmethod
    def _format_eval(cp: Optional[int], mate: Optional[int]) -> str:
        if mate is not None:
            side = "白方" if mate > 0 else "黑方"
            return f"评估：{side}将死（{abs(mate)}）"
        if cp is not None:
            if cp >= 50:
                advantage = "白优"
            elif cp <= -50:
                advantage = "黑优"
            else:
                advantage = "均势"
            return f"评估：{cp / 100:+.2f}（{advantage}）"
        return "评估：--"

    @staticmethod
    def _short_eval(cp: Optional[int], mate: Optional[int]) -> str:
        if mate is not None:
            return f"{'白' if mate > 0 else '黑'}方将死"
        if cp is not None:
            return f"{cp / 100:+.2f}"
        return "--"

    @staticmethod
    def _score_symbol(loss: int) -> str:
        if loss >= 200:
            return "??"
        if loss >= 100:
            return "?"
        if loss >= 50:
            return "?!"
        if loss <= -60:
            return "!"
        return ""

    def _reset_analysis_state(self) -> None:
        self._analysis_token += 1
        self._analysis_cancel.set()
        self._analysis_timer.stop()
        self._eval_scores.clear()
        self._eval_display.clear()
        self._move_annotations.clear()
        self._set_hint_busy(False)
        self.eval_bar.reset()
        self.eval_label.setText("评估：--")
        self.eval_graph.clear()
        self.accuracy_label.setText("准确率：--")
        self.accuracy_label.setToolTip("")
        self.hint_label.setText("提示：--")
        self.hint_label.setToolTip("")
        self.board.set_hint(None)

    def _schedule_auto_analysis(self) -> None:
        self._auto_analysis_token = self._analysis_token
        self._analysis_timer.stop()
        if (
            not self.online
            and self.engine_path is not None
            and not self.board.game_over
        ):
            self._analysis_timer.start()

    def _auto_analysis_timeout(self) -> None:
        if self.online or self._auto_analysis_token != self._analysis_token:
            return
        if self._hint_busy or self.ai_thinking:
            return
        if (
            self.ai_enabled
            and not self.board.is_reviewing()
            and self._ai_is_turn()
        ):
            return
        self._start_analysis(self._auto_analysis_token, False)

    def _start_analysis(self, token: int, explicit: bool) -> None:
        self._analysis_cancel.set()
        cancel_event = threading.Event()
        self._analysis_cancel = cancel_event
        moves = [
            ChessGame.move_to_uci(move) for _, move in self.board.game.history
        ]
        thread = threading.Thread(
            target=self._analysis_worker,
            args=(token, moves, explicit, cancel_event),
            daemon=True,
        )
        thread.start()

    def _analysis_worker(
        self,
        token: int,
        moves: list[str],
        explicit: bool,
        cancel_event: threading.Event,
    ) -> None:
        try:
            result = analyse_position(
                moves=moves,
                movetime_ms=900 if explicit else 320,
                cancel_event=cancel_event,
                multipv=3 if explicit else 1,
            )
        except Exception as exc:
            self.analysisReady.emit(token, str(exc), explicit)
            return
        self.analysisReady.emit(token, result, explicit)

    def _on_analysis_ready(
        self, token: int, payload: object, explicit: bool
    ) -> None:
        if token != self._analysis_token:
            return
        if explicit:
            self._set_hint_busy(False)
        if not isinstance(payload, AnalysisResult):
            if explicit:
                self.hint_label.setText("提示：分析失败")
                self.statusBar().showMessage(f"分析失败：{payload}", 6000)
            return
        self._apply_analysis_result(payload, explicit)

    def _apply_analysis_result(
        self, result: AnalysisResult, explicit: bool
    ) -> None:
        game = self.board.game
        ply = len(game.history)
        cp = result.score_cp
        mate = result.mate
        if game.turn == "b":
            if cp is not None:
                cp = -cp
            if mate is not None:
                mate = -mate

        display_lines: list[AnalysisLine] = []
        for line in result.lines:
            line_cp = line.score_cp
            line_mate = line.mate
            if game.turn == "b":
                if line_cp is not None:
                    line_cp = -line_cp
                if line_mate is not None:
                    line_mate = -line_mate
            display_lines.append(
                AnalysisLine(
                    multipv=line.multipv,
                    score_cp=line_cp,
                    mate=line_mate,
                    pv=line.pv,
                )
            )

        self.eval_bar.set_evaluation(cp, mate)
        self.eval_label.setText(self._format_eval(cp, mate))
        self._eval_display[ply] = (cp, mate)

        if mate is not None:
            value = 1000 if mate > 0 else -1000 if mate < 0 else 0
        else:
            value = cp

        notation_changed = False
        if value is not None:
            before = self._eval_scores.get(ply - 1)
            self._eval_scores[ply] = value
            node = self.game_tree.current
            if before is not None and ply > 0 and not node.is_root:
                mover = node.color
                loss = before - value if mover == "w" else value - before
                symbol = self._score_symbol(loss)
                if symbol:
                    self._move_annotations[ply] = symbol
                else:
                    self._move_annotations.pop(ply, None)
                notation_changed = True

        self._refresh_eval_graph()
        self._refresh_accuracy()
        if notation_changed:
            self._refresh_notation()

        if explicit:
            moves: list[Move] = []
            for line in display_lines:
                if not line.pv:
                    continue
                move = game.find_move_by_uci(line.pv[0])
                if move is not None and move not in moves:
                    moves.append(move)
            if not moves:
                fallback = game.find_move_by_uci(result.bestmove)
                if fallback is not None:
                    moves.append(fallback)
            if moves:
                self.board.set_hint_moves(moves[:3])
                primary = moves[0]
                san = game.san_for_move(primary)
                self.hint_label.setText(
                    f"建议：{san}（{self._short_eval(cp, mate)}）"
                )
                tooltip_lines: list[str] = []
                for index, line in enumerate(display_lines[:3]):
                    if line.pv:
                        line_move = game.find_move_by_uci(line.pv[0])
                        line_san = (
                            game.san_for_move(line_move)
                            if line_move is not None
                            else line.pv[0]
                        )
                    else:
                        line_san = "?"
                    tooltip_lines.append(
                        f"{index + 1}. {line_san} "
                        f"({self._short_eval(line.score_cp, line.mate)})"
                    )
                self.hint_label.setToolTip("\n".join(tooltip_lines))
            else:
                self.board.set_hint_moves([])
                self.hint_label.setText("提示：当前局面没有可用着法")
                self.hint_label.setToolTip("")

    def _refresh_eval_graph(self) -> None:
        self.eval_graph.set_scores(
            self._eval_scores, self.game_tree.current.ply
        )

    def _accuracy_stats(self) -> dict[str, tuple[float, int, float]]:
        totals = {
            "w": [0.0, 0],
            "b": [0.0, 0],
        }
        for node in self.game_tree.mainline():
            before = self._eval_scores.get(node.ply - 1)
            after = self._eval_scores.get(node.ply)
            if before is None or after is None:
                continue
            loss = before - after if node.color == "w" else after - before
            loss = max(0.0, min(1000.0, float(loss)))
            totals[node.color][0] += loss
            totals[node.color][1] += 1
        stats: dict[str, tuple[float, int, float]] = {}
        for color, (loss_sum, count) in totals.items():
            if count:
                acpl = loss_sum / count
                accuracy = 100.0 * math.exp(-acpl / 200.0)
                stats[color] = (acpl, count, accuracy)
            else:
                stats[color] = (0.0, 0, 0.0)
        return stats

    def _refresh_accuracy(self) -> None:
        stats = self._accuracy_stats()
        parts: list[str] = []
        tooltip: list[str] = []
        for color, label in (("w", "白"), ("b", "黑")):
            acpl, count, accuracy = stats[color]
            if count:
                parts.append(f"{label} {accuracy:.0f}")
                tooltip.append(
                    f"{label}方：准确率 {accuracy:.1f}%，"
                    f"平均损失 {acpl:.0f} cp（{count} 手）"
                )
            else:
                parts.append(f"{label} --")
        self.accuracy_label.setText("准确率：" + " / ".join(parts))
        self.accuracy_label.setToolTip("\n".join(tooltip))

    def _request_hint(self) -> None:
        if self.online:
            self.statusBar().showMessage("联机对局中已关闭引擎提示", 4000)
            return
        if (
            self._hint_busy
            or self.engine_path is None
            or self.board.game_over
        ):
            return
        self._analysis_timer.stop()
        self._analysis_token += 1
        token = self._analysis_token
        self._set_hint_busy(True)
        self.hint_label.setText("提示：分析中…")
        self._start_analysis(token, True)

    def _set_hint_busy(self, busy: bool) -> None:
        self._hint_busy = busy
        self.hint_button.setText("分析中…" if busy else "提示")
        self.hint_button.setEnabled(
            not busy
            and self.engine_path is not None
            and not self.board.game_over
        )

    def _schedule_session_save(self) -> None:
        if self._loading_settings or self._session_restoring:
            return
        self._session_save_timer.start()

    def _save_session(self) -> None:
        if self._loading_settings or self._session_restoring:
            return
        tree = self.game_tree
        if (
            not tree.root.children
            and not self.board.result_override
            and tree.start_fen == ChessGame.START_FEN
        ):
            clear_state()
            return
        if not tree.current.children:
            result = self.board.final_result()
            if result:
                tree.result = result
        state = {
            "tree": tree.to_dict(),
            "match_mode": "two" if self.online else self.match_mode,
            "human_color": self.human_color,
            "difficulty": self.difficulty,
            "ai_paused": self._ai_paused,
            "flipped": bool(self.board.flipped),
            "result_override": self.board.result_override or "",
            "finish_message": self.board._finish_message or "",
            "clock_enabled": self._clock_is_enabled(),
            "clock_base": self.clock.base_seconds,
            "clock_increment": self.clock.increment,
            "clock_white": self.clock.remaining_seconds("w"),
            "clock_black": self.clock.remaining_seconds("b"),
        }
        save_state(state)

    def _restore_session(self) -> bool:
        data = load_state()
        if not data:
            return False

        try:
            tree_data = data.get("tree")
            if isinstance(tree_data, dict):
                tree = GameTree.from_dict(tree_data)
            else:
                start_fen = data.get("start_fen")
                if not isinstance(start_fen, str) or not start_fen.strip():
                    start_fen = ChessGame.START_FEN
                moves = data.get("moves", [])
                if (
                    not isinstance(moves, list)
                    or len(moves) > 10000
                    or any(not isinstance(item, str) for item in moves)
                ):
                    raise ValueError("保存的着法无效")
                tree = GameTree(start_fen)
                node = tree.root
                for uci in moves:
                    game = tree.build_game(node)
                    move = game.find_move_by_uci(uci)
                    if move is None:
                        raise ValueError(f"无法恢复着法：{uci}")
                    node = tree.append_move(
                        node, move, game.san_for_move(move), game.turn
                    )
                ply = data.get("ply")
                if isinstance(ply, int) and not isinstance(ply, bool):
                    path = [tree.root, *tree.path_to(node)]
                    if 0 <= ply < len(path):
                        node = path[ply]
                tree.current = node
        except (ValueError, IndexError, TypeError):
            clear_state()
            self.statusBar().showMessage(
                "上次对局无法恢复，已开始新对局", 6000
            )
            return False

        game = tree.build_game(tree.current)

        mode = data.get("match_mode")
        if mode not in ("two", "human", "engine"):
            mode = "two"
        if mode in ("human", "engine") and self.engine_path is None:
            mode = "two"

        human_color = data.get("human_color")
        if human_color not in ("w", "b"):
            human_color = self.human_color
        difficulty = data.get("difficulty")
        if difficulty not in AI_LEVELS:
            difficulty = self.difficulty

        self.match_mode = mode
        self.ai_enabled = mode in ("human", "engine")
        self.human_color = human_color
        self.ai_color = "w" if human_color == "b" else "b"
        self.difficulty = difficulty
        if mode == "human":
            self.ai_used_colors = {self.ai_color}
        elif mode == "engine":
            self.ai_used_colors = {"w", "b"}
        else:
            self.ai_used_colors = set()

        for combo, value in (
            (self.mode_combo, mode),
            (self.side_combo, human_color),
            (self.difficulty_combo, difficulty),
        ):
            combo.blockSignals(True)
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)

        flipped = data.get("flipped")
        if isinstance(flipped, bool):
            self.board.flipped = flipped
        elif mode == "human":
            self.board.flipped = human_color == "b"
        self.eval_bar.set_flipped(self.board.flipped)

        self.game_tree = tree
        self._ai_paused = bool(data.get("ai_paused")) and self.ai_enabled
        self._session_restoring = True
        try:
            self.board.set_game(
                game, reviewing=self.game_tree.is_reviewing()
            )
            override = data.get("result_override")
            if (
                isinstance(override, str)
                and override
                and not self.game_tree.current.children
            ):
                self.board.result_override = override
                self.board._finish_message = str(
                    data.get("finish_message") or ""
                )
                self.board.game_over = True
        finally:
            self._session_restoring = False

        clock_enabled = bool(data.get("clock_enabled"))
        self.clock_checkbox.blockSignals(True)
        self.clock_checkbox.setChecked(clock_enabled)
        self.clock_checkbox.blockSignals(False)

        try:
            base = max(
                1,
                int(
                    data.get(
                        "clock_base",
                        self.clock_minutes_spin.value() * 60,
                    )
                ),
            )
            increment = max(0, int(data.get("clock_increment", 0)))
        except (TypeError, ValueError):
            base = self.clock_minutes_spin.value() * 60
            increment = self.clock_increment_spin.value()

        for spin, value in (
            (self.clock_minutes_spin, max(1, min(180, base // 60))),
            (self.clock_increment_spin, max(0, min(60, increment))),
        ):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

        self.clock.reset(base, increment)
        try:
            remaining_white = float(data.get("clock_white", base))
            remaining_black = float(data.get("clock_black", base))
        except (TypeError, ValueError):
            remaining_white = remaining_black = float(base)
        self.clock.remaining = {
            "w": max(0.0, remaining_white),
            "b": max(0.0, remaining_black),
        }
        if (
            clock_enabled
            and game.history
            and not self.board.game_over
            and not self.board.is_reviewing()
        ):
            self.clock.start(game.turn)

        self._update_clock_caption()
        self._update_clock_labels()
        self._refresh_clock_controls()
        self._on_state_changed()
        self.statusBar().showMessage("已恢复上次对局", 5000)
        if (
            self.ai_enabled
            and not self._ai_paused
            and not self.board.game_over
            and not self.board.is_reviewing()
        ):
            QTimer.singleShot(0, self._maybe_request_ai)
        return True

    def _show_fen_dialog(self) -> None:
        if self.online:
            QMessageBox.information(
                self, "联机中", "联机对局中不能通过 FEN 更换局面。"
            )
            return
        dialog = FenDialog(self.board.game.to_fen(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            tree = GameTree(dialog.fen)
        except ValueError as exc:
            QMessageBox.warning(self, "FEN 无效", str(exc))
            return

        self._ai_request_id += 1
        self._set_ai_thinking(False)
        self._ai_paused = False
        self.ai_used_colors.clear()
        self._reset_analysis_state()
        self.game_tree = tree
        self.board.set_game(tree.build_game(tree.root), reviewing=False)
        self._reset_local_clock()
        self._refresh_locks()
        self._apply_mode_controls()
        self._update_ai_status()
        self._refresh_status()
        self._refresh_notation()
        self._refresh_nav_buttons()
        self._refresh_captured()
        self._show_cached_eval(0)
        self._maybe_request_ai()

    def _load_settings(self) -> None:
        settings = self._settings

        theme = str(settings.value("theme", "经典"))
        if theme in THEMES:
            index = self.theme_combo.findData(theme)
            if index >= 0:
                self.theme_combo.setCurrentIndex(index)
            self.board.set_theme(theme)

        coordinates = bool(int(settings.value("show_coordinates", 1)))
        self.coords_checkbox.setChecked(coordinates)
        self.board.set_coordinates(coordinates)

        sound = bool(int(settings.value("sound", 1)))
        self.sound_checkbox.setChecked(sound)
        self.sound_player.set_enabled(sound)

        clock_enabled = bool(int(settings.value("clock_enabled", 0)))
        self.clock_checkbox.setChecked(clock_enabled)
        self.clock_minutes_spin.setValue(
            max(1, min(180, int(settings.value("clock_minutes", 10))))
        )
        self.clock_increment_spin.setValue(
            max(0, min(60, int(settings.value("clock_increment", 0))))
        )
        self._refresh_clock_controls()
        self._update_clock_caption()
        self._update_clock_labels()

        difficulty = str(settings.value("difficulty", "普通"))
        index = self.difficulty_combo.findData(difficulty)
        if index >= 0:
            self.difficulty_combo.setCurrentIndex(index)
        self.difficulty = self.difficulty_combo.currentData() or "普通"

        human_color = str(settings.value("human_color", "w"))
        index = self.side_combo.findData(human_color)
        if index >= 0:
            self.side_combo.setCurrentIndex(index)
        self.human_color = self.side_combo.currentData() or "w"
        self.ai_color = "w" if self.human_color == "b" else "b"

        self.board.flipped = bool(int(settings.value("flipped", 0)))
        self.eval_bar.set_flipped(self.board.flipped)

        geometry = settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def _save_settings(self) -> None:
        settings = self._settings
        settings.setValue("theme", self.board.theme_name)
        settings.setValue(
            "show_coordinates", int(self.board.show_coordinates)
        )
        settings.setValue("sound", int(self.sound_player.enabled))
        settings.setValue(
            "clock_enabled", int(self.clock_checkbox.isChecked())
        )
        settings.setValue("clock_minutes", self.clock_minutes_spin.value())
        settings.setValue("clock_increment", self.clock_increment_spin.value())
        settings.setValue("difficulty", self.difficulty)
        settings.setValue("human_color", self.human_color)
        settings.setValue("flipped", int(self.board.flipped))
        settings.setValue("geometry", self.saveGeometry())
        settings.sync()

    def _maybe_request_ai(self) -> None:
        if self.ai_thinking or self.board.is_animating():
            return
        if self.board.is_reviewing() or not self._ai_is_turn():
            return

        game = self.board.game
        legal_moves = game.all_legal_moves()
        if not legal_moves:
            return

        played_moves = [
            ChessGame.move_to_uci(move) for _, move in game.history
        ]
        skill_level, movetime_ms = AI_LEVELS.get(
            self.difficulty, AI_LEVELS["普通"]
        )

        self._ai_request_id += 1
        request_id = self._ai_request_id
        self._refresh_locks()
        self._set_ai_thinking(True)
        self._refresh_status()

        thread = threading.Thread(
            target=self._ai_worker,
            args=(request_id, played_moves, skill_level, movetime_ms),
            daemon=True,
        )
        thread.start()

    def _ai_worker(
        self,
        request_id: int,
        played_moves: list[str],
        skill_level: int,
        movetime_ms: int,
    ) -> None:
        try:
            bestmove = ask_stockfish_for_move(
                moves=played_moves,
                skill_level=skill_level,
                movetime_ms=movetime_ms,
            )
        except Exception as exc:  # engine missing, timeout, protocol errors
            self.aiResponse.emit(
                request_id, None, f"{type(exc).__name__}: {exc}"
            )
            return
        self.aiResponse.emit(request_id, bestmove, "")

    def _on_ai_response(
        self, request_id: int, content: object, error: str
    ) -> None:
        if request_id != self._ai_request_id:
            return
        self._set_ai_thinking(False)
        if not self.ai_enabled or self._ai_paused:
            return

        game = self.board.game
        if self.board.game_over or self.board.is_reviewing():
            self._update_ai_status()
            return
        if self.match_mode == "human" and game.turn != self.ai_color:
            self._update_ai_status()
            return

        legal_moves = game.all_legal_moves()
        uci = str(content).strip() if content is not None else ""
        if uci:
            uci = uci.split()[0]
        move = game.find_move_by_uci(uci) if uci else None

        if move is None:
            reason = error.strip() if error else "Stockfish 返回了无效着法"
            reason = reason.splitlines()[0][:120] if reason else "未知错误"
            if legal_moves:
                move = random.choice(legal_moves)
                self.ai_status.setText(
                    f"Stockfish 请求失败，已随机落子：{reason}"
                )
            else:
                self.ai_status.setText(f"Stockfish 请求失败：{reason}")
                self._refresh_status()
                return
        else:
            self.ai_status.setText("Stockfish：已落子")

        self.ai_used_colors.add(game.turn)
        self.board.execute_move(move)

    def _on_game_ended(self, message: str) -> None:
        self._set_ai_thinking(False)
        result = self.board.final_result()
        if result:
            self.game_tree.result = result
        if self.online:
            self.clock.stop()
        self._refresh_status()
        self._refresh_notation()
        if self.online:
            self.ai_status.setText("联机：对局结束")
        elif self.ai_enabled:
            self.ai_status.setText("Stockfish：对局结束")
        QMessageBox.information(
            self._lan_dialog_parent(), "对局结束", message
        )

    def closeEvent(self, event) -> None:
        self._session_save_timer.stop()
        self._save_session()
        self._save_settings()
        if self._network_dialog is not None:
            self._network_dialog.hide()
        self.lan.shutdown()
        self.online = False
        self._ai_request_id += 1
        self._analysis_token += 1
        self._analysis_cancel.set()
        self._analysis_timer.stop()
        self.ai_enabled = False
        self._set_ai_thinking(False)
        self.board.locked_color = None
        self.board.input_locked = False
        super().closeEvent(event)
