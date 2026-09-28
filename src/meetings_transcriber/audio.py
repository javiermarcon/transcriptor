from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .models import RunPaths

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class Monitor:
    name: str
    connected: bool
    primary: bool
    width: int | None = None
    height: int | None = None
    offset_x: int | None = None
    offset_y: int | None = None


_GEOMETRY_RE = re.compile(r"(?P<width>\d+)x(?P<height>\d+)\+(?P<x>\d+)\+(?P<y>\d+)")


def command_output(command: list[str], runner: Runner = subprocess.run) -> str:
    result = runner(command, check=True, text=True, capture_output=True)
    return result.stdout.strip()


def resolve_audio_devices(settings: Settings, runner: Runner = subprocess.run) -> tuple[str, str]:
    sink = settings.sink or command_output(["pactl", "get-default-sink"], runner)
    microphone = settings.microphone or command_output(["pactl", "get-default-source"], runner)
    return sink, microphone


def parse_xrandr_output(output: str) -> list[Monitor]:
    monitors: list[Monitor] = []
    for line in output.splitlines():
        if not line or line[0].isspace():
            continue
        parts = line.split()
        if len(parts) < 2 or parts[1] not in {"connected", "disconnected"}:
            continue
        connected = parts[1] == "connected"
        geometry = _GEOMETRY_RE.search(line) if connected else None
        monitors.append(
            Monitor(
                name=parts[0],
                connected=connected,
                primary=connected and "primary" in parts[2:],
                width=int(geometry.group("width")) if geometry else None,
                height=int(geometry.group("height")) if geometry else None,
                offset_x=int(geometry.group("x")) if geometry else None,
                offset_y=int(geometry.group("y")) if geometry else None,
            )
        )
    return monitors


def query_monitors(runner: Runner = subprocess.run) -> list[Monitor]:
    try:
        output = command_output(["xrandr", "--query"], runner)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"No se pudo ejecutar xrandr --query: {exc}") from exc
    return parse_xrandr_output(output)


def resolve_monitor(requested: str, monitors: list[Monitor]) -> Monitor:
    if requested == "primary":
        monitor = next((item for item in monitors if item.connected and item.primary), None)
        if monitor is None:
            raise ValueError("xrandr no informa ningún monitor conectado como primary")
    else:
        monitor = next((item for item in monitors if item.name == requested), None)
        if monitor is None:
            raise ValueError(f"VIDEO_MONITOR especifica una salida inexistente: {requested}")
        if not monitor.connected:
            raise ValueError(f"La salida solicitada está desconectada: {requested}")

    if (
        monitor.width is None
        or monitor.height is None
        or monitor.offset_x is None
        or monitor.offset_y is None
    ):
        raise ValueError(f"Geometría inválida para la salida {monitor.name}")
    if monitor.width <= 0 or monitor.height <= 0:
        raise ValueError(f"Geometría inválida para la salida {monitor.name}")
    return monitor


def detect_video_codec(runner: Runner = subprocess.run) -> str:
    try:
        output = command_output(["ffmpeg", "-hide_banner", "-encoders"], runner)
    except (OSError, subprocess.CalledProcessError):
        return "libx264"
    return "h264_nvenc" if re.search(r"\bh264_nvenc\b", output) else "libx264"


def resolve_video_capture(
    settings: Settings,
    runner: Runner = subprocess.run,
    environ: dict[str, str] | os._Environ[str] = os.environ,
) -> tuple[str, Monitor, str]:
    display = environ.get("DISPLAY", "").strip()
    if not display:
        raise ValueError("RECORD_VIDEO=true pero DISPLAY no está definido")
    monitor = resolve_monitor(settings.video_monitor, query_monitors(runner))
    return display, monitor, detect_video_codec(runner)


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


def validate_video(video: Path, runner: Runner = subprocess.run) -> float:
    if not video.is_file() or video.stat().st_size <= 0:
        raise ValueError(f"Video inexistente o vacío: {video}")
    try:
        result = runner(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration:stream=codec_type", "-of", "json", str(video),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        probe = json.loads(result.stdout)
        duration = float(probe["format"]["duration"])
    except (OSError, subprocess.CalledProcessError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"ffprobe no pudo leer un MP4 válido en {video}: {exc}") from exc
    if duration <= 0:
        raise ValueError(f"Duración inválida para {video}: {duration}")
    stream_types = {stream.get("codec_type") for stream in probe.get("streams", [])}
    if "video" not in stream_types:
        raise ValueError(f"El MP4 no contiene un stream de video: {video}")
    if "audio" not in stream_types:
        raise ValueError(f"El MP4 no contiene un stream de audio: {video}")
    return duration


def build_ffmpeg_command(
    settings: Settings,
    paths: RunPaths,
    sink: str,
    microphone: str,
    *,
    display: str | None = None,
    monitor: Monitor | None = None,
    video_codec: str | None = None,
) -> list[str]:
    filters = (
        "[0:a]aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono,"
        "asplit=2[sistema_guardar][sistema_mezclar];"
        "[1:a]aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono,"
        "asplit=2[micro_guardar][micro_mezclar];"
        f"[sistema_mezclar]volume={settings.volume_system}[sistema_nivel];"
        f"[micro_mezclar]volume={settings.volume_microphone}[micro_nivel];"
        "[sistema_nivel][micro_nivel]amix=inputs=2:duration=longest:normalize=0,"
        "alimiter=limit=0.95"
    )
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-f", "pulse", "-thread_queue_size", "1024", "-i", f"{sink}.monitor",
        "-f", "pulse", "-thread_queue_size", "1024", "-i", microphone,
    ]
    if settings.record_video:
        if display is None or monitor is None or video_codec is None:
            raise ValueError("Faltan datos de captura para construir la grabación de video")
        command.extend([
            "-f", "x11grab", "-thread_queue_size", "1024",
            "-framerate", str(settings.video_fps),
            "-video_size", f"{monitor.width}x{monitor.height}",
            "-draw_mouse", "1", "-i", f"{display}+{monitor.offset_x},{monitor.offset_y}",
        ])
        filters += ",asplit=2[mezcla_wav][mezcla_video]"
        mixed_label = "[mezcla_wav]"
    else:
        filters += "[mezcla]"
        mixed_label = "[mezcla]"

    command.extend([
        "-filter_complex", filters,
        "-map", "[sistema_guardar]", "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", str(paths.system_audio),
        "-map", "[micro_guardar]", "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", str(paths.microphone_audio),
        "-map", mixed_label, "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", str(paths.mixed_audio),
    ])
    if settings.record_video:
        if video_codec is None:
            raise ValueError("Faltan datos de salida para construir la grabación de video")
        video_options = ["-c:v", video_codec, "-pix_fmt", "yuv420p"]
        if video_codec == "h264_nvenc":
            video_options.extend(["-preset", "p4", "-tune", "ll", "-cq", "28"])
        else:
            video_options.extend(["-preset", "ultrafast", "-crf", "28"])
        command.extend([
            "-map", "2:v:0", "-map", "[mezcla_video]", *video_options,
            "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(paths.video),
        ])
    return command


def record_meeting(settings: Settings, paths: RunPaths) -> int:
    sink, microphone = resolve_audio_devices(settings)
    if settings.record_video:
        display, monitor, codec = resolve_video_capture(settings)
        command = build_ffmpeg_command(
            settings,
            paths,
            sink,
            microphone,
            display=display,
            monitor=monitor,
            video_codec=codec,
        )
    else:
        command = build_ffmpeg_command(settings, paths, sink, microphone)
    process = subprocess.Popen(command)
    try:
        return_code = process.wait()
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT)
        return_code = process.wait()

    if return_code not in {0, 130, 255}:
        if settings.record_video:
            raise RuntimeError(
                f"FFmpeg no pudo completar la captura de audio y video; terminó con código "
                f"{return_code}"
            )
        raise RuntimeError(f"FFmpeg terminó con código inesperado {return_code}")
    for audio in (paths.system_audio, paths.microphone_audio, paths.mixed_audio):
        validate_audio(audio)
    if settings.record_video:
        validate_video(paths.video)
    return return_code
