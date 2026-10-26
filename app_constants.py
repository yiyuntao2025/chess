from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QColor


BASE_DIR = Path(__file__).resolve().parent
PIECES_DIR = BASE_DIR / "assets" / "pieces"

SELECTED_COLOR = QColor(130, 190, 80, 150)
LAST_MOVE_COLOR = QColor(255, 235, 59, 90)
CHECK_COLOR = QColor(220, 60, 60, 110)
LEGAL_DOT_COLOR = QColor(30, 30, 30, 110)
LEGAL_RING_COLOR = QColor(30, 30, 30, 140)
HINT_COLOR = QColor(255, 166, 0, 210)
HINT_COLORS = (
    HINT_COLOR,
    QColor(80, 160, 255, 190),
    QColor(80, 200, 120, 190),
)

THEMES = {
    "经典": (QColor("#f0d9b5"), QColor("#b58863")),
    "森林": (QColor("#eeeed2"), QColor("#769656")),
    "蓝灰": (QColor("#dfe6ea"), QColor("#8ca2ad")),
    "暖木": (QColor("#f3e0c7"), QColor("#a97b50")),
}

AI_LEVELS = {
    "入门": (0, 250),
    "普通": (8, 600),
    "困难": (20, 1200),
}

PIECE_LETTERS = {"K": "W", "Q": "Q", "R": "R", "B": "B", "N": "K", "P": "P"}

PROMOTION_CHOICES = {
    "皇后": "Q",
    "车": "R",
    "象": "B",
    "马": "N",
}

PIECE_VALUES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}
ONLINE_CLOCK_SECONDS = 600
ONLINE_MESSAGE_TYPES = {
    "move",
    "new_game",
    "resign",
    "timeout",
    "claim_draw",
    "draw_offer",
    "draw_accept",
    "draw_decline",
    "undo_request",
    "undo_accept",
    "undo_decline",
    "chat",
    "pause_request",
    "pause_accept",
    "pause_decline",
    "resume_request",
    "resume_accept",
    "rematch_request",
    "rematch_accept",
    "rematch_decline",
}
