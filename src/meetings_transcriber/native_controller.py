from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .audio import RecordingSession, detect_video_codec, resolve_monitor_video_target
from .config import Settings, load_settings
from .models import RunPaths
from .native_protocol import error_response, ok_response, validate_request
from .portal_screencast import PortalScreenCastError
from .profiles import create_run_paths, ensure_profile, list_profile_names, validate_profile_name
from .wayland_capture import (
    ensure_gst_pipewire_available,
    is_wayland_session,
    open_portal_capture,
    video_target_from_portal,
)
from .window_capture import (
    WindowCaptureError,
    is_meet_url,
    resolve_meet_window,
    video_target_for_window,
)

VideoSource = Literal["window", "monitor"]


@dataclass
class ActiveRecording:
    session_id: str
    session: RecordingSession
    paths: RunPaths
    profile_name: str
    meet_url: str
    meet_title: str
    video_source: str
    video_label: str


class NativeHostController:
    """Estado del host: como máximo una grabación activa."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        project_dir: Path | None = None,
        environ: dict[str, str] | os._Environ[str] | None = None,
    ) -> None:
        self.environ = environ if environ is not None else os.environ
        self.project_dir = project_dir or Path(__file__).resolve().parents[2]
        self.settings = settings or load_settings(self.project_dir)
        self._active: ActiveRecording | None = None
        self._last_error: str | None = None

    def native_video_source(self) -> VideoSource:
        raw = self.environ.get("NATIVE_VIDEO_SOURCE", "window").strip().lower()
        if raw in {"window", "monitor"}:
            return raw  # type: ignore[return-value]
        raise ValueError(
            f"NATIVE_VIDEO_SOURCE inválido: {raw!r}. Usá 'window' o 'monitor'."
        )

    def default_profile_name(self) -> str | None:
        raw = self.environ.get("NATIVE_MESSAGING_PROFILE", "").strip()
        if not raw:
            return None
        try:
            return validate_profile_name(raw)
        except ValueError:
            return None

    def resolve_profile_name(self, requested: str | None) -> str:
        """Perfil del payload o fallback a NATIVE_MESSAGING_PROFILE."""
        if requested is not None and str(requested).strip():
            try:
                return validate_profile_name(str(requested).strip())
            except ValueError as exc:
                raise ValueError(f"INVALID_PROFILE: {exc}") from exc
        default = self.default_profile_name()
        if default:
            return default
        raise ValueError(
            "PROFILE_NOT_CONFIGURED: indicá un profile en start_recording "
            "o configurá NATIVE_MESSAGING_PROFILE."
        )

    def handle(self, message: Any) -> dict[str, Any]:
        request, error = validate_request(message)
        if error is not None:
            return error
        assert request is not None
        action = request["action"]
        request_id = request["request_id"]
        payload = request["payload"]
        try:
            if action == "get_status":
                return ok_response(request_id, self.get_status())
            if action == "list_profiles":
                return ok_response(request_id, self.list_profiles())
            if action == "start_recording":
                return ok_response(
                    request_id,
                    self.start_recording(
                        url=payload["url"],
                        title=payload["title"],
                        profile=payload.get("profile"),
                    ),
                )
            if action == "stop_recording":
                return ok_response(
                    request_id,
                    self.stop_recording(session_id=payload["session_id"]),
                )
        except (WindowCaptureError, PortalScreenCastError) as exc:
            self._last_error = exc.message
            return error_response(request_id, exc.code, exc.message)
        except ValueError as exc:
            self._last_error = str(exc)
            message_text = str(exc)
            if "PROFILE_NOT_CONFIGURED" in message_text or "NATIVE_MESSAGING_PROFILE" in message_text:
                code = "PROFILE_NOT_CONFIGURED"
            elif "INVALID_PROFILE" in message_text or "perfil inválido" in message_text.casefold():
                code = "INVALID_PROFILE"
            elif "NATIVE_VIDEO_SOURCE" in message_text:
                code = "INVALID_REQUEST"
            else:
                code = "INVALID_REQUEST"
            return error_response(request_id, code, message_text)
        except RuntimeError as exc:
            self._last_error = str(exc)
            message = str(exc)
            code = "FFMPEG_ERROR" if "FFmpeg" in message else "INTERNAL_ERROR"
            if "ya hay una grabación" in message.casefold() or "BUSY" in message:
                code = "BUSY"
            if "sesión" in message.casefold() or "session" in message.casefold():
                if "no hay" in message.casefold() or "no coincide" in message.casefold():
                    code = "NO_SESSION"
            return error_response(request_id, code, message)
        except OSError as exc:
            self._last_error = str(exc)
            return error_response(request_id, "INTERNAL_ERROR", str(exc))
        return error_response(request_id, "UNKNOWN_ACTION", "Acción no implementada.")

    def get_status(self) -> dict[str, Any]:
        active = self._active
        if active is not None and active.session.is_running:
            return {
                "status": "recording",
                "session_id": active.session_id,
                "meeting_dir": str(active.paths.directory),
                "video_source": active.video_source,
                "video_label": active.video_label,
            }
        if active is not None and not active.session.is_running:
            # Proceso cayó solo: limpiar y reportar error.
            code = active.session.return_code
            self._last_error = f"FFmpeg terminó de forma inesperada con código {code}"
            self._active = None
            return {
                "status": "error",
                "session_id": None,
                "message": self._last_error,
            }
        if self._last_error:
            return {
                "status": "error",
                "session_id": None,
                "message": self._last_error,
            }
        return {"status": "ready", "session_id": None}

    def list_profiles(self) -> dict[str, Any]:
        profiles = list_profile_names(self.settings.base_dir)
        default = self.default_profile_name()
        data: dict[str, Any] = {"profiles": profiles}
        if default is not None:
            data["default_profile"] = default
        return data

    def start_recording(
        self,
        *,
        url: str,
        title: str,
        profile: str | None = None,
    ) -> dict[str, Any]:
        if self._active is not None and self._active.session.is_running:
            raise RuntimeError("BUSY: ya hay una grabación en curso")
        if self._active is not None:
            self._active = None

        if not is_meet_url(url):
            raise WindowCaptureError(
                "INVALID_MEET_URL",
                "La URL no corresponde a una pestaña https://meet.google.com/…",
            )

        profile_name = self.resolve_profile_name(profile)
        video_source = self.native_video_source()
        profile_paths = ensure_profile(self.settings.base_dir, profile_name)
        paths = create_run_paths(profile_paths)

        if not self.settings.record_video:
            raise RuntimeError(
                "RECORD_VIDEO=false; el host Native Messaging requiere captura de video."
            )

        codec = detect_video_codec()
        portal_handle = None
        if video_source == "window":
            target, portal_handle = self._resolve_window_target(url=url, title=title)
        elif is_wayland_session(self.environ):
            # Fallback explícito a monitor en Wayland: portal (selector de pantalla).
            ensure_gst_pipewire_available()
            portal_handle = open_portal_capture("monitor", environ=self.environ)
            target = video_target_from_portal(portal_handle)
        else:
            target, _codec = resolve_monitor_video_target(
                self.settings, environ=self.environ
            )

        session = RecordingSession(
            self.settings,
            paths,
            video_target=target,
            video_codec=codec,
            portal_handle=portal_handle,
        )
        session_id = str(uuid.uuid4())
        try:
            session.start()
        except Exception:
            # Evitar dejar carpetas a medias sin proceso; la carpeta puede quedar vacía.
            raise

        if not session.is_running:
            code = session.return_code
            raise RuntimeError(
                f"FFmpeg no permaneció en ejecución tras el inicio (código {code})"
            )

        self._active = ActiveRecording(
            session_id=session_id,
            session=session,
            paths=paths,
            profile_name=profile_paths.name,
            meet_url=url,
            meet_title=title,
            video_source=target.source,
            video_label=target.label,
        )
        self._last_error = None
        return {
            "session_id": session_id,
            "status": "recording",
            "meeting_dir": str(paths.directory),
            "profile": profile_paths.name,
            "video_source": target.source,
            "video_label": target.label,
            "meet_url": url,
            "meet_title": title,
        }

    def stop_recording(self, *, session_id: str) -> dict[str, Any]:
        active = self._active
        if active is None:
            raise RuntimeError("NO_SESSION: no hay una sesión de grabación activa")
        if active.session_id != session_id.strip():
            raise RuntimeError("NO_SESSION: session_id no coincide con la sesión activa")

        return_code = active.session.stop()
        try:
            active.session.validate_outputs(return_code)
        finally:
            self._active = None

        self._last_error = None
        return {
            "status": "ready",
            "session_id": session_id.strip(),
            "meeting_dir": str(active.paths.directory),
            "profile": active.profile_name,
            "video_source": active.video_source,
            "video_label": active.video_label,
            "ffmpeg_return_code": return_code,
            "files": {
                "system_audio": str(active.paths.system_audio),
                "microphone_audio": str(active.paths.microphone_audio),
                "mixed_audio": str(active.paths.mixed_audio),
                "video": str(active.paths.video),
            },
        }

    def _resolve_window_target(self, *, url: str, title: str):
        """X11 por window_id si hay ventanas Firefox; si no, portal Wayland."""
        if is_wayland_session(self.environ):
            ensure_gst_pipewire_available()
            handle = open_portal_capture("window", environ=self.environ)
            return video_target_from_portal(handle), handle

        try:
            window = resolve_meet_window(url=url, title=title, environ=self.environ)
            return video_target_for_window(window, environ=self.environ), None
        except WindowCaptureError as exc:
            # Sesión híbrida: Wayland_DISPLAY presente aunque XDG diga otra cosa.
            if exc.code == "WINDOW_CAPTURE_UNAVAILABLE" and self.environ.get("WAYLAND_DISPLAY"):
                ensure_gst_pipewire_available()
                handle = open_portal_capture("window", environ=self.environ)
                return video_target_from_portal(handle), handle
            raise

    def shutdown(self) -> None:
        """Cierre seguro si Firefox corta el pipe (sin dejar FFmpeg huérfano)."""
        active = self._active
        if active is None:
            return
        try:
            if active.session.is_running:
                return_code = active.session.stop()
                try:
                    active.session.validate_outputs(return_code)
                except (RuntimeError, ValueError, OSError):
                    pass
        finally:
            self._active = None
