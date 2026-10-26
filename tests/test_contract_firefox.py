"""Contrato extensión ↔ host: payloads derivados del esquema real de Firefox.

No ejecuta Meet ni FFmpeg. Los fixtures en tests/fixtures/synthetic/ están
marcados como sintéticos.
"""

from __future__ import annotations

import json
from pathlib import Path

from meetings_transcriber.attribution import attribute_segments, write_attributed_transcript
from meetings_transcriber.meet_events import load_meet_events, validate_meet_event_payload
from meetings_transcriber.native_protocol import (
    ACTIONS,
    NATIVE_HOST_NAME,
    PROTOCOL_VERSION,
    validate_request,
)
from meetings_transcriber.profiles import run_paths_for_directory

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "synthetic"

# Acciones que declara shared/protocol.js de transcriptor-firefox (verificado en auditoría).
FIREFOX_PROTOCOL_ACTIONS = frozenset(
    {
        "get_status",
        "list_profiles",
        "start_recording",
        "stop_recording",
        "record_meet_event",
    }
)


def test_host_actions_match_firefox_protocol_v1():
    assert PROTOCOL_VERSION == 1
    assert NATIVE_HOST_NAME == "com.meetings.transcriptor"
    assert ACTIONS == FIREFOX_PROTOCOL_ACTIONS


def test_synthetic_meet_events_from_extension_schema_are_accepted():
    path = FIXTURES / "meet_events_sequence.jsonl"
    assert path.is_file()
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 5
    for line in lines:
        raw = json.loads(line)
        assert raw.get("details", {}).get("synthetic") is True or raw["event_type"].startswith(
            "observation_"
        )
        event, err = validate_meet_event_payload(raw)
        assert err is None, err
        assert event is not None
        request, error = validate_request(
            {
                "protocol_version": 1,
                "request_id": "contract-1",
                "action": "record_meet_event",
                "payload": raw,
            }
        )
        assert error is None
        assert request is not None
        assert request["action"] == "record_meet_event"


def test_roster_only_events_do_not_attribute_names():
    """participant_joined/left figuran en Meet pero no atribuyen segmentos."""
    events = load_meet_events(FIXTURES / "meet_events_sequence.jsonl")
    roster_only = [
        event
        for event in events
        if event["event_type"] in {"participant_joined", "participant_left", "observation_started", "observation_stopped"}
    ]
    whisper = json.loads((FIXTURES / "whisperx_segments.json").read_text(encoding="utf-8"))
    doc = attribute_segments(
        whisper["segments"],
        meet_events=roster_only,
        recording_started_at_epoch_ms=1_700_000_000_000,
    )
    assert all(seg["attributed_name"] is None for seg in doc["segments"])
    assert doc["speakers"] == {}
    assert all(seg["speaker_id"].startswith("SPEAKER_") for seg in doc["segments"])


def test_active_speaker_events_align_to_whisperx_relative_time():
    """Los timestamp_epoch_ms se restan de recording_started_at_epoch_ms → segundos de audio."""
    events = load_meet_events(FIXTURES / "meet_events_sequence.jsonl")
    whisper = json.loads((FIXTURES / "whisperx_segments.json").read_text(encoding="utf-8"))
    started = 1_700_000_000_000
    doc = attribute_segments(
        whisper["segments"],
        meet_events=events,
        recording_started_at_epoch_ms=started,
    )
    # Segmento ~10-12s alineado con eventos Nacho ~10.2s / 10.5s
    assert doc["speakers"]["SPEAKER_00"]["attributed_name"] == "Nacho"
    # Segmento ~20-22.5s alineado con eventos Javier ~20.1s / 20.8s
    assert doc["speakers"]["SPEAKER_01"]["attributed_name"] == "Javier"
    # Segmento ~40s sin active_speaker cercano: hereda mapa SPEAKER_00=Nacho
    # (atribucion a nivel speaker, no solo por evento del segmento).
    seg40 = next(seg for seg in doc["segments"] if seg["start"] == 40.0)
    assert seg40["speaker_id"] == "SPEAKER_00"
    assert seg40["attributed_name"] == "Nacho"
    assert seg40["attribution"]["source"] == "meet_active_speaker"
    refs = doc["speakers"]["SPEAKER_00"]["evidence"]["meet_event_refs"]
    assert refs
    assert all("timestamp_epoch_ms" in ref for ref in refs)


def test_legacy_meeting_without_meet_events_keeps_speaker_ids(tmp_path):
    """Grabación anterior sin session.json / meet_events: atribución vacía, IDs intactos."""
    meeting = tmp_path / "Reunion_legacy_synthetic"
    meeting.mkdir()
    paths = run_paths_for_directory(meeting)
    whisper = json.loads((FIXTURES / "whisperx_segments.json").read_text(encoding="utf-8"))
    paths.json_result.write_text(json.dumps(whisper), encoding="utf-8")
    # Sin microfono/sistema ni meet_events ni session_meta.
    assert not paths.meet_events.exists()
    assert not paths.session_meta.exists()

    doc = write_attributed_transcript(
        paths.json_result,
        paths.attributed_transcript,
        paths,
        local_participant_name=None,
    )
    assert paths.attributed_transcript.is_file()
    assert doc["speakers"] == {}
    for seg, original in zip(doc["segments"], whisper["segments"], strict=True):
        assert seg["speaker_id"] == original["speaker"]
        assert seg["attributed_name"] is None
        assert seg["text"] == original["text"]


def test_out_of_order_meet_timestamps_still_windowed_by_sort():
    started = 1_700_000_000_000
    # Entregados fuera de orden (como podría llegar JSONL si se append-a con reloj ruidoso).
    events = [
        {
            "session_id": "s",
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": started + 11_000,
            "display_name": "Nacho",
            "participant_key": "k:nacho",
            "confidence": 0.8,
            "details": {"synthetic": True},
        },
        {
            "session_id": "s",
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": started + 10_200,
            "display_name": "Nacho",
            "participant_key": "k:nacho",
            "confidence": 0.8,
            "details": {"synthetic": True},
        },
    ]
    segments = [
        {"start": 10.0, "end": 12.0, "text": "hola", "speaker": "SPEAKER_00"},
    ]
    doc = attribute_segments(
        segments,
        meet_events=events,
        recording_started_at_epoch_ms=started,
    )
    assert doc["speakers"]["SPEAKER_00"]["attributed_name"] == "Nacho"
