from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
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


@dataclass(frozen=True)
class VideoTarget:
    """Destino de captura de video.

    `source`: `monitor` o `window`.
    `backend`: `x11` (x11grab) o `portal` (PipeWire vía xdg-desktop-portal).
    """

    source: str
    display: str
    width: int
    height: int
    offset_x: int = 0
    offset_y: int = 0
    window_id: int | None = None
    label: str = ""
    backend: str = "x11"
    pipewire_node_id: int | None = None


_GEOMETRY_RE = re.compile(r"(?P<width>\d+)x(?P<height>\d+)\+(?P<x>\d+)\+(?P<y>\d+)")
_ACCEPTED_FFMPEG_CODES = frozenset({0, 130, 255})


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


def nvenc_usable(runner: Runner = subprocess.run) -> bool:
    """Comprueba si h264_nvenc abre de verdad, no solo si FFmpeg lo lista."""
    try:
        result = runner(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=64x64:d=0.1",
                "-frames:v",
                "1",
                "-c:v",
                "h264_nvenc",
                "-f",
                "null",
                "-",
            ],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def detect_video_codec(runner: Runner = subprocess.run) -> str:
    try:
        output = command_output(["ffmpeg", "-hide_banner", "-encoders"], runner)
    except (OSError, subprocess.CalledProcessError):
        return "libx264"
    if not re.search(r"\bh264_nvenc\b", output):
        return "libx264"
    return "h264_nvenc" if nvenc_usable(runner) else "libx264"


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


def resolve_monitor_video_target(
    settings: Settings,
    runner: Runner = subprocess.run,
    environ: dict[str, str] | os._Environ[str] = os.environ,
) -> tuple[VideoTarget, str]:
    display, monitor, codec = resolve_video_capture(settings, runner, environ)
    assert monitor.width is not None and monitor.height is not None
    assert monitor.offset_x is not None and monitor.offset_y is not None
    target = VideoTarget(
        source="monitor",
        display=display,
        width=monitor.width,
        height=monitor.height,
        offset_x=monitor.offset_x,
        offset_y=monitor.offset_y,
        label=f"monitor:{monitor.name}",
        backend="x11",
    )
    return target, codec


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


def _resolve_video_inputs(
    *,
    display: str | None,
    monitor: Monitor | None,
    video_target: VideoTarget | None,
    video_codec: str | None,
) -> tuple[VideoTarget, str]:
    if video_target is not None:
        if video_codec is None:
            raise ValueError("Faltan datos de captura para construir la grabación de video")
        if video_target.backend == "portal":
            if video_target.pipewire_node_id is None:
                raise ValueError("VideoTarget portal requiere pipewire_node_id")
        elif video_target.source == "window" and video_target.window_id is None:
            raise ValueError("VideoTarget window requiere window_id")
        if video_target.width <= 0 or video_target.height <= 0:
            raise ValueError("Geometría de captura de video inválida")
        return video_target, video_codec
    if display is None or monitor is None or video_codec is None:
        raise ValueError("Faltan datos de captura para construir la grabación de video")
    if (
        monitor.width is None
        or monitor.height is None
        or monitor.offset_x is None
        or monitor.offset_y is None
    ):
        raise ValueError("Geometría de monitor inválida para la captura de video")
    return (
        VideoTarget(
            source="monitor",
            display=display,
            width=monitor.width,
            height=monitor.height,
            offset_x=monitor.offset_x,
            offset_y=monitor.offset_y,
            label=f"monitor:{monitor.name}",
            backend="x11",
        ),
        video_codec,
    )


def build_ffmpeg_command(
    settings: Settings,
    paths: RunPaths,
    sink: str,
    microphone: str,
    *,
    display: str | None = None,
    monitor: Monitor | None = None,
    video_codec: str | None = None,
    video_target: VideoTarget | None = None,
    portal_video_path: str | None = None,
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
    target: VideoTarget | None = None
    codec: str | None = video_codec
    if settings.record_video:
        target, codec = _resolve_video_inputs(
            display=display,
            monitor=monitor,
            video_target=video_target,
            video_codec=video_codec,
        )
        if target.backend == "portal":
            if not portal_video_path:
                raise ValueError("Captura portal requiere portal_video_path (fifo/fd)")
            command.extend([
                "-f", "rawvideo",
                "-pixel_format", "yuv420p",
                "-video_size", f"{target.width}x{target.height}",
                "-framerate", str(settings.video_fps),
                "-thread_queue_size", "1024",
                "-i", portal_video_path,
            ])
        else:
            command.extend([
                "-f", "x11grab", "-thread_queue_size", "1024",
                "-framerate", str(settings.video_fps),
                "-video_size", f"{target.width}x{target.height}",
                "-draw_mouse", "1",
            ])
            if target.source == "window":
                assert target.window_id is not None
                command.extend(["-window_id", str(target.window_id), "-i", target.display])
            else:
                command.extend([
                    "-i",
                    f"{target.display}+{target.offset_x},{target.offset_y}",
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
        if codec is None:
            raise ValueError("Faltan datos de salida para construir la grabación de video")
        video_options = ["-c:v", codec, "-pix_fmt", "yuv420p"]
        if codec == "h264_nvenc":
            video_options.extend(["-preset", "p4", "-tune", "ll", "-cq", "28"])
        else:
            video_options.extend(["-preset", "ultrafast", "-crf", "28"])
        command.extend([
            "-map", "2:v:0", "-map", "[mezcla_video]", *video_options,
            "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(paths.video),
        ])
    return command


class RecordingSession:
    """Sesión de grabación reutilizable por CLI y Native Messaging."""

    def __init__(
        self,
        settings: Settings,
        paths: RunPaths,
        *,
        video_target: VideoTarget | None = None,
        video_codec: str | None = None,
        portal_handle: object | None = None,
    ) -> None:
        self.settings = settings
        self.paths = paths
        self.video_target = video_target
        self.video_codec = video_codec
        self._portal_handle = portal_handle
        self._process: subprocess.Popen[bytes] | None = None
        self._gst_process: subprocess.Popen[bytes] | None = None
        self._return_code: int | None = None
        self._portal_read_fd: int | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def return_code(self) -> int | None:
        return self._return_code

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("La sesión de grabación ya fue iniciada")
        sink, microphone = resolve_audio_devices(self.settings)
        if self.settings.record_video:
            target = self.video_target
            codec = self.video_codec
            if target is None or codec is None:
                target, codec = self._default_video_target()
                self.video_target = target
                self.video_codec = codec
            # stderr: stdout queda libre para Native Messaging / pipes.
            print(f"Códec de video: {codec}", file=sys.stderr, flush=True)
            print(
                f"Captura de video: {target.backend}/{target.source} "
                f"({target.label or target.source})",
                file=sys.stderr,
                flush=True,
            )
            if target.backend == "portal":
                self._start_portal_pipeline(sink, microphone, target, codec)
                return
            command = build_ffmpeg_command(
                self.settings,
                self.paths,
                sink,
                microphone,
                video_target=target,
                video_codec=codec,
            )
        else:
            command = build_ffmpeg_command(self.settings, self.paths, sink, microphone)
        self._process = subprocess.Popen(command)

    def _default_video_target(self) -> tuple[VideoTarget, str]:
        from .wayland_capture import (
            ensure_gst_pipewire_available,
            is_wayland_session,
            open_portal_capture,
            video_target_from_portal,
        )

        if is_wayland_session():
            print(
                "Wayland detectado: se abrirá el selector del portal para el monitor.",
                file=sys.stderr,
                flush=True,
            )
            ensure_gst_pipewire_available()
            handle = open_portal_capture("monitor")
            self._portal_handle = handle
            return video_target_from_portal(handle), detect_video_codec()
        return resolve_monitor_video_target(self.settings)

    def _start_portal_pipeline(
        self,
        sink: str,
        microphone: str,
        target: VideoTarget,
        codec: str,
    ) -> None:
        from .wayland_capture import build_pipewire_gst_command, ensure_gst_pipewire_available

        ensure_gst_pipewire_available()
        assert target.pipewire_node_id is not None
        read_fd, write_fd = os.pipe()
        self._portal_read_fd = read_fd
        gst_cmd = build_pipewire_gst_command(
            node_id=target.pipewire_node_id,
            width=target.width,
            height=target.height,
            fps=self.settings.video_fps,
        )
        self._gst_process = subprocess.Popen(
            gst_cmd,
            stdout=write_fd,
            stderr=subprocess.DEVNULL,
        )
        os.close(write_fd)
        portal_path = f"/dev/fd/{read_fd}"
        command = build_ffmpeg_command(
            self.settings,
            self.paths,
            sink,
            microphone,
            video_target=target,
            video_codec=codec,
            portal_video_path=portal_path,
        )
        self._process = subprocess.Popen(command, pass_fds=(read_fd,))
        os.close(read_fd)
        self._portal_read_fd = None

    def wait(self) -> int:
        if self._process is None:
            raise RuntimeError("La sesión de grabación no está iniciada")
        try:
            self._return_code = self._process.wait()
        except KeyboardInterrupt:
            self._return_code = self.stop()
        finally:
            self._cleanup_helpers()
        return self._return_code

    def stop(self) -> int:
        if self._process is None:
            raise RuntimeError("La sesión de grabación no está iniciada")
        if self._process.poll() is None:
            self._process.send_signal(signal.SIGINT)
            self._return_code = self._process.wait()
        elif self._return_code is None:
            self._return_code = self._process.returncode
        self._cleanup_helpers()
        return self._return_code

    def _cleanup_helpers(self) -> None:
        if self._gst_process is not None and self._gst_process.poll() is None:
            self._gst_process.send_signal(signal.SIGINT)
            try:
                self._gst_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._gst_process.kill()
                self._gst_process.wait(timeout=5)
        self._gst_process = None
        handle = self._portal_handle
        self._portal_handle = None
        if handle is not None:
            close = getattr(handle, "close", None)
            if callable(close):
                close()
        if self._portal_read_fd is not None:
            try:
                os.close(self._portal_read_fd)
            except OSError:
                pass
            self._portal_read_fd = None

    def validate_outputs(self, return_code: int | None = None) -> int:
        code = self._return_code if return_code is None else return_code
        if code is None:
            raise RuntimeError("No hay código de salida de FFmpeg para validar")
        if code not in _ACCEPTED_FFMPEG_CODES:
            if self.settings.record_video:
                raise RuntimeError(
                    "FFmpeg no pudo completar la captura de audio y video; terminó con código "
                    f"{code}"
                )
            raise RuntimeError(f"FFmpeg terminó con código inesperado {code}")
        for audio in (self.paths.system_audio, self.paths.microphone_audio, self.paths.mixed_audio):
            validate_audio(audio)
        if self.settings.record_video:
            validate_video(self.paths.video)
        return code


def record_meeting(settings: Settings, paths: RunPaths) -> int:
    session = RecordingSession(settings, paths)
    session.start()
    return_code = session.wait()
    return session.validate_outputs(return_code)
