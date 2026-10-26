from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DEFAULT_MOVETIME_MS = 800
STARTUP_TIMEOUT = 10.0
_ENGINE_LOCK = threading.RLock()
_ENGINE: Optional["_EngineSession"] = None


@dataclass(frozen=True)
class AnalysisResult:
    bestmove: str
    score_cp: Optional[int] = None
    mate: Optional[int] = None


class _AnalysisCancelled(RuntimeError):
    pass


def find_stockfish() -> Optional[Path]:
    candidates: list[Path] = []

    env_path = os.environ.get("STOCKFISH_PATH")
    if env_path:
        candidates.append(Path(env_path.strip().strip('"')))

    candidates.append(BASE_DIR / "stockfish.exe")

    stockfish_dir = BASE_DIR / "stockfish"
    if stockfish_dir.is_dir():
        candidates.extend(sorted(stockfish_dir.glob("*.exe")))

    candidates.extend(sorted(BASE_DIR.glob("stockfish*.exe")))

    for name in ("stockfish", "stockfish.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def _parse_score(line: str) -> tuple[Optional[int], Optional[int]]:
    parts = line.split()
    for index, token in enumerate(parts):
        if token != "score" or index + 2 >= len(parts):
            continue
        kind = parts[index + 1]
        try:
            value = int(parts[index + 2])
        except ValueError:
            continue
        if kind == "cp":
            return value, None
        if kind == "mate":
            return None, value
    return None, None


class _EngineSession:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._output: Queue[Optional[str]] = Queue()
        self._send_lock = threading.Lock()
        self._closed = False

        try:
            self.process = subprocess.Popen(
                [str(path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=str(path.parent),
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise RuntimeError(f"无法启动 Stockfish：{exc}") from exc

        assert self.process.stdin is not None
        assert self.process.stdout is not None

        threading.Thread(target=self._read_output, daemon=True).start()

        try:
            self._send("uci")
            self.wait_for("uciok", STARTUP_TIMEOUT)
            self._send("isready")
            self.wait_for("readyok", STARTUP_TIMEOUT)
        except Exception:
            self.close()
            raise

    def _read_output(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self._output.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._output.put(None)

    def _send(self, command: str) -> None:
        with self._send_lock:
            if self._closed:
                raise RuntimeError("Stockfish 进程已关闭")
            assert self.process.stdin is not None
            try:
                self.process.stdin.write(command + "\n")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise RuntimeError("Stockfish 进程已退出") from exc

    def wait_for(self, prefix: str, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Stockfish 响应超时")
            try:
                line = self._output.get(timeout=remaining)
            except Empty as exc:
                raise RuntimeError("Stockfish 响应超时") from exc
            if line is None:
                raise RuntimeError("Stockfish 进程已退出")
            if line.startswith(prefix):
                return line

    @staticmethod
    def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise _AnalysisCancelled("分析已取消")

    def search(
        self,
        fen: Optional[str],
        moves: Optional[list[str]],
        movetime_ms: int,
        skill_level: Optional[int],
        cancel_event: Optional[threading.Event],
    ) -> AnalysisResult:
        self._check_cancel(cancel_event)

        level = 20 if skill_level is None else max(0, min(20, int(skill_level)))
        self._send(f"setoption name Skill Level value {level}")
        self._send("isready")
        self.wait_for("readyok", STARTUP_TIMEOUT)

        self._check_cancel(cancel_event)

        if moves is not None:
            if moves:
                self._send("position startpos moves " + " ".join(moves))
            else:
                self._send("position startpos")
        else:
            self._send(f"position fen {fen}")

        search_ms = max(50, int(movetime_ms))
        self._send(f"go movetime {search_ms}")

        bestmove: Optional[str] = None
        score_cp: Optional[int] = None
        mate: Optional[int] = None
        deadline = time.monotonic() + max(10.0, search_ms / 1000 + 15.0)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Stockfish 思考超时")
            try:
                line = self._output.get(timeout=remaining)
            except Empty as exc:
                raise RuntimeError("Stockfish 思考超时") from exc
            if line is None:
                raise RuntimeError("Stockfish 进程已退出")

            if line.startswith("info"):
                line_cp, line_mate = _parse_score(line)
                if line_cp is not None:
                    score_cp, mate = line_cp, None
                elif line_mate is not None:
                    score_cp, mate = None, line_mate

            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) >= 2:
                    bestmove = parts[1]
                break

        if not bestmove or bestmove == "(none)":
            raise RuntimeError("Stockfish 没有返回有效着法")
        return AnalysisResult(bestmove=bestmove, score_cp=score_cp, mate=mate)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            assert self.process.stdin is not None
            self.process.stdin.write("quit\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError, AssertionError):
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        try:
            assert self.process.stdin is not None
            self.process.stdin.close()
        except (OSError, ValueError, AssertionError):
            pass


def _get_session(path: Path) -> _EngineSession:
    global _ENGINE
    if _ENGINE is not None and _ENGINE.path == path:
        return _ENGINE
    if _ENGINE is not None:
        _ENGINE.close()
        _ENGINE = None
    session = _EngineSession(path)
    _ENGINE = session
    return session


def _close_engine() -> None:
    global _ENGINE
    if not _ENGINE_LOCK.acquire(timeout=3.0):
        return
    try:
        if _ENGINE is not None:
            _ENGINE.close()
            _ENGINE = None
    finally:
        _ENGINE_LOCK.release()


atexit.register(_close_engine)


def _run_uci(
    fen: Optional[str],
    moves: Optional[list[str]],
    movetime_ms: int,
    skill_level: Optional[int],
    cancel_event: Optional[threading.Event] = None,
) -> AnalysisResult:
    path = find_stockfish()
    if path is None:
        raise RuntimeError(
            "未找到 Stockfish 引擎，请将 stockfish.exe 放入 stockfish/ 目录，"
            "或设置 STOCKFISH_PATH 环境变量"
        )
    if fen is None and moves is None:
        raise RuntimeError("缺少当前局面")
    if cancel_event is not None and cancel_event.is_set():
        raise _AnalysisCancelled("分析已取消")

    global _ENGINE
    with _ENGINE_LOCK:
        if cancel_event is not None and cancel_event.is_set():
            raise _AnalysisCancelled("分析已取消")
        session = _get_session(path)
        try:
            return session.search(
                fen, moves, movetime_ms, skill_level, cancel_event
            )
        except _AnalysisCancelled:
            raise
        except Exception:
            session.close()
            if _ENGINE is session:
                _ENGINE = None
            raise


def ask_stockfish_for_move(
    fen: Optional[str] = None,
    moves: Optional[list[str]] = None,
    movetime_ms: int = DEFAULT_MOVETIME_MS,
    skill_level: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    return _run_uci(
        fen, moves, movetime_ms, skill_level, cancel_event
    ).bestmove


def analyse_position(
    fen: Optional[str] = None,
    moves: Optional[list[str]] = None,
    movetime_ms: int = 400,
    cancel_event: Optional[threading.Event] = None,
) -> AnalysisResult:
    return _run_uci(fen, moves, movetime_ms, None, cancel_event)
