from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PyQt6.QtWidgets import QInputDialog, QWidget

from app_constants import (
    CHECK_COLOR,
    HINT_COLORS,
    LAST_MOVE_COLOR,
    LEGAL_DOT_COLOR,
    LEGAL_RING_COLOR,
    PIECE_LETTERS,
    PIECE_VALUES,
    PIECES_DIR,
    PROMOTION_CHOICES,
    SELECTED_COLOR,
    THEMES,
)
from chess_engine import ChessGame, Move


class EvalBar(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(18)
        self.setMinimumHeight(120)
        self.score_cp: Optional[int] = None
        self.mate: Optional[int] = None
        self.flipped = False
        self._update_tooltip()

    def set_evaluation(
        self, score_cp: Optional[int], mate: Optional[int]
    ) -> None:
        self.score_cp = score_cp
        self.mate = mate
        self._update_tooltip()
        self.update()

    def set_flipped(self, flipped: bool) -> None:
        self.flipped = flipped
        self.update()

    def reset(self) -> None:
        self.set_evaluation(None, None)

    def _update_tooltip(self) -> None:
        if self.mate is not None:
            side = "白方" if self.mate > 0 else "黑方"
            if self.mate == 0:
                text = "评估：将死"
            else:
                text = f"评估：{side} {abs(self.mate)} 步将死"
        elif self.score_cp is not None:
            text = f"评估：{self.score_cp / 100:+.2f}"
        else:
            text = "评估：--"
        self.setToolTip(text)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = QRectF(self.rect())
        painter.fillRect(outer, QColor("#1b1a18"))
        inner = outer.adjusted(2, 2, -2, -2)
        if inner.width() <= 0 or inner.height() <= 0:
            return

        if self.mate is not None:
            fraction = 1.0 if self.mate > 0 else 0.0
        elif self.score_cp is not None:
            clamped = max(-1500, min(1500, self.score_cp))
            fraction = 1.0 / (1.0 + 10 ** (-clamped / 400))
        else:
            fraction = 0.5

        painter.fillRect(inner, QColor("#2b2926"))
        white_height = inner.height() * fraction
        if self.flipped:
            white_rect = QRectF(
                inner.x(), inner.y(), inner.width(), white_height
            )
        else:
            white_rect = QRectF(
                inner.x(),
                inner.bottom() - white_height,
                inner.width(),
                white_height,
            )
        painter.fillRect(white_rect, QColor("#f4f1e8"))

        painter.setPen(QPen(QColor(0, 0, 0, 80), 1))
        painter.drawLine(
            QPointF(inner.left(), inner.center().y()),
            QPointF(inner.right(), inner.center().y()),
        )


class EvalGraphWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(74)
        self.setToolTip("评估曲线（白方视角）")
        self.scores: dict[int, int] = {}
        self.current_ply = 0

    def set_scores(self, scores: dict[int, int], current_ply: int) -> None:
        self.scores = dict(scores)
        self.current_ply = current_ply
        self.update()

    def clear(self) -> None:
        self.scores.clear()
        self.current_ply = 0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = QRectF(self.rect())
        painter.fillRect(outer, QColor("#1d1b19"))
        painter.setPen(QPen(QColor("#3d3933"), 1))
        painter.drawRect(outer.adjusted(0.5, 0.5, -0.5, -0.5))
        inner = outer.adjusted(8, 8, -8, -8)
        if inner.width() <= 0 or inner.height() <= 0:
            return

        font = QFont(self.font())
        font.setPixelSize(10)
        painter.setFont(font)
        painter.setPen(QColor("#8d877d"))
        painter.drawText(
            QRectF(inner.left(), 2, inner.width(), 12),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            "评估曲线",
        )

        if not self.scores:
            painter.setPen(QColor("#77716a"))
            painter.drawText(
                inner,
                Qt.AlignmentFlag.AlignCenter,
                "暂无数据",
            )
            return

        max_ply = max(
            [self.current_ply, 1, *self.scores.keys()]
        )
        center_y = inner.center().y()
        painter.setPen(QPen(QColor(120, 115, 105, 100), 1))
        painter.drawLine(
            QPointF(inner.left(), center_y),
            QPointF(inner.right(), center_y),
        )

        points: list[QPointF] = []
        for ply in sorted(self.scores):
            clamped = max(-800, min(800, self.scores[ply]))
            x = inner.left() + (ply / max_ply) * inner.width()
            y = center_y - (clamped / 800.0) * (inner.height() / 2 - 8)
            points.append(QPointF(x, y))
        if len(points) >= 2:
            painter.setPen(
                QPen(QColor("#d8b26a"), 2, Qt.PenStyle.SolidLine)
            )
            painter.drawPolyline(QPolygonF(points))
        elif points:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#d8b26a"))
            painter.drawEllipse(points[0], 2.5, 2.5)

        marker_x = inner.left() + (
            min(self.current_ply, max_ply) / max_ply
        ) * inner.width()
        painter.setPen(QPen(QColor("#7bd88f"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(
            QPointF(marker_x, inner.top()),
            QPointF(marker_x, inner.bottom()),
        )


class CapturedPiecesWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setToolTip("吃子")
        self.by_white: list[str] = []
        self.by_black: list[str] = []
        self._source_cache: dict[str, QPixmap] = {}
        self._scaled_cache: dict[tuple[str, int, float], QPixmap] = {}

    def set_captured(
        self, by_white: list[str], by_black: list[str]
    ) -> None:
        self.by_white = sorted(
            by_white,
            key=lambda piece: PIECE_VALUES.get(piece.upper(), 0),
            reverse=True,
        )
        self.by_black = sorted(
            by_black,
            key=lambda piece: PIECE_VALUES.get(piece.upper(), 0),
            reverse=True,
        )
        names = {"P": "兵", "N": "马", "B": "象", "R": "车", "Q": "后"}
        white_captures = " ".join(
            names.get(piece.upper(), piece) for piece in self.by_white
        ) or "无"
        black_captures = " ".join(
            names.get(piece.upper(), piece) for piece in self.by_black
        ) or "无"
        self.setToolTip(
            f"白方吃子：{white_captures}\n黑方吃子：{black_captures}"
        )
        self.update()

    def clear(self) -> None:
        self.set_captured([], [])

    def _source_pixmap(self, piece: str) -> Optional[QPixmap]:
        cached = self._source_cache.get(piece)
        if cached is not None:
            return cached if not cached.isNull() else None
        color_suffix = "W" if piece.isupper() else "B"
        stem = f"{PIECE_LETTERS[piece.upper()]}{color_suffix}"
        path = PIECES_DIR / f"{stem}.png"
        if not path.exists():
            path = PIECES_DIR / f"{stem}.PNG"
        pixmap = QPixmap(str(path))
        self._source_cache[piece] = pixmap
        return pixmap if not pixmap.isNull() else None

    def _scaled_pixmap(self, piece: str, size: float) -> Optional[QPixmap]:
        source = self._source_pixmap(piece)
        if source is None:
            return None
        dpr = max(1.0, self.devicePixelRatioF())
        target = max(1, int(size))
        key = (piece, target, round(dpr, 2))
        cached = self._scaled_cache.get(key)
        if cached is not None:
            return cached
        scaled = source.scaled(
            int(target * dpr),
            int(target * dpr),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        self._scaled_cache[key] = scaled
        return scaled

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        total = len(self.by_white) + len(self.by_black)
        if total == 0:
            return

        painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
        painter.drawLine(0, 0, self.width(), 0)

        label_font = QFont(self.font())
        label_font.setPixelSize(10)
        painter.setFont(label_font)
        painter.setPen(QColor("#8d877d"))
        painter.drawText(
            QRectF(8, 0, 36, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "白吃",
        )
        painter.drawText(
            QRectF(self.width() - 44, 0, 36, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            "黑吃",
        )

        available = max(1.0, self.width() - 100)
        spacing = min(28.0, available / total)
        size = spacing * 0.95
        center_y = self.height() / 2

        x = 48.0
        for piece in self.by_white:
            self._draw_piece(painter, piece, x, center_y - size / 2, size)
            x += spacing

        x = self.width() - 48.0 - size
        for piece in self.by_black:
            self._draw_piece(painter, piece, x, center_y - size / 2, size)
            x -= spacing

    def _draw_piece(
        self,
        painter: QPainter,
        piece: str,
        x: float,
        y: float,
        size: float,
    ) -> None:
        pixmap = self._scaled_pixmap(piece, size)
        if pixmap is not None:
            painter.drawPixmap(QPointF(x, y), pixmap)
            return
        font = QFont(self.font())
        font.setPixelSize(max(10, int(size * 0.8)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(
            QColor("#f4f1e8") if piece.isupper() else QColor("#1a1a1a")
        )
        painter.drawText(
            QRectF(x, y, size, size),
            Qt.AlignmentFlag.AlignCenter,
            piece.upper(),
        )


class ChessBoard(QWidget):
    stateChanged = pyqtSignal()
    gameEnded = pyqtSignal(str)
    moveCompleted = pyqtSignal()
    moveSound = pyqtSignal(str)
    newMovePlayed = pyqtSignal()
    userMovePlayed = pyqtSignal(str)

    ANIMATION_DURATION = 220

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(560, 560)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.game = ChessGame()
        self.selected: Optional[tuple[int, int]] = None
        self.legal_moves: list[Move] = []
        self.legal_targets: set[tuple[int, int]] = set()
        self.game_over = False
        self.locked_color: Optional[str] = None
        self.input_locked = False
        self.flipped = False
        self.theme_name = "经典"
        self.light_color, self.dark_color = THEMES[self.theme_name]
        self.show_coordinates = True
        self.hint_moves: list[Move] = []
        self._redo_moves: list[Move] = []
        self._dragging = False
        self._drag_piece: Optional[str] = None
        self._drag_pos: Optional[QPointF] = None
        self._source_cache: dict[str, QPixmap] = {}
        self._scaled_cache: dict[tuple[str, int, float], QPixmap] = {}
        self._animation: Optional[dict] = None
        self._animation_anim: Optional[QVariantAnimation] = None
        self._pending_result: Optional[str] = None
        self.result_override: Optional[str] = None
        self._finish_message: Optional[str] = None
        self.reviewing = False

    def new_game(self) -> None:
        self._cancel_animation()
        self.game.reset()
        self._redo_moves.clear()
        self.reviewing = False
        self.hint_moves = []
        self.selected = None
        self.legal_moves = []
        self.legal_targets = set()
        self.game_over = False
        self.result_override = None
        self._finish_message = None
        self.update()
        self.stateChanged.emit()

    def set_game(self, game: ChessGame, reviewing: bool = False) -> None:
        self._cancel_animation()
        self.game = game
        self._redo_moves.clear()
        self.reviewing = reviewing
        self.hint_moves = []
        self.selected = None
        self.legal_moves = []
        self.legal_targets = set()
        self.result_override = None
        self._finish_message = None
        self.game_over = bool(game.result_tag())
        self.update()
        self.stateChanged.emit()

    def final_result(self) -> str:
        return self.result_override or self.game.result_tag()

    def finish_game(self, message: str, result_tag: str) -> None:
        if self.game_over:
            return
        self._cancel_animation()
        self.selected = None
        self.legal_moves = []
        self.legal_targets = set()
        self.hint_moves = []
        self.result_override = result_tag
        self._finish_message = message
        self.game_over = True
        self.update()
        self.stateChanged.emit()
        self.moveSound.emit("end")
        self.gameEnded.emit(message)

    def rollback_to(self, ply: int) -> None:
        self._cancel_animation()
        ply = max(0, min(ply, len(self.game.history)))
        while len(self.game.history) > ply:
            self.game.undo_move()
        self._redo_moves.clear()
        self.result_override = None
        self._finish_message = None
        self.hint_moves = []
        self.selected = None
        self.legal_moves = []
        self.legal_targets = set()
        self.game_over = bool(self.game.result_tag())
        self.update()
        self.stateChanged.emit()

    def undo(self) -> None:
        if not self.game.history:
            return
        self.set_ply(len(self.game.history) - 1)

    def redo(self) -> bool:
        if not self._redo_moves:
            return False
        return self.set_ply(len(self.game.history) + 1)

    def set_ply(self, ply: int) -> bool:
        total = len(self.game.history) + len(self._redo_moves)
        ply = max(0, min(ply, total))
        if ply == len(self.game.history):
            return False

        self._cancel_animation()
        changed = False
        while len(self.game.history) > ply:
            move = self.game.undo_move()
            if move is None:
                break
            self._redo_moves.append(move)
            changed = True
        while len(self.game.history) < ply and self._redo_moves:
            move = self._redo_moves.pop()
            self.game.make_move(move)
            changed = True

        if changed:
            self.selected = None
            self.legal_moves = []
            self.legal_targets = set()
            self.hint_moves = []
            self.game_over = bool(self.game.result_tag())
            self.result_override = None
            self._finish_message = None
            self.update()
            self.stateChanged.emit()
        return changed

    def is_reviewing(self) -> bool:
        return self.reviewing or bool(self._redo_moves)

    def total_plies(self) -> int:
        return len(self.game.history) + len(self._redo_moves)

    def set_theme(self, name: str) -> None:
        if name not in THEMES:
            return
        self.theme_name = name
        self.light_color, self.dark_color = THEMES[name]
        self.update()

    def set_coordinates(self, visible: bool) -> None:
        self.show_coordinates = visible
        self.update()

    def flip(self) -> None:
        self.flipped = not self.flipped
        self.update()

    def set_hint(self, move: Optional[Move]) -> None:
        self.set_hint_moves([move] if move is not None else [])

    def set_hint_moves(self, moves: list[Move]) -> None:
        self.hint_moves = list(moves)
        self.update()

    def is_animating(self) -> bool:
        return self._animation is not None

    def status_text(self) -> str:
        game = self.game
        if self.game_over and self._finish_message:
            return self._finish_message
        if game.is_checkmate():
            winner = "白方" if game.turn == "b" else "黑方"
            return f"将死！{winner}获胜"
        if game.is_stalemate():
            return "逼和，双方和棋"
        if game.is_insufficient_material():
            return "和棋（子力不足）"
        if game.is_seventyfive_move_draw():
            return "和棋（75 回合规则）"
        if game.is_fivefold_repetition():
            return "和棋（五次重复局面）"
        side = "白方" if game.turn == "w" else "黑方"
        if game.in_check(game.turn):
            return f"{side}被将军"
        if game.is_claimable_draw():
            return f"{side}走棋（可判和）"
        return f"{side}走棋"

    def _view_to_board(self, view_row: int, view_col: int) -> tuple[int, int]:
        if self.flipped:
            return 7 - view_row, 7 - view_col
        return view_row, view_col

    def _board_to_view(self, row: int, col: int) -> tuple[int, int]:
        return self._view_to_board(row, col)

    def _board_geometry(self) -> tuple[float, float, float]:
        size = min(self.width(), self.height())
        square = size / 8
        left = (self.width() - size) / 2
        top = (self.height() - size) / 2
        return left, top, square

    def _square_at(self, x: float, y: float) -> Optional[tuple[int, int]]:
        left, top, square = self._board_geometry()
        if not (left <= x < left + square * 8 and top <= y < top + square * 8):
            return None
        view_col = int((x - left) / square)
        view_row = int((y - top) / square)
        return self._view_to_board(view_row, view_col)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.game_over or self.is_animating() or self.input_locked:
            return
        square = self._square_at(event.position().x(), event.position().y())
        if square is None:
            return

        row, col = square
        piece = self.game.piece_at(row, col)

        if self.selected is not None and (row, col) in self.legal_targets:
            self._play_move(row, col)
            return

        if piece is not None and self.game.color_of(piece) == self.game.turn:
            if self.locked_color == self.game.turn:
                return
            self._select(row, col)
            self._start_drag(row, col, event.position())
            return

        if self.selected is not None:
            self._clear_selection()

    def _start_drag(self, row: int, col: int, position: QPointF) -> None:
        piece = self.game.piece_at(row, col)
        if piece is None:
            return
        self._dragging = True
        self._drag_piece = piece
        self._drag_pos = QPointF(position)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self._drag_pos = QPointF(event.position())
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            super().mouseReleaseEvent(event)
            return

        self._dragging = False
        self._drag_piece = None
        self._drag_pos = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        square = self._square_at(event.position().x(), event.position().y())
        if (
            square is not None
            and self.selected is not None
            and square in self.legal_targets
        ):
            self._play_move(*square)
        else:
            self.update()
        super().mouseReleaseEvent(event)

    def _select(self, row: int, col: int) -> None:
        self.selected = (row, col)
        self.legal_moves = self.game.legal_moves(row, col)
        self.legal_targets = {(move.to_row, move.to_col) for move in self.legal_moves}
        self.update()

    def _clear_selection(self) -> None:
        self.selected = None
        self.legal_moves = []
        self.legal_targets = set()
        self.update()

    def _play_move(self, to_row: int, to_col: int) -> None:
        candidates = [
            move
            for move in self.legal_moves
            if (move.to_row, move.to_col) == (to_row, to_col)
        ]
        if not candidates:
            return

        move = candidates[0]
        if len(candidates) > 1:
            promotion = self._ask_promotion()
            if promotion is None:
                return
            move = next(
                candidate for candidate in candidates if candidate.promotion == promotion
            )

        self.execute_move(move)
        self.userMovePlayed.emit(ChessGame.move_to_uci(move))

    def execute_move(self, move: Move) -> None:
        game = self.game
        moving_piece = game.piece_at(move.from_row, move.from_col)
        if moving_piece is None:
            return

        if self._animation is not None:
            self._cancel_animation()
        self._redo_moves.clear()
        self.reviewing = False
        self.hint_moves = []
        self._dragging = False
        self._drag_piece = None
        self._drag_pos = None

        captured_piece = None
        captured_pos: Optional[tuple[int, int]] = None
        if move.is_en_passant:
            captured_pos = (move.from_row, move.to_col)
            captured_piece = game.piece_at(*captured_pos)
        else:
            target = game.piece_at(move.to_row, move.to_col)
            if target is not None:
                captured_pos = (move.to_row, move.to_col)
                captured_piece = target

        rook_piece = None
        rook_from: Optional[tuple[int, int]] = None
        rook_to: Optional[tuple[int, int]] = None
        if move.is_castle:
            rook_from_col = 7 if move.to_col > move.from_col else 0
            rook_to_col = 5 if move.to_col > move.from_col else 3
            rook_from = (move.from_row, rook_from_col)
            rook_to = (move.from_row, rook_to_col)
            rook_piece = game.piece_at(*rook_from)

        game.make_move(move)
        self.selected = None
        self.legal_moves = []
        self.legal_targets = set()
        self.game_over = False
        self._pending_result = None
        self.result_override = None
        self._finish_message = None

        if game.is_checkmate():
            self.game_over = True
            winner = "白方" if game.turn == "b" else "黑方"
            self._pending_result = f"将死！{winner}获胜"
        elif game.is_stalemate():
            self.game_over = True
            self._pending_result = "逼和，双方和棋"
        elif game.is_insufficient_material():
            self.game_over = True
            self._pending_result = "和棋（子力不足）"
        elif game.is_seventyfive_move_draw():
            self.game_over = True
            self._pending_result = "和棋（75 回合规则）"
        elif game.is_fivefold_repetition():
            self.game_over = True
            self._pending_result = "和棋（五次重复局面）"

        if self.game_over:
            sound = "end"
        elif game.in_check(game.turn):
            sound = "check"
        elif captured_piece is not None:
            sound = "capture"
        else:
            sound = "move"
        self.moveSound.emit(sound)

        self._start_animation(
            move,
            moving_piece,
            captured_piece,
            captured_pos,
            rook_piece,
            rook_from,
            rook_to,
        )
        self.newMovePlayed.emit()
        self.update()
        self.stateChanged.emit()

    def _start_animation(
        self,
        move: Move,
        moving_piece: str,
        captured_piece: Optional[str],
        captured_pos: Optional[tuple[int, int]],
        rook_piece: Optional[str],
        rook_from: Optional[tuple[int, int]],
        rook_to: Optional[tuple[int, int]],
    ) -> None:
        self._animation = {
            "move": move,
            "piece": moving_piece,
            "from": (move.from_row, move.from_col),
            "to": (move.to_row, move.to_col),
            "captured_piece": captured_piece,
            "captured_pos": captured_pos,
            "rook_piece": rook_piece,
            "rook_from": rook_from,
            "rook_to": rook_to,
            "progress": 0.0,
        }
        anim = QVariantAnimation(self)
        anim.setDuration(self.ANIMATION_DURATION)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._on_animation_value)
        anim.finished.connect(self._on_animation_finished)
        self._animation_anim = anim
        anim.start()

    def _on_animation_value(self, value) -> None:
        if self._animation is None:
            return
        self._animation["progress"] = float(value)
        self.update()

    def _on_animation_finished(self) -> None:
        anim = self._animation_anim
        self._animation_anim = None
        if anim is not None:
            anim.deleteLater()
        if self._animation is None:
            return
        self._animation = None
        self.update()
        self.moveCompleted.emit()
        if self._pending_result:
            message = self._pending_result
            self._pending_result = None
            self.gameEnded.emit(message)

    def _cancel_animation(self) -> None:
        anim = self._animation_anim
        self._animation_anim = None
        self._animation = None
        self._pending_result = None
        if anim is not None:
            anim.stop()
            anim.deleteLater()
        self.update()

    def _ask_promotion(self) -> Optional[str]:
        options = list(PROMOTION_CHOICES.keys())
        choice, accepted = QInputDialog.getItem(
            self, "兵升变", "选择升变棋子：", options, 0, False
        )
        if not accepted:
            return None
        return PROMOTION_CHOICES[choice]

    def _piece_pixmap(self, piece: str) -> Optional[QPixmap]:
        cached = self._source_cache.get(piece)
        if cached is not None:
            return cached if not cached.isNull() else None

        color_suffix = "W" if piece.isupper() else "B"
        stem = f"{PIECE_LETTERS[piece.upper()]}{color_suffix}"
        path = PIECES_DIR / f"{stem}.png"
        if not path.exists():
            path = PIECES_DIR / f"{stem}.PNG"
        pixmap = QPixmap(str(path))
        self._source_cache[piece] = pixmap
        return pixmap if not pixmap.isNull() else None

    def _scaled_piece(self, piece: str, logical_size: float) -> Optional[QPixmap]:
        source = self._piece_pixmap(piece)
        if source is None:
            return None

        dpr = max(1.0, self.devicePixelRatioF())
        target = max(1, int(logical_size))
        key = (piece, target, round(dpr, 2))
        cached = self._scaled_cache.get(key)
        if cached is not None:
            return cached

        scaled = source.scaled(
            int(target * dpr),
            int(target * dpr),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        self._scaled_cache[key] = scaled
        return scaled

    def resizeEvent(self, event) -> None:
        self._scaled_cache.clear()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#262421"))

        left, top, square = self._board_geometry()
        last_move = self.game.last_move
        last_squares = set()
        if last_move is not None:
            last_squares = {
                (last_move.from_row, last_move.from_col),
                (last_move.to_row, last_move.to_col),
            }

        checked_king = None
        if self.game.in_check(self.game.turn):
            checked_king = self.game.find_king(self.game.turn)

        for view_row in range(8):
            for view_col in range(8):
                row, col = self._view_to_board(view_row, view_col)
                rect = QRectF(
                    left + view_col * square,
                    top + view_row * square,
                    square,
                    square,
                )
                is_light = (view_row + view_col) % 2 == 0
                painter.fillRect(
                    rect, self.light_color if is_light else self.dark_color
                )

                if (row, col) in last_squares:
                    painter.fillRect(rect, LAST_MOVE_COLOR)
                if self.selected == (row, col):
                    painter.fillRect(rect, SELECTED_COLOR)
                if checked_king == (row, col):
                    painter.fillRect(rect, CHECK_COLOR)

                if (row, col) in self.legal_targets:
                    if self.game.piece_at(row, col) is None:
                        radius = square * 0.14
                        center = rect.center()
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(LEGAL_DOT_COLOR)
                        painter.drawEllipse(center, radius, radius)
                    else:
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.setPen(QPen(LEGAL_RING_COLOR, square * 0.055))
                        margin = square * 0.07
                        painter.drawEllipse(
                            rect.adjusted(margin, margin, -margin, -margin)
                        )
                    painter.setPen(Qt.PenStyle.NoPen)

        anim = self._animation
        skip_squares: set[tuple[int, int]] = set()
        if anim is not None:
            skip_squares.add(anim["to"])
            if anim["rook_to"] is not None:
                skip_squares.add(anim["rook_to"])
        if self._dragging and self.selected is not None:
            skip_squares.add(self.selected)

        for view_row in range(8):
            for view_col in range(8):
                row, col = self._view_to_board(view_row, view_col)
                if (row, col) in skip_squares:
                    continue
                piece = self.game.piece_at(row, col)
                if piece is None:
                    continue
                center_x, center_y = self._square_center(
                    view_row, view_col, left, top, square
                )
                self._draw_piece_at(
                    painter, piece, center_x, center_y, square * 0.92
                )

        if anim is not None:
            progress = float(anim["progress"])
            if anim["captured_piece"] is not None and anim["captured_pos"] is not None:
                cap_view = self._board_to_view(*anim["captured_pos"])
                cap_x, cap_y = self._square_center(
                    *cap_view, left, top, square
                )
                self._draw_piece_at(
                    painter,
                    anim["captured_piece"],
                    cap_x,
                    cap_y,
                    square * 0.92,
                    opacity=max(0.0, 1.0 - progress),
                    scale=max(0.5, 1.0 - 0.4 * progress),
                )

            from_view = self._board_to_view(*anim["from"])
            to_view = self._board_to_view(*anim["to"])
            from_x, from_y = self._square_center(
                *from_view, left, top, square
            )
            to_x, to_y = self._square_center(*to_view, left, top, square)
            piece_x = from_x + (to_x - from_x) * progress
            piece_y = from_y + (to_y - from_y) * progress
            self._draw_piece_at(
                painter, anim["piece"], piece_x, piece_y, square * 0.92
            )

            if (
                anim["rook_piece"] is not None
                and anim["rook_from"] is not None
                and anim["rook_to"] is not None
            ):
                rook_from_view = self._board_to_view(*anim["rook_from"])
                rook_to_view = self._board_to_view(*anim["rook_to"])
                rook_from_x, rook_from_y = self._square_center(
                    *rook_from_view, left, top, square
                )
                rook_to_x, rook_to_y = self._square_center(
                    *rook_to_view, left, top, square
                )
                rook_x = rook_from_x + (rook_to_x - rook_from_x) * progress
                rook_y = rook_from_y + (rook_to_y - rook_from_y) * progress
                self._draw_piece_at(
                    painter,
                    anim["rook_piece"],
                    rook_x,
                    rook_y,
                    square * 0.92,
                )

        for index, move in enumerate(self.hint_moves[: len(HINT_COLORS)]):
            self._draw_hint_arrow(
                painter,
                left,
                top,
                square,
                move,
                HINT_COLORS[index],
                1.0 - index * 0.18,
            )

        if (
            self._dragging
            and self._drag_piece is not None
            and self._drag_pos is not None
        ):
            self._draw_piece_at(
                painter,
                self._drag_piece,
                self._drag_pos.x(),
                self._drag_pos.y(),
                square * 0.92,
                opacity=0.9,
                scale=1.05,
            )

        if self.show_coordinates:
            self._draw_coordinates(painter, left, top, square)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#1b1a18"), max(2.0, square * 0.035)))
        painter.drawRect(
            QRectF(left, top, square * 8, square * 8).adjusted(-1, -1, 1, 1)
        )

    @staticmethod
    def _square_center(
        row: int, col: int, left: float, top: float, square: float
    ) -> tuple[float, float]:
        return left + (col + 0.5) * square, top + (row + 0.5) * square

    def _draw_piece_at(
        self,
        painter: QPainter,
        piece: str,
        center_x: float,
        center_y: float,
        logical_size: float,
        opacity: float = 1.0,
        scale: float = 1.0,
    ) -> None:
        pixmap = self._scaled_piece(piece, logical_size)
        painter.save()
        painter.setOpacity(opacity)
        painter.translate(center_x, center_y)
        painter.scale(scale, scale)
        if pixmap is not None:
            width = pixmap.width() / pixmap.devicePixelRatio()
            height = pixmap.height() / pixmap.devicePixelRatio()
            painter.drawPixmap(QPointF(-width / 2, -height / 2), pixmap)
        else:
            font = QFont(self.font())
            font.setPixelSize(max(12, int(logical_size * 0.6)))
            font.setBold(True)
            painter.setFont(font)
            color = QColor("#fafafa") if piece.isupper() else QColor("#1a1a1a")
            painter.setPen(color)
            painter.drawText(
                QRectF(-logical_size / 2, -logical_size / 2, logical_size, logical_size),
                Qt.AlignmentFlag.AlignCenter,
                piece.upper(),
            )
        painter.restore()

    def _draw_hint_arrow(
        self,
        painter: QPainter,
        left: float,
        top: float,
        square: float,
        move: Move,
        color: QColor,
        scale: float = 1.0,
    ) -> None:
        from_view = self._board_to_view(move.from_row, move.from_col)
        to_view = self._board_to_view(move.to_row, move.to_col)
        start_x, start_y = self._square_center(
            *from_view, left, top, square
        )
        end_x, end_y = self._square_center(*to_view, left, top, square)
        dx = end_x - start_x
        dy = end_y - start_y
        length = math.hypot(dx, dy)
        if length == 0:
            return

        ux, uy = dx / length, dy / length
        tip_x, tip_y = end_x, end_y
        head_length = square * 0.28 * scale
        head_width = square * 0.20 * scale
        base_x = tip_x - ux * head_length
        base_y = tip_y - uy * head_length
        perp_x, perp_y = -uy, ux

        painter.save()
        pen = QPen(color, max(3.0, square * 0.075 * scale))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(start_x, start_y), QPointF(base_x, base_y))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(tip_x, tip_y),
                    QPointF(
                        base_x + perp_x * head_width / 2,
                        base_y + perp_y * head_width / 2,
                    ),
                    QPointF(
                        base_x - perp_x * head_width / 2,
                        base_y - perp_y * head_width / 2,
                    ),
                ]
            )
        )
        painter.restore()

    def _draw_coordinates(
        self, painter: QPainter, left: float, top: float, square: float
    ) -> None:
        if square < 36:
            return
        font = QFont(self.font())
        font.setPixelSize(max(9, int(square * 0.16)))
        font.setBold(True)
        painter.setFont(font)

        for view_col in range(8):
            board_col = 7 - view_col if self.flipped else view_col
            rect = QRectF(
                left + view_col * square, top + 7 * square, square, square
            )
            color = (
                self.dark_color if (7 + view_col) % 2 == 0 else self.light_color
            )
            painter.setPen(color)
            painter.drawText(
                rect.adjusted(0, 0, -square * 0.08, -square * 0.04),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                chr(ord("a") + board_col),
            )

        for view_row in range(8):
            board_row = 7 - view_row if self.flipped else view_row
            rect = QRectF(left, top + view_row * square, square, square)
            color = (
                self.dark_color if view_row % 2 == 0 else self.light_color
            )
            painter.setPen(color)
            painter.drawText(
                rect.adjusted(square * 0.08, square * 0.04, 0, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                str(8 - board_row),
            )
