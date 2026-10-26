from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QStandardPaths


STATE_VERSION = 1


def state_path() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    directory = Path(base) if base else Path.home() / ".chess"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "saved_game.json"


def load_state() -> Optional[dict]:
    path = state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return None
    return data


def save_state(data: dict) -> bool:
    path = state_path()
    temporary = path.with_suffix(".tmp")
    payload = {"version": STATE_VERSION, **data}
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        return False
    return True


def clear_state() -> None:
    path = state_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
