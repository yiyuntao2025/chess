from __future__ import annotations

import datetime
from typing import Optional


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
