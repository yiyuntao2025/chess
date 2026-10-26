from __future__ import annotations

import math
import os
import struct
import sys
import tempfile
import wave
from pathlib import Path


SAMPLE_RATE = 22050
SOUND_VERSION = 1

SOUND_SPECS = {
    "move": [(520, 0.05, 0.22, 45), (400, 0.055, 0.16, 50)],
    "capture": [(210, 0.07, 0.28, 35), (150, 0.10, 0.24, 28)],
    "check": [(880, 0.06, 0.22, 20), (1100, 0.09, 0.20, 18)],
    "end": [(523, 0.12, 0.22, 12), (392, 0.20, 0.22, 9)],
    "chat": [(740, 0.06, 0.16, 24), (988, 0.10, 0.14, 18)],
}


def _write_wav(path: Path, spec: list[tuple[float, float, float, float]]) -> None:
    frames = bytearray()
    for frequency, duration, volume, decay in spec:
        count = int(SAMPLE_RATE * duration)
        for index in range(count):
            t = index / SAMPLE_RATE
            envelope = math.exp(-decay * t)
            sample = volume * 32767 * envelope * math.sin(
                2 * math.pi * frequency * t
            )
            frames.extend(struct.pack("<h", max(-32768, min(32767, int(sample)))))

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(bytes(frames))


class SoundPlayer:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and os.environ.get("CHESS_DISABLE_SOUND") != "1"
        self._winsound = None
        self._files: dict[str, str] = {}

        if sys.platform != "win32":
            return
        try:
            import winsound
        except ImportError:
            return

        self._winsound = winsound
        try:
            self._prepare_sounds()
        except OSError:
            self._winsound = None

    def _prepare_sounds(self) -> None:
        directory = Path(tempfile.gettempdir()) / "chess_pyqt_sounds"
        directory.mkdir(parents=True, exist_ok=True)
        for name, spec in SOUND_SPECS.items():
            path = directory / f"{name}_v{SOUND_VERSION}.wav"
            if not path.exists() or path.stat().st_size == 0:
                _write_wav(path, spec)
            self._files[name] = str(path)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def play(self, name: str) -> None:
        if not self.enabled or self._winsound is None:
            return
        path = self._files.get(name)
        if path is None:
            return
        try:
            self._winsound.PlaySound(
                path,
                self._winsound.SND_FILENAME
                | self._winsound.SND_ASYNC
                | self._winsound.SND_NODEFAULT,
            )
        except RuntimeError:
            self._winsound = None
