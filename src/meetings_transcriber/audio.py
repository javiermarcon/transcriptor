from __future__ import annotations

import signal
import subprocess
from collections.abc import Callable
from pathlib import Path

from .config import Settings
from .models import RunPaths

Runner = Callable[..., subprocess.CompletedProcess[str]]


def command_output(command: list[str], runner: Runner = subprocess.run) -> str:
    result = runner(command, check=True, text=True, capture_output=True)
    return result.stdout.strip()


def resolve_audio_devices(settings: Settings, runner: Runner = subprocess.run) -> tuple[str, str]:
    sink = settings.sink or command_output(["pactl", "get-default-sink"], runner)
    microphone = settings.microphone or command_output(["pactl", "get-default-source"], runner)
    return sink, microphone


def ffprobe_duration(audio: Path, runner: Runner = subprocess.run) -> float:
    result = runner(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(audio),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    duration = float(result.stdout.strip())
    if duration <= 0:
        raise ValueError(f"Duración inválida para {audio}: {duration}")
    return duration


def validate_audio(audio: Path, runner: Runner = subprocess.run) -> float:
    if not audio.is_file() or audio.stat().st_size <= 0:
        raise ValueError(f"Audio inexistente o vacío: {audio}")
    return ffprobe_duration(audio, runner)


def build_ffmpeg_command(settings: Settings, paths: RunPaths, sink: str, microphone: str) -> list[str]:
    filters = (
        "[0:a]aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono,"
        "asplit=2[sistema_guardar][sistema_mezclar];"
        "[1:a]aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono,"
        "asplit=2[micro_guardar][micro_mezclar];"
        f"[sistema_mezclar]volume={settings.volume_system}[sistema_nivel];"
        f"[micro_mezclar]volume={settings.volume_microphone}[micro_nivel];"
        "[sistema_nivel][micro_nivel]amix=inputs=2:duration=longest:normalize=0,"
        "alimiter=limit=0.95[mezcla]"
    )
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-f", "pulse", "-thread_queue_size", "1024", "-i", f"{sink}.monitor",
        "-f", "pulse", "-thread_queue_size", "1024", "-i", microphone,
        "-filter_complex", filters,
        "-map", "[sistema_guardar]", "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", str(paths.system_audio),
        "-map", "[micro_guardar]", "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", str(paths.microphone_audio),
        "-map", "[mezcla]", "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", str(paths.mixed_audio),
    ]


def record_meeting(settings: Settings, paths: RunPaths) -> int:
    sink, microphone = resolve_audio_devices(settings)
    process = subprocess.Popen(build_ffmpeg_command(settings, paths, sink, microphone))
    try:
        return_code = process.wait()
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)
        return_code = process.wait()

    if return_code not in {0, 130, 255}:
        raise RuntimeError(f"FFmpeg terminó con código inesperado {return_code}")
    for audio in (paths.system_audio, paths.microphone_audio, paths.mixed_audio):
        validate_audio(audio)
    return return_code
