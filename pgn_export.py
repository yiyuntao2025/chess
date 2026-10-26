from __future__ import annotations

import datetime
from typing import Optional

from chess_engine import ChessGame
from game_tree import GameNode, GameTree


def _escape_header(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _wrap_tokens(tokens: list[str], width: int = 80) -> list[str]:
    lines: list[str] = []
    current = ""
    for token in tokens:
        if current and len(current) + 1 + len(token) > width:
            lines.append(current)
            current = token
        else:
            current = token if not current else f"{current} {token}"
    if current:
        lines.append(current)
    return lines


def _move_token(tree: GameTree, node: GameNode, force_number: bool) -> str:
    number = tree.move_number(node)
    if node.color == "w":
        prefix = f"{number}. "
    elif force_number:
        prefix = f"{number}... "
    else:
        prefix = ""
    text = f"{prefix}{node.san}"
    for nag in node.nags:
        text += f" ${nag}"
    if node.comment:
        comment = node.comment.replace("}", "]").replace("{", "[")
        text += f" {{{comment}}}"
    return text


def _render_move(
    tree: GameTree, node: GameNode, force_number: bool
) -> list[str]:
    tokens = [_move_token(tree, node, force_number)]
    tokens.extend(_render_children(tree, node, False))
    return tokens


def _render_children(
    tree: GameTree, parent: GameNode, force_first: bool
) -> list[str]:
    if not parent.children:
        return []
    tokens: list[str] = []
    main = parent.children[0]
    tokens.append(_move_token(tree, main, force_first))
    for variation in parent.children[1:]:
        tokens.append("(")
        tokens.extend(_render_move(tree, variation, True))
        tokens.append(")")
    tokens.extend(_render_children(tree, main, False))
    return tokens


def build_pgn_tree(
    tree: GameTree,
    result: str = "",
    white: str = "Player",
    black: str = "Player 2",
    date: Optional[datetime.date] = None,
    event: str = "Casual Game",
    site: str = "Local",
    extra_headers: Optional[dict[str, str]] = None,
) -> str:
    result_tag = result or tree.result or "*"
    date_text = (date or datetime.date.today()).strftime("%Y.%m.%d")

    merged: dict[str, str] = dict(tree.headers)
    merged.setdefault("Event", event)
    merged.setdefault("Site", site)
    merged.setdefault("Date", date_text)
    merged.setdefault("Round", "-")
    merged["White"] = white
    merged["Black"] = black
    merged["Result"] = result_tag
    if extra_headers:
        merged.update(extra_headers)

    if tree.start_fen != ChessGame.START_FEN:
        merged["SetUp"] = "1"
        merged["FEN"] = tree.start_fen
    else:
        merged.pop("SetUp", None)
        merged.pop("FEN", None)

    order = [
        "Event",
        "Site",
        "Date",
        "Round",
        "White",
        "Black",
        "Result",
        "SetUp",
        "FEN",
    ]
    lines: list[str] = []
    for key in order:
        value = merged.pop(key, None)
        if value is not None:
            lines.append(f'[{key} "{_escape_header(str(value))}"]')
    for key in sorted(merged):
        lines.append(f'[{key} "{_escape_header(str(merged[key]))}"]')
    lines.append("")

    tokens = _render_children(tree, tree.root, True)
    tokens.append(result_tag)
    lines.extend(_wrap_tokens(tokens))
    return "\n".join(lines) + "\n"


def build_pgn(
    san_history: list[str],
    result: str = "",
    white: str = "Player",
    black: str = "Player 2",
    date: Optional[datetime.date] = None,
    event: str = "Casual Game",
    site: str = "Local",
) -> str:
    result_tag = result or "*"
    date_text = (date or datetime.date.today()).strftime("%Y.%m.%d")

    headers = [
        ("Event", event),
        ("Site", site),
        ("Date", date_text),
        ("Round", "-"),
        ("White", white),
        ("Black", black),
        ("Result", result_tag),
    ]
    lines = [
        f'[{key} "{_escape_header(str(value))}"]' for key, value in headers
    ]
    lines.append("")

    tokens: list[str] = []
    for index in range(0, len(san_history), 2):
        number = index // 2 + 1
        tokens.append(f"{number}. {san_history[index]}")
        if index + 1 < len(san_history):
            tokens.append(san_history[index + 1])
    tokens.append(result_tag)

    lines.extend(_wrap_tokens(tokens))
    return "\n".join(lines) + "\n"
