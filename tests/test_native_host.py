import io
import json
import struct

from meetings_transcriber.native_controller import NativeHostController
from meetings_transcriber.native_host import read_message, serve, write_message
from meetings_transcriber.native_protocol import MAX_MESSAGE_BYTES


class FakeController(NativeHostController):
    def __init__(self):
        self.handled = []
        self.shut_down = False

    def handle(self, message):
        self.handled.append(message)
        return {
            "protocol_version": 1,
            "request_id": message.get("request_id", ""),
            "ok": True,
            "data": {"status": "ready"},
        }

    def shutdown(self):
        self.shut_down = True


def _frame(message: dict) -> bytes:
    payload = json.dumps(message).encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


def test_read_write_native_messaging_framing():
    message = {"protocol_version": 1, "request_id": "x", "action": "get_status", "payload": {}}
    buffer = io.BytesIO()
    write_message(buffer, message)
    buffer.seek(0)
    decoded = read_message(buffer)
    assert decoded == message


def test_read_message_rejects_oversized_payload():
    buffer = io.BytesIO(struct.pack("<I", MAX_MESSAGE_BYTES + 1) + b"x")
    try:
        read_message(buffer)
        raised = False
    except ValueError as exc:
        raised = True
        assert "inválido" in str(exc).casefold() or "invalid" in str(exc).casefold()
    assert raised


def test_serve_handles_requests_and_shutdown_on_eof():
    controller = FakeController()
    request = {
        "protocol_version": 1,
        "request_id": "req-9",
        "action": "get_status",
        "payload": {},
    }
    stdin = io.BytesIO(_frame(request))
    stdout = io.BytesIO()
    assert serve(controller, stdin=stdin, stdout=stdout) == 0
    assert controller.handled == [request]
    assert controller.shut_down is True
    stdout.seek(0)
    response = read_message(stdout)
    assert response is not None
    assert response["ok"] is True
    assert response["request_id"] == "req-9"


def test_serve_disconnect_still_calls_shutdown():
    controller = FakeController()
    stdin = io.BytesIO(b"")
    stdout = io.BytesIO()
    serve(controller, stdin=stdin, stdout=stdout)
    assert controller.shut_down is True
