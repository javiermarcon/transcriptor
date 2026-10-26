from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from .models import RunPaths

Runner = Callable[..., subprocess.CompletedProcess[str]]

TranscriptionAudioSource = Literal["mp4_demux", "mixed_wav"]


def mp4_has_audio_stream(video: Path, runner: Runner = subprocess.run) -> bool:
    if not video.is_file() or video.stat().st_size <= 0:
        return False
    result = runner(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(video),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return False
    return "audio" in (result.stdout or "").casefold()


def demux_mp4_audio_to_wav(
    video: Path,
    output: Path,
    *,
    runner: Runner = subprocess.run,
) -> None:
    """Extrae la pista de audio del MP4 a PCM 16 kHz mono (formato Whisper)."""
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-vn",
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output),
    ]
    result = runner(command, check=False, text=True, capture_output=True)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
        detail = (result.stderr or result.stdout or "").strip() or f"code={result.returncode}"
        raise RuntimeError(f"No se pudo demuxear audio del MP4: {detail}")


def write_transcription_audio_meta(path: Path, meta: dict[str, Any]) -> None:
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_transcription_audio(
    paths: RunPaths,
    *,
    runner: Runner = subprocess.run,
) -> tuple[Path, TranscriptionAudioSource]:
    """Elige la fuente de audio para WhisperX.

    Preferí el audio demuxeado de ``reunion.mp4`` (misma línea de tiempo que el
    video) cuando hay pista de audio. Si no, ``reunion_mezclada.wav``.
    """
    if paths.video.is_file() and paths.video.stat().st_size > 0 and mp4_has_audio_stream(
        paths.video, runner=runner
    ):
        demux_mp4_audio_to_wav(paths.video, paths.transcription_audio, runner=runner)
        write_transcription_audio_meta(
            paths.transcription_audio_meta,
            {
                "source": "mp4_demux",
                "video": paths.video.name,
                "output": paths.transcription_audio.name,
                "reason": (
                    "WhisperX usa el audio del MP4 para alinear timestamps con el video "
                    "(evidencia visual y reproducción)."
                ),
            },
        )
        return paths.transcription_audio, "mp4_demux"

    if not paths.mixed_audio.is_file() or paths.mixed_audio.stat().st_size <= 0:
        raise FileNotFoundError(
            f"No hay audio para transcribir: falta pista en {paths.video.name} "
            f"y no existe {paths.mixed_audio.name}"
        )
    write_transcription_audio_meta(
        paths.transcription_audio_meta,
        {
            "source": "mixed_wav",
            "output": paths.mixed_audio.name,
            "reason": (
                "Sin audio usable en reunion.mp4; se usa reunion_mezclada.wav "
                "(comportamiento histórico)."
            ),
        },
    )
    return paths.mixed_audio, "mixed_wav"
