from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Literal

SourceKind = Literal["window", "monitor"]

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
REQUEST_IFACE = "org.freedesktop.portal.Request"
SESSION_IFACE = "org.freedesktop.portal.Session"

SOURCE_MONITOR = 1
SOURCE_WINDOW = 2
CURSOR_EMBEDDED = 2


class PortalScreenCastError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PortalStream:
    node_id: int
    width: int
    height: int
    source_type: int
    session_handle: str


def gi_available() -> bool:
    try:
        import gi  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


def _require_gi() -> tuple[Any, Any]:
    try:
        import gi  # type: ignore[import-not-found]

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib  # type: ignore[import-not-found]
    except (ImportError, ValueError) as exc:
        raise PortalScreenCastError(
            "WINDOW_CAPTURE_UNAVAILABLE",
            "PyGObject (python3-gi) no está disponible para el portal ScreenCast de Wayland.",
        ) from exc
    return Gio, GLib


def _unique_token(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


class PortalScreenCastSession:
    """Sesión ScreenCast viva mientras el proceso worker no cierre stdin."""

    def __init__(self, *, kind: SourceKind, timeout_seconds: float = 120.0) -> None:
        if kind not in {"window", "monitor"}:
            raise PortalScreenCastError("INVALID_REQUEST", f"Tipo inválido: {kind!r}")
        self.kind = kind
        self.timeout_seconds = timeout_seconds
        self._Gio: Any = None
        self._GLib: Any = None
        self._bus: Any = None
        self._loop: Any = None
        self._session_handle: str | None = None
        self._stream: PortalStream | None = None
        self._closed = False

    @property
    def stream(self) -> PortalStream | None:
        return self._stream

    def open(self) -> PortalStream:
        if self._stream is not None:
            return self._stream
        self._Gio, self._GLib = _require_gi()
        self._bus = self._Gio.bus_get_sync(self._Gio.BusType.SESSION, None)
        self._loop = self._GLib.MainLoop()

        session_token = _unique_token("ms")
        select_token = _unique_token("sel")
        start_token = _unique_token("st")

        session_handle = self._create_session(session_token)
        self._session_handle = session_handle
        try:
            self._select_sources(session_handle, select_token)
            streams = self._start(session_handle, start_token)
        except Exception:
            self.close()
            raise

        if not streams:
            self.close()
            raise PortalScreenCastError(
                "WINDOW_NOT_FOUND",
                "El portal ScreenCast no devolvió ningún stream de captura.",
            )
        node_id, props = streams[0]
        size = props.get("size")
        if not size or len(size) != 2:
            self.close()
            raise PortalScreenCastError(
                "WINDOW_CAPTURE_UNAVAILABLE",
                "El portal ScreenCast no informó el tamaño del stream.",
            )
        self._stream = PortalStream(
            node_id=int(node_id),
            width=int(size[0]),
            height=int(size[1]),
            source_type=int(props.get("source_type", 0)),
            session_handle=session_handle,
        )
        return self._stream

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        handle = self._session_handle
        self._session_handle = None
        self._stream = None
        if handle is None or self._bus is None or self._Gio is None:
            return
        try:
            self._bus.call_sync(
                PORTAL_BUS,
                handle,
                SESSION_IFACE,
                "Close",
                None,
                None,
                self._Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except Exception:
            pass

    def _source_types(self) -> int:
        return SOURCE_WINDOW if self.kind == "window" else SOURCE_MONITOR

    def _sender_token(self) -> str:
        unique = self._bus.get_unique_name()
        return unique.lstrip(":").replace(".", "_")

    def _request_path(self, token: str) -> str:
        return f"/org/freedesktop/portal/desktop/request/{self._sender_token()}/{token}"

    def _create_session(self, token: str) -> str:
        assert self._Gio is not None and self._GLib is not None
        options = {
            "handle_token": self._GLib.Variant("s", token),
            "session_handle_token": self._GLib.Variant("s", f"{token}sess"),
        }
        request_path = self._request_path(token)
        # Suscribirse antes de invocar evita perder la respuesta.
        pending_path = request_path
        result_holder: dict[str, Any] = {}
        errors: list[BaseException] = []

        def on_signal(
            _connection: Any,
            _sender: str,
            _path: str,
            _interface: str,
            signal_name: str,
            parameters: Any,
        ) -> None:
            if signal_name != "Response":
                return
            code, data = parameters.unpack()
            if int(code) != 0:
                errors.append(
                    PortalScreenCastError(
                        "WINDOW_CAPTURE_UNAVAILABLE",
                        f"CreateSession del portal falló (código {code}).",
                    )
                )
            else:
                result_holder.update(dict(data))
            self._loop.quit()

        def on_timeout() -> bool:
            errors.append(
                PortalScreenCastError(
                    "WINDOW_CAPTURE_UNAVAILABLE",
                    f"Timeout ({self.timeout_seconds:.0f}s) en CreateSession.",
                )
            )
            if self._loop.is_running():
                self._loop.quit()
            return False

        sub = self._bus.signal_subscribe(
            PORTAL_BUS,
            REQUEST_IFACE,
            "Response",
            pending_path,
            None,
            self._Gio.DBusSignalFlags.NONE,
            on_signal,
        )
        timeout_id = self._GLib.timeout_add(int(self.timeout_seconds * 1000), on_timeout)
        try:
            self._bus.call_sync(
                PORTAL_BUS,
                PORTAL_PATH,
                SCREENCAST_IFACE,
                "CreateSession",
                self._GLib.Variant("(a{sv})", (options,)),
                self._GLib.VariantType("(o)"),
                self._Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            self._loop.run()
        finally:
            self._GLib.source_remove(timeout_id)
            self._bus.signal_unsubscribe(sub)
        if errors:
            raise errors[0]
        handle = result_holder.get("session_handle")
        if not isinstance(handle, str) or not handle:
            raise PortalScreenCastError(
                "WINDOW_CAPTURE_UNAVAILABLE",
                "CreateSession no devolvió session_handle.",
            )
        return handle

    def _select_sources(self, session_handle: str, token: str) -> None:
        assert self._Gio is not None and self._GLib is not None
        options = {
            "handle_token": self._GLib.Variant("s", token),
            "types": self._GLib.Variant("u", self._source_types()),
            "multiple": self._GLib.Variant("b", False),
            "cursor_mode": self._GLib.Variant("u", CURSOR_EMBEDDED),
        }
        request_path = self._request_path(token)
        # Pre-suscripción vía _await_response no cubre la carrera; suscribimos
        # igual que CreateSession prediciendo el path del token.
        errors: list[BaseException] = []
        done: dict[str, Any] = {}

        def on_signal(
            _connection: Any,
            _sender: str,
            _path: str,
            _interface: str,
            signal_name: str,
            parameters: Any,
        ) -> None:
            if signal_name != "Response":
                return
            code, data = parameters.unpack()
            if int(code) != 0:
                errors.append(
                    PortalScreenCastError(
                        "WINDOW_CAPTURE_UNAVAILABLE",
                        "SelectSources cancelado o fallido "
                        f"(código {code}). Elegí la ventana/monitor de Meet en el diálogo.",
                    )
                )
            else:
                done.update(dict(data))
            self._loop.quit()

        def on_timeout() -> bool:
            errors.append(
                PortalScreenCastError(
                    "WINDOW_CAPTURE_UNAVAILABLE",
                    "Timeout en SelectSources del portal ScreenCast.",
                )
            )
            if self._loop.is_running():
                self._loop.quit()
            return False

        sub = self._bus.signal_subscribe(
            PORTAL_BUS,
            REQUEST_IFACE,
            "Response",
            request_path,
            None,
            self._Gio.DBusSignalFlags.NONE,
            on_signal,
        )
        timeout_id = self._GLib.timeout_add(int(self.timeout_seconds * 1000), on_timeout)
        try:
            self._bus.call_sync(
                PORTAL_BUS,
                PORTAL_PATH,
                SCREENCAST_IFACE,
                "SelectSources",
                self._GLib.Variant("(oa{sv})", (session_handle, options)),
                self._GLib.VariantType("(o)"),
                self._Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            self._loop.run()
        finally:
            self._GLib.source_remove(timeout_id)
            self._bus.signal_unsubscribe(sub)
        if errors:
            raise errors[0]

    def _start(
        self, session_handle: str, token: str
    ) -> list[tuple[int, dict[str, Any]]]:
        assert self._Gio is not None and self._GLib is not None
        options = {"handle_token": self._GLib.Variant("s", token)}
        request_path = self._request_path(token)
        errors: list[BaseException] = []
        done: dict[str, Any] = {}

        def on_signal(
            _connection: Any,
            _sender: str,
            _path: str,
            _interface: str,
            signal_name: str,
            parameters: Any,
        ) -> None:
            if signal_name != "Response":
                return
            code, data = parameters.unpack()
            if int(code) != 0:
                errors.append(
                    PortalScreenCastError(
                        "WINDOW_CAPTURE_UNAVAILABLE",
                        f"Start del portal cancelado o fallido (código {code}).",
                    )
                )
            else:
                done.update(dict(data))
            self._loop.quit()

        def on_timeout() -> bool:
            errors.append(
                PortalScreenCastError(
                    "WINDOW_CAPTURE_UNAVAILABLE",
                    "Timeout en Start del portal ScreenCast.",
                )
            )
            if self._loop.is_running():
                self._loop.quit()
            return False

        sub = self._bus.signal_subscribe(
            PORTAL_BUS,
            REQUEST_IFACE,
            "Response",
            request_path,
            None,
            self._Gio.DBusSignalFlags.NONE,
            on_signal,
        )
        timeout_id = self._GLib.timeout_add(int(self.timeout_seconds * 1000), on_timeout)
        try:
            self._bus.call_sync(
                PORTAL_BUS,
                PORTAL_PATH,
                SCREENCAST_IFACE,
                "Start",
                self._GLib.Variant("(osa{sv})", (session_handle, "", options)),
                self._GLib.VariantType("(o)"),
                self._Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            self._loop.run()
        finally:
            self._GLib.source_remove(timeout_id)
            self._bus.signal_unsubscribe(sub)
        if errors:
            raise errors[0]
        streams_raw = done.get("streams") or []
        streams: list[tuple[int, dict[str, Any]]] = []
        for item in streams_raw:
            node_id, props = item
            streams.append((int(node_id), dict(props)))
        return streams


def main(argv: list[str] | None = None) -> int:
    """Worker: abre el portal, imprime JSON y mantiene la sesión hasta EOF en stdin."""
    args = list(sys.argv[1:] if argv is None else argv)
    kind: SourceKind = "window"
    if args and args[0] in {"window", "monitor"}:
        kind = args[0]  # type: ignore[assignment]
    try:
        session = PortalScreenCastSession(kind=kind)
        stream = session.open()
    except PortalScreenCastError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "message": exc.message}), flush=True)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "node_id": stream.node_id,
                "width": stream.width,
                "height": stream.height,
                "source_type": stream.source_type,
                "session_handle": stream.session_handle,
                "kind": kind,
            }
        ),
        flush=True,
    )
    try:
        sys.stdin.read()
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
