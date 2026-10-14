from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from .audio import VideoTarget

Runner = Callable[..., subprocess.CompletedProcess[str]]

_FIREFOX_CLASS_RE = re.compile(r"\b(firefox|navigator|mozilla)\b", re.IGNORECASE)
_WINDOW_LINE_RE = re.compile(
    r"^\s+(0x[0-9a-fA-F]+)\s+\"(?P<title>[^\"]*)\".*?"
    r"(?P<width>\d+)x(?P<height>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)"
)
_MIN_WIDTH = 200
_MIN_HEIGHT = 200


class WindowCaptureError(RuntimeError):
    """Error al resolver o capturar una ventana X11."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class X11Window:
    window_id: int
    title: str
    width: int
    height: int
    offset_x: int
    offset_y: int
    wm_class: str


def is_meet_url(url: str) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname == "meet.google.com"


def _parse_window_id(raw: str) -> int:
    value = raw.strip().lower()
    if value.startswith("0x"):
        return int(value, 16)
    return int(value)


def _run_checked(command: list[str], runner: Runner) -> str:
    result = runner(command, check=False, text=True, capture_output=True)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise WindowCaptureError(
            "WINDOW_CAPTURE_UNAVAILABLE",
            f"No se pudo ejecutar {' '.join(command[:2])}: {stderr or result.returncode}",
        )
    return result.stdout or ""


def _parse_wm_class(prop_output: str) -> str:
    for line in prop_output.splitlines():
        if "WM_CLASS" in line and "=" in line:
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _parse_net_wm_name(prop_output: str) -> str | None:
    for line in prop_output.splitlines():
        if "_NET_WM_NAME" in line and "=" in line:
            value = line.split("=", 1)[1].strip()
            if value.startswith("(invalid"):
                return None
            return value.strip().strip('"')
    return None


def _is_hidden(prop_output: str) -> bool:
    return "_NET_WM_STATE_HIDDEN" in prop_output


def list_candidate_windows(
    runner: Runner = subprocess.run,
) -> list[X11Window]:
    tree = _run_checked(["xwininfo", "-root", "-tree"], runner)
    candidates: list[X11Window] = []
    for line in tree.splitlines():
        match = _WINDOW_LINE_RE.search(line)
        if not match:
            continue
        width = int(match.group("width"))
        height = int(match.group("height"))
        if width < _MIN_WIDTH or height < _MIN_HEIGHT:
            continue
        window_id = _parse_window_id(match.group(1))
        title_from_tree = match.group("title").strip()
        props = _run_checked(
            [
                "xprop",
                "-id",
                hex(window_id),
                "WM_CLASS",
                "WM_NAME",
                "_NET_WM_NAME",
                "_NET_WM_STATE",
            ],
            runner,
        )
        wm_class = _parse_wm_class(props)
        if not _FIREFOX_CLASS_RE.search(wm_class):
            continue
        if _is_hidden(props):
            continue
        net_name = _parse_net_wm_name(props)
        title = (net_name or title_from_tree).strip()
        candidates.append(
            X11Window(
                window_id=window_id,
                title=title,
                width=width,
                height=height,
                offset_x=int(match.group("x")),
                offset_y=int(match.group("y")),
                wm_class=wm_class,
            )
        )
    return candidates


def _normalize_title(value: str) -> str:
    return " ".join(value.casefold().split())


def _title_matches(window_title: str, meet_title: str) -> bool:
    left = _normalize_title(window_title)
    right = _normalize_title(meet_title)
    if not left or not right:
        return False
    if left == right:
        return True
    # Exigir solapamiento sustancial: el título de Meet (sin sufijos comunes) en el de la ventana.
    compact_right = right
    for suffix in (" - meet", " | meet"):
        if compact_right.endswith(suffix):
            compact_right = compact_right[: -len(suffix)].strip()
    # Variantes tipográficas frecuentes en títulos de pestaña.
    for suffix in (" \u2013 meet", " \u2014 meet"):
        if compact_right.endswith(suffix):
            compact_right = compact_right[: -len(suffix)].strip()
    if compact_right and compact_right in left:
        return True
    if left in right and len(left) >= 8:
        return True
    return False


def resolve_meet_window(
    *,
    url: str,
    title: str,
    runner: Runner = subprocess.run,
    environ: dict[str, str] | os._Environ[str] = os.environ,
) -> X11Window:
    if not is_meet_url(url):
        raise WindowCaptureError(
            "INVALID_MEET_URL",
            "La URL no corresponde a una pestaña https://meet.google.com/…",
        )
    display = environ.get("DISPLAY", "").strip()
    if not display:
        raise WindowCaptureError(
            "WINDOW_CAPTURE_UNAVAILABLE",
            "DISPLAY no está definido; no se puede capturar una ventana X11.",
        )

    try:
        candidates = list_candidate_windows(runner)
    except FileNotFoundError as exc:
        raise WindowCaptureError(
            "WINDOW_CAPTURE_UNAVAILABLE",
            f"Falta una herramienta X11 requerida: {exc.filename or exc}",
        ) from exc

    if not candidates:
        raise WindowCaptureError(
            "WINDOW_CAPTURE_UNAVAILABLE",
            "No hay ventanas Firefox visibles en X11. "
            "En sesiones Wayland Firefox suele no exponer window_id a x11grab.",
        )

    meet_title = title.strip()
    if not meet_title:
        raise WindowCaptureError(
            "WINDOW_NOT_FOUND",
            "El título de la pestaña de Meet está vacío; no se puede validar la ventana.",
        )

    matched = [window for window in candidates if _title_matches(window.title, meet_title)]
    if not matched:
        # Segundo criterio: ventana Firefox cuyo título mencione Meet, solo si hay una.
        meet_named = [
            window
            for window in candidates
            if "meet" in _normalize_title(window.title)
        ]
        if len(meet_named) == 1:
            matched = meet_named
        else:
            raise WindowCaptureError(
                "WINDOW_NOT_FOUND",
                "No se encontró una ventana Firefox visible cuyo título coincida "
                f"con la pestaña de Meet ({meet_title!r}).",
            )

    if len(matched) > 1:
        raise WindowCaptureError(
            "WINDOW_AMBIGUOUS",
            "Hay varias ventanas Firefox candidatas; no se puede elegir una de forma fiable.",
        )
    return matched[0]


def video_target_for_window(
    window: X11Window,
    *,
    environ: dict[str, str] | os._Environ[str] = os.environ,
) -> VideoTarget:
    display = environ.get("DISPLAY", "").strip()
    if not display:
        raise WindowCaptureError(
            "WINDOW_CAPTURE_UNAVAILABLE",
            "DISPLAY no está definido; no se puede capturar una ventana X11.",
        )
    return VideoTarget(
        source="window",
        display=display,
        width=window.width,
        height=window.height,
        window_id=window.window_id,
        label=f"window:0x{window.window_id:x}:{window.title[:80]}",
    )
