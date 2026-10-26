from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


BOARD_SIZE = 8

KNIGHT_OFFSETS = ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1))
KING_OFFSETS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
ORTHOGONAL_DIRECTIONS = ((-1, 0), (1, 0), (0, -1), (0, 1))
DIAGONAL_DIRECTIONS = ((-1, -1), (-1, 1), (1, -1), (1, 1))


@dataclass(frozen=True)
class Move:
    from_row: int
    from_col: int
    to_row: int
    to_col: int
    promotion: Optional[str] = None
    is_castle: bool = False
    is_en_passant: bool = False


class ChessGame:
    START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._load_fen(self.START_FEN)
        self.history: list[tuple[dict, Move]] = []
        self.san_history: list[str] = []

    def _load_fen(self, fen: str) -> None:
        placement, turn, castling, ep_square, halfmove, fullmove = fen.split()
        self.board: list[list[Optional[str]]] = [[None] * BOARD_SIZE for _ in range(BOARD_SIZE)]
        for row, rank in enumerate(placement.split("/")):
            col = 0
            for char in rank:
                if char.isdigit():
                    col += int(char)
                else:
                    self.board[row][col] = char
                    col += 1
        self.turn = turn
        self.castling = "" if castling == "-" else castling
        if ep_square == "-":
            self.ep_target = None
        else:
            self.ep_target = (8 - int(ep_square[1]), ord(ep_square[0]) - ord("a"))
        self.halfmove_clock = int(halfmove)
        self.fullmove_number = int(fullmove)
        self.position_counts: dict[tuple, int] = {self._position_key(): 1}

    @staticmethod
    def color_of(piece: str) -> str:
        return "w" if piece.isupper() else "b"

    @staticmethod
    def opponent(color: str) -> str:
        return "b" if color == "w" else "w"

    def piece_at(self, row: int, col: int) -> Optional[str]:
        return self.board[row][col]

    def find_king(self, color: str) -> Optional[tuple[int, int]]:
        target = "K" if color == "w" else "k"
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                if self.board[row][col] == target:
                    return row, col
        return None

    def in_check(self, color: str) -> bool:
        king = self.find_king(color)
        if king is None:
            return False
        return self.is_square_attacked(king[0], king[1], self.opponent(color))

    def is_square_attacked(self, row: int, col: int, by_color: str) -> bool:
        board = self.board
        enemy_pawn = "P" if by_color == "w" else "p"
        enemy_knight = "N" if by_color == "w" else "n"
        enemy_king = "K" if by_color == "w" else "k"

        pawn_row = row + 1 if by_color == "w" else row - 1
        for dc in (-1, 1):
            pawn_col = col + dc
            if 0 <= pawn_row < BOARD_SIZE and 0 <= pawn_col < BOARD_SIZE:
                if board[pawn_row][pawn_col] == enemy_pawn:
                    return True

        for dr, dc in KNIGHT_OFFSETS:
            r, c = row + dr, col + dc
            if 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board[r][c] == enemy_knight:
                return True

        for dr, dc in KING_OFFSETS:
            r, c = row + dr, col + dc
            if 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board[r][c] == enemy_king:
                return True

        rook_targets = {"R", "Q"} if by_color == "w" else {"r", "q"}
        bishop_targets = {"B", "Q"} if by_color == "w" else {"b", "q"}

        for dr, dc in ORTHOGONAL_DIRECTIONS:
            r, c = row + dr, col + dc
            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE:
                piece = board[r][c]
                if piece is not None:
                    if piece in rook_targets:
                        return True
                    break
                r += dr
                c += dc

        for dr, dc in DIAGONAL_DIRECTIONS:
            r, c = row + dr, col + dc
            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE:
                piece = board[r][c]
                if piece is not None:
                    if piece in bishop_targets:
                        return True
                    break
                r += dr
                c += dc

        return False

    def legal_moves(self, row: int, col: int) -> list[Move]:
        piece = self.board[row][col]
        if piece is None or self.color_of(piece) != self.turn:
            return []
        return self._legal_moves_for_piece(row, col)

    def all_legal_moves(self, color: Optional[str] = None) -> list[Move]:
        color = color or self.turn
        moves: list[Move] = []
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                piece = self.board[row][col]
                if piece is not None and self.color_of(piece) == color:
                    moves.extend(self._legal_moves_for_piece(row, col))
        return moves

    def _legal_moves_for_piece(self, row: int, col: int) -> list[Move]:
        piece = self.board[row][col]
        if piece is None:
            return []
        color = self.color_of(piece)
        legal: list[Move] = []
        for move in self._pseudo_legal_moves(row, col):
            snapshot = self._snapshot()
            self._apply_move(move)
            allowed = not self.in_check(color)
            self._restore(snapshot)
            if allowed:
                legal.append(move)
        return legal

    def is_checkmate(self, color: Optional[str] = None) -> bool:
        color = color or self.turn
        return self.in_check(color) and not self.all_legal_moves(color)

    def is_stalemate(self, color: Optional[str] = None) -> bool:
        color = color or self.turn
        return not self.in_check(color) and not self.all_legal_moves(color)

    def is_fifty_move_draw(self) -> bool:
        return self.halfmove_clock >= 100

    def is_seventyfive_move_draw(self) -> bool:
        return self.halfmove_clock >= 150

    def is_threefold_repetition(self) -> bool:
        return self.position_counts.get(self._position_key(), 0) >= 3

    def is_fivefold_repetition(self) -> bool:
        return self.position_counts.get(self._position_key(), 0) >= 5

    def is_claimable_draw(self) -> bool:
        return self.is_fifty_move_draw() or self.is_threefold_repetition()

    def is_automatic_draw(self) -> bool:
        return (
            self.is_insufficient_material()
            or self.is_seventyfive_move_draw()
            or self.is_fivefold_repetition()
        )

    def is_insufficient_material(self) -> bool:
        pieces: list[tuple[int, int, str]] = []
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                piece = self.board[row][col]
                if piece is not None and piece.upper() != "K":
                    pieces.append((row, col, piece))

        if not pieces:
            return True
        if len(pieces) == 1:
            return pieces[0][2].upper() in ("B", "N")
        if len(pieces) == 2:
            first_row, first_col, first = pieces[0]
            second_row, second_col, second = pieces[1]
            if first.upper() != "B" or second.upper() != "B":
                return False
            if first.islower() == second.islower():
                return False
            return (first_row + first_col) % 2 == (second_row + second_col) % 2
        return False

    def captured_pieces(self) -> tuple[list[str], list[str]]:
        captured_by_white: list[str] = []
        captured_by_black: list[str] = []
        for snapshot, move in self.history:
            snapshot_board = snapshot["board"]
            if move.is_en_passant:
                row, col = move.from_row, move.to_col
            else:
                row, col = move.to_row, move.to_col
            piece = snapshot_board[row][col]
            if piece is None:
                continue
            if piece.islower():
                captured_by_white.append(piece)
            else:
                captured_by_black.append(piece)
        return captured_by_white, captured_by_black

    @staticmethod
    def _normalize_san(san: str) -> str:
        text = san.strip()
        text = text.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
        text = re.sub(r"e\.p\.", "", text, flags=re.IGNORECASE)
        text = text.replace("=", "")
        text = re.sub(r"[!?]+$", "", text)
        text = text.rstrip("+#")
        return text

    def find_move_by_san(self, san: str) -> Optional[Move]:
        target = self._normalize_san(san)
        if not target:
            return None
        for move in self.all_legal_moves():
            if self._normalize_san(self.san_for_move(move)) == target:
                return move
        return None

    def make_move(self, move: Move) -> None:
        piece = self.board[move.from_row][move.from_col]
        san = self._san_base(move) if piece is not None else ""
        snapshot = self._snapshot()
        self._apply_move(move)
        if piece is not None:
            opponent = self.turn
            if self.in_check(opponent):
                san += "#" if self.is_checkmate(opponent) else "+"
            self.san_history.append(san)
        self.history.append((snapshot, move))
        key = self._position_key()
        self.position_counts[key] = self.position_counts.get(key, 0) + 1

    def undo_move(self) -> Optional[Move]:
        if not self.history:
            return None
        current_key = self._position_key()
        count = self.position_counts.get(current_key, 0) - 1
        if count > 0:
            self.position_counts[current_key] = count
        else:
            self.position_counts.pop(current_key, None)

        snapshot, move = self.history.pop()
        if self.san_history:
            self.san_history.pop()
        self._restore(snapshot)
        return move

    @property
    def last_move(self) -> Optional[Move]:
        return self.history[-1][1] if self.history else None

    def to_fen(self) -> str:
        ranks: list[str] = []
        for row in range(BOARD_SIZE):
            empty = 0
            rank = ""
            for col in range(BOARD_SIZE):
                piece = self.board[row][col]
                if piece is None:
                    empty += 1
                else:
                    if empty:
                        rank += str(empty)
                        empty = 0
                    rank += piece
            if empty:
                rank += str(empty)
            ranks.append(rank)

        placement = "/".join(ranks)
        castling = self.castling or "-"
        if self.ep_target is None:
            ep_square = "-"
        else:
            ep_square = f"{chr(ord('a') + self.ep_target[1])}{8 - self.ep_target[0]}"
        return (
            f"{placement} {self.turn} {castling} {ep_square} "
            f"{self.halfmove_clock} {self.fullmove_number}"
        )

    def _position_key(self) -> tuple:
        return (
            tuple(tuple(row) for row in self.board),
            self.turn,
            self.castling,
            self._effective_ep_target(),
        )

    def _effective_ep_target(self) -> Optional[tuple[int, int]]:
        if self.ep_target is None:
            return None

        target_row, target_col = self.ep_target
        pawn_row = target_row + (1 if self.turn == "w" else -1)
        if not 0 <= pawn_row < BOARD_SIZE:
            return None

        pawn = "P" if self.turn == "w" else "p"
        for pawn_col in (target_col - 1, target_col + 1):
            if not 0 <= pawn_col < BOARD_SIZE:
                continue
            if self.board[pawn_row][pawn_col] != pawn:
                continue
            if any(
                move.is_en_passant
                for move in self._legal_moves_for_piece(pawn_row, pawn_col)
            ):
                return self.ep_target
        return None

    @staticmethod
    def move_to_uci(move: Move) -> str:
        uci = (
            f"{chr(ord('a') + move.from_col)}{8 - move.from_row}"
            f"{chr(ord('a') + move.to_col)}{8 - move.to_row}"
        )
        if move.promotion:
            uci += move.promotion.lower()
        return uci

    def find_move_by_uci(self, uci: str) -> Optional[Move]:
        uci = uci.strip().lower()
        moves = self.all_legal_moves()
        for move in moves:
            if self.move_to_uci(move) == uci:
                return move
        if len(uci) == 4:
            promotions = [
                move for move in moves if self.move_to_uci(move)[:4] == uci
            ]
            if promotions:
                for move in promotions:
                    if move.promotion == "Q":
                        return move
                return promotions[0]
        return None

    def san_for_move(self, move: Move) -> str:
        piece = self.board[move.from_row][move.from_col]
        if piece is None:
            return ""
        san = self._san_base(move)
        snapshot = self._snapshot()
        self._apply_move(move)
        opponent = self.turn
        if self.in_check(opponent):
            san += "#" if self.is_checkmate(opponent) else "+"
        self._restore(snapshot)
        return san

    def result_tag(self) -> str:
        if self.is_checkmate():
            return "1-0" if self.turn == "b" else "0-1"
        if self.is_stalemate():
            return "1/2-1/2"
        if self.is_automatic_draw():
            return "1/2-1/2"
        return ""

    def _san_base(self, move: Move) -> str:
        piece = self.board[move.from_row][move.from_col]
        if piece is None:
            return ""
        piece_type = piece.upper()
        destination = f"{chr(ord('a') + move.to_col)}{8 - move.to_row}"
        is_capture = (
            self.board[move.to_row][move.to_col] is not None or move.is_en_passant
        )

        if move.is_castle:
            return "O-O" if move.to_col > move.from_col else "O-O-O"

        if piece_type == "P":
            if is_capture:
                san = f"{chr(ord('a') + move.from_col)}x{destination}"
            else:
                san = destination
            if move.promotion:
                san += f"={move.promotion.upper()}"
            return san

        disambiguation = ""
        if piece_type != "K":
            color = self.color_of(piece)
            ambiguous: list[tuple[int, int]] = []
            for row in range(BOARD_SIZE):
                for col in range(BOARD_SIZE):
                    if (row, col) == (move.from_row, move.from_col):
                        continue
                    other = self.board[row][col]
                    if (
                        other is None
                        or other.upper() != piece_type
                        or self.color_of(other) != color
                    ):
                        continue
                    destinations = {
                        (candidate.to_row, candidate.to_col)
                        for candidate in self._legal_moves_for_piece(row, col)
                    }
                    if (move.to_row, move.to_col) in destinations:
                        ambiguous.append((row, col))
            if ambiguous:
                same_file = any(col == move.from_col for _, col in ambiguous)
                same_rank = any(row == move.from_row for row, _ in ambiguous)
                if not same_file:
                    disambiguation = chr(ord("a") + move.from_col)
                elif not same_rank:
                    disambiguation = str(8 - move.from_row)
                else:
                    disambiguation = (
                        f"{chr(ord('a') + move.from_col)}{8 - move.from_row}"
                    )

        capture_mark = "x" if is_capture else ""
        return f"{piece_type}{disambiguation}{capture_mark}{destination}"

    def _snapshot(self) -> dict:
        return {
            "board": [row[:] for row in self.board],
            "turn": self.turn,
            "castling": self.castling,
            "ep_target": self.ep_target,
            "halfmove_clock": self.halfmove_clock,
            "fullmove_number": self.fullmove_number,
        }

    def _restore(self, snapshot: dict) -> None:
        self.board = [row[:] for row in snapshot["board"]]
        self.turn = snapshot["turn"]
        self.castling = snapshot["castling"]
        self.ep_target = snapshot["ep_target"]
        self.halfmove_clock = snapshot["halfmove_clock"]
        self.fullmove_number = snapshot["fullmove_number"]

    def _apply_move(self, move: Move) -> None:
        board = self.board
        piece = board[move.from_row][move.from_col]
        if piece is None:
            return

        color = self.color_of(piece)
        piece_type = piece.upper()
        captured = board[move.to_row][move.to_col]

        board[move.from_row][move.from_col] = None
        board[move.to_row][move.to_col] = piece

        if move.is_en_passant:
            captured = board[move.from_row][move.to_col]
            board[move.from_row][move.to_col] = None

        if move.is_castle:
            row = move.from_row
            rook_from_col, rook_to_col = (7, 5) if move.to_col > move.from_col else (0, 3)
            board[row][rook_to_col] = board[row][rook_from_col]
            board[row][rook_from_col] = None

        if piece_type == "P" and move.to_row in (0, BOARD_SIZE - 1):
            promotion = (move.promotion or "Q").upper()
            board[move.to_row][move.to_col] = promotion if color == "w" else promotion.lower()

        rights = set(self.castling)
        if piece_type == "K":
            rights -= {"K", "Q"} if color == "w" else {"k", "q"}
        elif piece_type == "R":
            self._remove_rook_right(rights, move.from_row, move.from_col)
        if captured is not None and captured.upper() == "R":
            self._remove_rook_right(rights, move.to_row, move.to_col)
        self.castling = "".join(char for char in "KQkq" if char in rights)

        if piece_type == "P" and abs(move.to_row - move.from_row) == 2:
            self.ep_target = ((move.from_row + move.to_row) // 2, move.from_col)
        else:
            self.ep_target = None

        if piece_type == "P" or captured is not None:
            self.halfmove_clock = 0
        else:
            self.halfmove_clock += 1

        if color == "b":
            self.fullmove_number += 1
        self.turn = self.opponent(color)

    @staticmethod
    def _remove_rook_right(rights: set[str], row: int, col: int) -> None:
        if (row, col) == (7, 0):
            rights.discard("Q")
        elif (row, col) == (7, 7):
            rights.discard("K")
        elif (row, col) == (0, 0):
            rights.discard("q")
        elif (row, col) == (0, 7):
            rights.discard("k")

    def _pseudo_legal_moves(self, row: int, col: int) -> list[Move]:
        board = self.board
        piece = board[row][col]
        if piece is None:
            return []

        color = self.color_of(piece)
        piece_type = piece.upper()
        moves: list[Move] = []

        def inside(r: int, c: int) -> bool:
            return 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE

        def add_target(r: int, c: int, **kwargs) -> bool:
            if not inside(r, c):
                return True
            target = board[r][c]
            if target is not None and self.color_of(target) == color:
                return True
            moves.append(Move(row, col, r, c, **kwargs))
            return target is None

        def add_pawn_target(r: int, c: int, **kwargs) -> None:
            if r in (0, BOARD_SIZE - 1):
                for promotion in ("Q", "R", "B", "N"):
                    moves.append(Move(row, col, r, c, promotion=promotion, **kwargs))
            else:
                moves.append(Move(row, col, r, c, **kwargs))

        if piece_type == "P":
            direction = -1 if color == "w" else 1
            start_row = 6 if color == "w" else 1
            next_row = row + direction

            if inside(next_row, col) and board[next_row][col] is None:
                add_pawn_target(next_row, col)
                double_row = row + 2 * direction
                if row == start_row and board[double_row][col] is None:
                    moves.append(Move(row, col, double_row, col))

            for dc in (-1, 1):
                next_col = col + dc
                if not inside(next_row, next_col):
                    continue
                target = board[next_row][next_col]
                if target is not None and self.color_of(target) != color:
                    add_pawn_target(next_row, next_col)
                elif target is None and self.ep_target == (next_row, next_col):
                    moves.append(
                        Move(row, col, next_row, next_col, is_en_passant=True)
                    )

        elif piece_type == "N":
            for dr, dc in KNIGHT_OFFSETS:
                add_target(row + dr, col + dc)

        elif piece_type in ("B", "R", "Q"):
            directions = []
            if piece_type in ("B", "Q"):
                directions.extend(DIAGONAL_DIRECTIONS)
            if piece_type in ("R", "Q"):
                directions.extend(ORTHOGONAL_DIRECTIONS)
            for dr, dc in directions:
                r, c = row + dr, col + dc
                while inside(r, c):
                    target = board[r][c]
                    if target is None:
                        moves.append(Move(row, col, r, c))
                    else:
                        if self.color_of(target) != color:
                            moves.append(Move(row, col, r, c))
                        break
                    r += dr
                    c += dc

        elif piece_type == "K":
            for dr, dc in KING_OFFSETS:
                add_target(row + dr, col + dc)

            enemy = self.opponent(color)
            if color == "w" and (row, col) == (7, 4):
                if (
                    "K" in self.castling
                    and board[7][5] is None
                    and board[7][6] is None
                    and board[7][7] == "R"
                    and not any(
                        self.is_square_attacked(7, c, enemy) for c in (4, 5, 6)
                    )
                ):
                    moves.append(Move(7, 4, 7, 6, is_castle=True))
                if (
                    "Q" in self.castling
                    and board[7][1] is None
                    and board[7][2] is None
                    and board[7][3] is None
                    and board[7][0] == "R"
                    and not any(
                        self.is_square_attacked(7, c, enemy) for c in (4, 3, 2)
                    )
                ):
                    moves.append(Move(7, 4, 7, 2, is_castle=True))
            elif color == "b" and (row, col) == (0, 4):
                if (
                    "k" in self.castling
                    and board[0][5] is None
                    and board[0][6] is None
                    and board[0][7] == "r"
                    and not any(
                        self.is_square_attacked(0, c, enemy) for c in (4, 5, 6)
                    )
                ):
                    moves.append(Move(0, 4, 0, 6, is_castle=True))
                if (
                    "q" in self.castling
                    and board[0][1] is None
                    and board[0][2] is None
                    and board[0][3] is None
                    and board[0][0] == "r"
                    and not any(
                        self.is_square_attacked(0, c, enemy) for c in (4, 3, 2)
                    )
                ):
                    moves.append(Move(0, 4, 0, 2, is_castle=True))

        return moves
