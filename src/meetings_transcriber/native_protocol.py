from __future__ import annotations

from typing import Any

PROTOCOL_VERSION = 1
NATIVE_HOST_NAME = "com.meetings.transcriptor"
ALLOWED_EXTENSION_ID = "meetings-transcriptor@example.org"

ACTIONS = frozenset({"get_status", "start_recording", "stop_recording"})

# Límite de Native Messaging en Firefox (~1 MiB). Usamos un tope conservador.
MAX_MESSAGE_BYTES = 1024 * 1024


def ok_response(request_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "ok": True,
        "data": data,
    }


def error_response(
    request_id: str,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "ok": False,
        "error": {"code": code, "message": message},
    }


def _is_object(value: Any) -> bool:
    return isinstance(value, dict)


def validate_request(
    message: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Valida una solicitud. Devuelve `(request, None)` o `(None, error_response)`."""
    if not _is_object(message):
        return None, error_response(
            "",
            "INVALID_REQUEST",
            "La solicitud debe ser un objeto JSON.",
        )

    request_id = message.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        return None, error_response(
            str(request_id) if isinstance(request_id, str) else "",
            "INVALID_REQUEST",
            "request_id debe ser un string no vacío.",
        )
    request_id = request_id.strip()

    version = message.get("protocol_version")
    if version != PROTOCOL_VERSION:
        return None, error_response(
            request_id,
            "UNSUPPORTED_PROTOCOL",
            f"protocol_version debe ser {PROTOCOL_VERSION}.",
        )

    action = message.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        return None, error_response(
            request_id,
            "UNKNOWN_ACTION",
            "Acción no permitida por el host.",
        )

    payload = message.get("payload", {})
    if payload is None:
        payload = {}
    if not _is_object(payload):
        return None, error_response(
            request_id,
            "INVALID_REQUEST",
            "payload debe ser un objeto.",
        )

    if action == "start_recording":
        url = payload.get("url")
        title = payload.get("title")
        if not isinstance(url, str) or not url.strip():
            return None, error_response(
                request_id,
                "INVALID_REQUEST",
                "start_recording requiere payload.url string.",
            )
        if not isinstance(title, str):
            return None, error_response(
                request_id,
                "INVALID_REQUEST",
                "start_recording requiere payload.title string.",
            )
        extra = set(payload) - {"url", "title"}
        if extra:
            return None, error_response(
                request_id,
                "INVALID_REQUEST",
                f"Campos no permitidos en payload: {', '.join(sorted(extra))}",
            )
    elif action == "stop_recording":
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            return None, error_response(
                request_id,
                "INVALID_REQUEST",
                "stop_recording requiere payload.session_id string.",
            )
        extra = set(payload) - {"session_id"}
        if extra:
            return None, error_response(
                request_id,
                "INVALID_REQUEST",
                f"Campos no permitidos en payload: {', '.join(sorted(extra))}",
            )
    elif action == "get_status":
        if payload:
            return None, error_response(
                request_id,
                "INVALID_REQUEST",
                "get_status no acepta campos en payload.",
            )

    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "action": action,
        "payload": payload,
    }, None
