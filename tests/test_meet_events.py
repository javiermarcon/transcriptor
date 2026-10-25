from meetings_transcriber.meet_events import (
    append_meet_event,
    load_meet_events,
    load_session_meta,
    validate_meet_event_payload,
    write_session_meta,
)
from meetings_transcriber.native_protocol import validate_request


def test_validate_meet_event_payload_ok_and_rejects():
    event, err = validate_meet_event_payload(
        {
            "session_id": "s1",
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": 123.0,
            "display_name": "Nacho",
            "confidence": 0.6,
        }
    )
    assert err is None
    assert event is not None
    assert event["display_name"] == "Nacho"

    _, err = validate_meet_event_payload(
        {
            "session_id": "s1",
            "event_type": "rm -rf",
            "timestamp_epoch_ms": 1,
        }
    )
    assert err is not None

    _, err = validate_meet_event_payload(
        {
            "session_id": "s1",
            "event_type": "participant_joined",
            "timestamp_epoch_ms": 1,
            "shell": "x",
        }
    )
    assert err is not None and "no permitidos" in err


def test_record_meet_event_protocol_action():
    request, error = validate_request(
        {
            "protocol_version": 1,
            "request_id": "r1",
            "action": "record_meet_event",
            "payload": {
                "session_id": "sess",
                "event_type": "participant_joined",
                "timestamp_epoch_ms": 1000,
                "display_name": "Ana",
                "source": "dom_people_list",
                "confidence": 0.55,
            },
        }
    )
    assert error is None
    assert request is not None
    assert request["action"] == "record_meet_event"
    assert request["payload"]["display_name"] == "Ana"


def test_append_and_load_meet_events(tmp_path):
    path = tmp_path / "meet_events.jsonl"
    append_meet_event(
        path,
        {
            "session_id": "s",
            "event_type": "observation_started",
            "timestamp_epoch_ms": 1,
        },
    )
    append_meet_event(
        path,
        {
            "session_id": "s",
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": 2,
            "display_name": "Javier",
        },
    )
    events = load_meet_events(path)
    assert len(events) == 2
    assert events[1]["display_name"] == "Javier"


def test_session_meta_roundtrip(tmp_path):
    path = tmp_path / "session.json"
    write_session_meta(path, {"session_id": "abc", "recording_started_at_epoch_ms": 42})
    meta = load_session_meta(path)
    assert meta is not None
    assert meta["session_id"] == "abc"
    assert meta["recording_started_at_epoch_ms"] == 42
