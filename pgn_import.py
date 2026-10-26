from __future__ import annotations

import re


RESULT_TOKENS = {"1-0", "0-1", "1/2-1/2", "*"}


class PGNImportError(Exception):
    pass


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
