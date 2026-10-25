from __future__ import annotations

import array
import math
import wave
from pathlib import Path


def _frames_to_samples(raw: bytes, sample_width: int) -> array.array:
    if sample_width == 1:
        # PCM unsigned 8-bit → centrar en 0.
        return array.array("h", (b - 128 for b in raw))
    if sample_width == 2:
        samples = array.array("h")
        samples.frombytes(raw)
        return samples
    if sample_width == 4:
        samples = array.array("i")
        samples.frombytes(raw)
        return samples
    raise ValueError(f"sample_width no soportado: {sample_width}")


def rms_for_interval(path: Path, start_s: float, end_s: float) -> float | None:
    """RMS normalizado [0, 1] del intervalo [start_s, end_s) en un WAV PCM.

    Devuelve None si el archivo no existe, no es legible o el intervalo es vacío.
    """
    if start_s < 0:
        start_s = 0.0
    if end_s <= start_s:
        return None
    if not path.is_file():
        return None
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            rate = handle.getframerate()
            n_frames = handle.getnframes()
            if channels < 1 or sample_width not in {1, 2, 4} or rate < 1 or n_frames < 1:
                return None
            start_frame = min(n_frames, max(0, int(start_s * rate)))
            end_frame = min(n_frames, max(start_frame, int(end_s * rate)))
            if end_frame <= start_frame:
                return None
            handle.setpos(start_frame)
            raw = handle.readframes(end_frame - start_frame)
            samples = _frames_to_samples(raw, sample_width)
    except (OSError, wave.Error, ValueError):
        return None
    if not samples:
        return None
    # Promedio por frame si es multi-canal: tomar todos los samples es válido para RMS.
    acc = 0.0
    for value in samples:
        acc += float(value) * float(value)
    rms = math.sqrt(acc / len(samples))
    max_amp = float((1 << (8 * sample_width - 1)) - 1)
    if max_amp <= 0:
        return None
    return min(1.0, rms / max_amp)
