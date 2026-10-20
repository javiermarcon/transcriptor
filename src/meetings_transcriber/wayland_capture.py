from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .audio import VideoTarget
from .portal_screencast import PortalScreenCastError, SourceKind

Runner = Callable[..., subprocess.CompletedProcess[str]]


def session_type(environ: dict[str, str] | os._Environ[str] = os.environ) -> str:
    raw = environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if raw:
        return raw
    if environ.get("WAYLAND_DISPLAY", "").strip():
        return "wayland"
    if environ.get("DISPLAY", "").strip():
        return "x11"
    return "unknown"


def is_wayland_session(environ: dict[str, str] | os._Environ[str] = os.environ) -> bool:
    return session_type(environ) == "wayland" or bool(environ.get("WAYLAND_DISPLAY", "").strip())


def system_python3() -> str:
    override = os.environ.get("NATIVE_HOST_SYSTEM_PYTHON", "").strip()
    if override and os.path.isfile(override) and os.access(override, os.X_OK):
        return override
    candidate = "/usr/bin/python3"
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    which = shutil.which("python3")
    if which:
        return which
    raise PortalScreenCastError(
        "WINDOW_CAPTURE_UNAVAILABLE",
        "No se encontró /usr/bin/python3 para el portal ScreenCast (PyGObject).",
    )


def project_src_dir() -> Path:
    return Path(__file__).resolve().parents[1]


@dataclass
class PortalCaptureHandle:
    """Proceso worker que mantiene la sesión del portal + metadatos del stream."""

    kind: SourceKind
    node_id: int
    width: int
    height: int
    session_handle: str
    process: subprocess.Popen[str]

    def close(self) -> None:
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def open_portal_capture(
    kind: SourceKind,
    *,
    environ: dict[str, str] | os._Environ[str] | None = None,
    python_bin: str | None = None,
) -> PortalCaptureHandle:
    env = dict(environ if environ is not None else os.environ)
    src = str(project_src_dir())
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not existing else f"{src}:{existing}"
    python = python_bin or system_python3()
    process = subprocess.Popen(
        [python, "-m", "meetings_transcriber.portal_screencast", kind],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        # DEVNULL: si stderr es PIPE y nadie lo lee, el worker se bloquea
        # al llenar el buffer y el host NM deja de responder.
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    assert process.stdout is not None
    try:
        line = process.stdout.readline()
        if not line.strip():
            process.wait(timeout=5)
            raise PortalScreenCastError(
                "WINDOW_CAPTURE_UNAVAILABLE",
                "El worker del portal ScreenCast no devolvió datos.",
            )
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        process.kill()
        raise PortalScreenCastError(
            "WINDOW_CAPTURE_UNAVAILABLE",
            f"Respuesta inválida del portal ScreenCast: {exc}",
        ) from exc
    except Exception:
        process.kill()
        raise

    if not payload.get("ok"):
        process.wait(timeout=5)
        raise PortalScreenCastError(
            str(payload.get("code") or "WINDOW_CAPTURE_UNAVAILABLE"),
            str(payload.get("message") or "Falló el portal ScreenCast."),
        )

    return PortalCaptureHandle(
        kind=kind,
        node_id=int(payload["node_id"]),
        width=int(payload["width"]),
        height=int(payload["height"]),
        session_handle=str(payload.get("session_handle") or ""),
        process=process,
    )


def video_target_from_portal(handle: PortalCaptureHandle) -> VideoTarget:
    # yuv420p exige dimensiones pares.
    width = handle.width - (handle.width % 2)
    height = handle.height - (handle.height % 2)
    if width < 2 or height < 2:
        raise PortalScreenCastError(
            "WINDOW_CAPTURE_UNAVAILABLE",
            f"Tamaño de stream portal inválido: {handle.width}x{handle.height}",
        )
    return VideoTarget(
        source=handle.kind,
        display="",
        width=width,
        height=height,
        backend="portal",
        pipewire_node_id=handle.node_id,
        label=f"portal:{handle.kind}:node={handle.node_id}",
    )


def build_pipewire_gst_command(
    *,
    node_id: int,
    width: int,
    height: int,
    fps: int,
) -> list[str]:
    if shutil.which("gst-launch-1.0") is None:
        raise PortalScreenCastError(
            "WINDOW_CAPTURE_UNAVAILABLE",
            "Falta gst-launch-1.0 (GStreamer) para capturar PipeWire en Wayland.",
        )
    # Salida raw I420 por stdout para que FFmpeg la lea como rawvideo.
    return [
        "gst-launch-1.0",
        "-q",
        "pipewiresrc",
        f"path={node_id}",
        "do-timestamp=true",
        "!",
        "videoconvert",
        "!",
        "videoscale",
        "!",
        f"video/x-raw,format=I420,width={width},height={height}",
        "!",
        "videorate",
        "!",
        f"video/x-raw,framerate={fps}/1",
        "!",
        "fdsink",
        "fd=1",
    ]


def ensure_gst_pipewire_available(runner: Runner = subprocess.run) -> None:
    result = runner(
        ["gst-inspect-1.0", "pipewiresrc"],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise PortalScreenCastError(
            "WINDOW_CAPTURE_UNAVAILABLE",
            "GStreamer no tiene el elemento pipewiresrc (paquete gstreamer1.0-pipewire).",
        )