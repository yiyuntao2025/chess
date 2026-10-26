from __future__ import annotations

import re

from chess_engine import ChessGame
from game_tree import GameNode, GameTree


RESULT_TOKENS = {"1-0", "0-1", "1/2-1/2", "*"}
TAG_RE = re.compile(
    r'\[\s*([A-Za-z0-9_]+)\s+"((?:[^"\\]|\\.)*)"\s*\]'
)
TOKEN_RE = re.compile(r"\{[^}]*\}|;[^\n\r]*|%[^\n\r]*|\(|\)|\$\d+|[^\s(){};%]+")
SUFFIX_NAGS = {
    "!!": 3,
    "??": 4,
    "!?": 5,
    "?!": 6,
    "!": 1,
    "?": 2,
}


class PGNImportError(Exception):
    pass


def _unescape_tag(value: str) -> str:
    return re.sub(r'\\(["\\])', r"\1", value)


def _strip_variations(text: str) -> str:
    result: list[str] = []
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            if depth:
                depth -= 1
        elif depth == 0:
            result.append(char)
    return "".join(result)


def parse_pgn(pgn_text: str) -> GameTree:
    text = pgn_text.lstrip("\ufeff")
    headers: dict[str, str] = {}
    for match in TAG_RE.finditer(text):
        headers[match.group(1)] = _unescape_tag(match.group(2))

    movetext = TAG_RE.sub(" ", text)
    start_fen = headers.get("FEN") or headers.get("fen")
    try:
        tree = GameTree(start_fen or ChessGame.START_FEN)
    except (ValueError, IndexError) as exc:
        raise PGNImportError(f"PGN 中的 FEN 无效：{exc}") from exc
    tree.headers = headers

    current: GameNode = tree.root
    stack: list[GameNode] = []
    result = ""
    move_count = 0

    for raw in TOKEN_RE.findall(movetext):
        token = raw.strip()
        if not token:
            continue
        if token == "(":
            stack.append(current)
            current = current.parent or tree.root
            continue
        if token == ")":
            if not stack:
                raise PGNImportError("PGN 变例括号不匹配")
            current = stack.pop()
            continue
        if token.startswith("$"):
            try:
                nag = int(token[1:])
            except ValueError:
                continue
            if not current.is_root:
                current.nags.append(nag)
            continue
        if token.startswith("{") and token.endswith("}"):
            comment = token[1:-1].strip()
            if comment:
                if current.comment:
                    current.comment += " " + comment
                else:
                    current.comment = comment
            continue
        if token.startswith(";") or token.startswith("%"):
            comment = token[1:].strip()
            if comment:
                if current.comment:
                    current.comment += " " + comment
                else:
                    current.comment = comment
            continue
        if token in RESULT_TOKENS:
            result = token
            break

        token = re.sub(r"^\d+\.+", "", token)
        if not token or token == ".":
            continue

        suffix = ""
        for marker in ("!!", "??", "!?", "?!", "!", "?"):
            if token.endswith(marker):
                suffix = marker
                token = token[: -len(marker)]
                break
        token = token.strip()
        if not token or token.lower() in ("e.p.", "ep"):
            continue
        if token in RESULT_TOKENS:
            result = token
            break

        game = tree.build_game(current)
        move = game.find_move_by_san(token)
        if move is None:
            raise PGNImportError(
                f"第 {move_count + 1} 着无法识别或非法：{token}"
            )
        node = tree.append_move(
            current,
            move,
            game.san_for_move(move),
            game.turn,
        )
        if suffix:
            node.nags.append(SUFFIX_NAGS[suffix])
        current = node
        move_count += 1
        if move_count > 20000:
            raise PGNImportError("PGN 着法过多")

    if stack:
        raise PGNImportError("PGN 变例括号不匹配")

    tree.result = result or headers.get("Result", "*") or "*"
    return tree


def extract_moves(pgn_text: str) -> list[str]:
    if re.search(r'\[\s*(SetUp|FEN)\s+"', pgn_text, re.IGNORECASE):
        raise PGNImportError("暂不支持包含 FEN/SetUp 标签的 PGN 文件")

    text = re.sub(r"^\s*\[[^\n]*\]\s*$", " ", pgn_text, flags=re.MULTILINE)
    text = re.sub(r"\{[^}]*\}", " ", text, flags=re.DOTALL)
    text = re.sub(r";[^\n]*", " ", text)
    text = re.sub(r"%[^\n]*", " ", text)
    text = re.sub(r"\$\d+", " ", text)
    text = _strip_variations(text)

    moves: list[str] = []
    for raw_token in text.split():
        token = raw_token.lstrip("\ufeff")
        if token in RESULT_TOKENS:
            break

        token = re.sub(r"^\d+\.+", "", token)
        if not token or token in {".", "..", "..."}:
            continue

        token = token.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
        token = re.sub(r"e\.p\.", "", token, flags=re.IGNORECASE)
        token = re.sub(r"[!?]+$", "", token)
        if not token:
            continue
        if token in RESULT_TOKENS:
            break
        if token.startswith("[") or token.startswith("]"):
            continue
        moves.append(token)

    return moves
