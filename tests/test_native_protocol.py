from meetings_transcriber.native_protocol import (
    PROTOCOL_VERSION,
    error_response,
    ok_response,
    validate_request,
)


def test_ok_and_error_preserve_protocol_fields():
    ok = ok_response("req-1", {"status": "ready"})
    assert ok == {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": "req-1",
        "ok": True,
        "data": {"status": "ready"},
    }
    err = error_response("req-2", "BUSY", "ocupado")
    assert err["ok"] is False
    assert err["error"]["code"] == "BUSY"
    assert err["request_id"] == "req-2"


def test_validate_request_accepts_known_actions():
    request, error = validate_request(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "get_status",
            "payload": {},
        }
    )
    assert error is None
    assert request is not None
    assert request["action"] == "get_status"


def test_validate_request_rejects_unknown_action_and_bad_version():
    _, error = validate_request(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "rm -rf /",
            "payload": {},
        }
    )
    assert error is not None
    assert error["error"]["code"] == "UNKNOWN_ACTION"

    _, error = validate_request(
        {
            "protocol_version": 99,
            "request_id": "a",
            "action": "get_status",
            "payload": {},
        }
    )
    assert error is not None
    assert error["error"]["code"] == "UNSUPPORTED_PROTOCOL"


def test_validate_start_and_stop_payloads():
    _, error = validate_request(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Standup"},
        }
    )
    assert error is None

    request, error = validate_request(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {
                "url": "https://meet.google.com/x",
                "title": "Standup",
                "profile": "Shipii",
            },
        }
    )
    assert error is None
    assert request is not None
    assert request["payload"]["profile"] == "Shipii"

    _, error = validate_request(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Standup", "cmd": "x"},
        }
    )
    assert error is not None
    assert error["error"]["code"] == "INVALID_REQUEST"

    _, error = validate_request(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "list_profiles",
            "payload": {},
        }
    )
    assert error is None

    _, error = validate_request(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "stop_recording",
            "payload": {},
        }
    )
    assert error is not None
    assert error["error"]["code"] == "INVALID_REQUEST"

    req, error = validate_request(
        {
            "protocol_version": 1,
            "request_id": "b",
            "action": "stop_recording",
            "payload": {"session_id": "s1", "transcribe": True},
        }
    )
    assert error is None
    assert req["payload"]["transcribe"] is True

    _, error = validate_request(
        {
            "protocol_version": 1,
            "request_id": "c",
            "action": "stop_recording",
            "payload": {"session_id": "s1", "transcribe": "si"},
        }
    )
    assert error is not None
