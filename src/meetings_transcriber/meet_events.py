from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MEET_EVENT_TYPES = frozenset(
    {
        "observation_started",
        "observation_stopped",
        "participant_joined",
        "participant_left",
        "participant_seen",
        "active_speaker_changed",
    }
)

_ALLOWED_EVENT_FIELDS = frozenset(
    {
        "session_id",
        "event_type",
        "timestamp_epoch_ms",
        "source",
        "display_name",
        "participant_key",
        "confidence",
        "quality",
        "details",
    }
)


def validate_meet_event_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Valida el payload de record_meet_event. Devuelve (evento, None) o (None, mensaje)."""
    extra = set(payload) - _ALLOWED_EVENT_FIELDS
    if extra:
        return None, f"Campos no permitidos en payload: {', '.join(sorted(extra))}"

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None, "record_meet_event requiere payload.session_id string."

    event_type = payload.get("event_type")
    if not isinstance(event_type, str) or event_type not in MEET_EVENT_TYPES:
        return None, "record_meet_event.event_type no permitido."

    ts = payload.get("timestamp_epoch_ms")
    if not isinstance(ts, (int, float)) or isinstance(ts, bool) or not (ts == ts):
        return None, "record_meet_event requiere timestamp_epoch_ms numérico."

    event: dict[str, Any] = {
        "session_id": session_id.strip(),
        "event_type": event_type,
        "timestamp_epoch_ms": float(ts),
    }

    source = payload.get("source")
    if source is not None:
        if not isinstance(source, str) or not source.strip():
            return None, "source debe ser un string no vacío."
        event["source"] = source.strip()

    display_name = payload.get("display_name")
    if display_name is not None:
        if not isinstance(display_name, str) or not display_name.strip():
            return None, "display_name debe ser un string no vacío."
        event["display_name"] = display_name.strip()

    participant_key = payload.get("participant_key")
    if participant_key is not None:
        if not isinstance(participant_key, str) or not participant_key.strip():
            return None, "participant_key debe ser un string no vacío."
        event["participant_key"] = participant_key.strip()

    if "confidence" in payload:
        confidence = payload.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            return None, "confidence debe ser numérico."
        conf = float(confidence)
        if conf < 0.0 or conf > 1.0:
            return None, "confidence debe estar entre 0 y 1."
        event["confidence"] = conf

    quality = payload.get("quality")
    if quality is not None:
        if not isinstance(quality, str) or not quality.strip():
            return None, "quality debe ser un string no vacío."
        event["quality"] = quality.strip()

    details = payload.get("details")
    if details is not None:
        if not isinstance(details, dict):
            return None, "details debe ser un objeto."
        event["details"] = details

    return event, None


def write_session_meta(path: Path, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_session_meta(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def append_meet_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_meet_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        if isinstance(data, dict):
            events.append(data)
    return events
