import threading
from pathlib import Path
from signal import SIGINT
from unittest.mock import Mock

import pytest

from meetings_transcriber.audio import VideoTarget
from meetings_transcriber.config import Settings
from meetings_transcriber.native_controller import NativeHostController
from meetings_transcriber.window_capture import WindowCaptureError, X11Window


def make_settings(tmp_path: Path, **kwargs) -> Settings:
    values = dict(
        base_dir=tmp_path,
        whisperx_bin=None,
        whisper_ctranslate2_bin=None,
        hf_token=None,
        model="large-v3",
        batch_size=2,
        threads=4,
        device="cpu",
        compute_type="int8",
        volume_system=0.7,
        volume_microphone=2.0,
        vad_method="pyannote",
        vad_onset=0.5,
        vad_offset=0.363,
        chunk_size=30,
        sink="sink",
        microphone="microphone",
        record_video=True,
        video_monitor="primary",
        video_fps=10,
    )
    values.update(kwargs)
    return Settings(**values)


class FakePopen:
    def __init__(self):
        self.signals = []
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def send_signal(self, sig):
        self.signals.append(sig)
        self.returncode = 255


@pytest.fixture
def controller(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    environ = {
        "NATIVE_MESSAGING_PROFILE": "Shipii",
        "NATIVE_VIDEO_SOURCE": "window",
        "DISPLAY": ":1",
    }
    ctrl = NativeHostController(settings=settings, project_dir=tmp_path, environ=environ)
    fake = FakePopen()
    monkeypatch.setattr(
        "meetings_transcriber.audio.subprocess.Popen",
        lambda *_a, **_k: fake,
    )
    monkeypatch.setattr("meetings_transcriber.audio.resolve_audio_devices", lambda _s: ("sink", "mic"))
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.detect_video_codec",
        lambda *_a, **_k: "libx264",
    )
    monkeypatch.setattr("meetings_transcriber.audio.validate_audio", lambda *_a, **_k: 1.0)
    monkeypatch.setattr("meetings_transcriber.audio.validate_video", lambda *_a, **_k: 1.0)
    return ctrl, fake


def test_get_status_ready(controller):
    ctrl, _fake = controller
    response = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "r1",
            "action": "get_status",
            "payload": {},
        }
    )
    assert response["ok"] is True
    assert response["data"]["status"] == "ready"
    assert response["request_id"] == "r1"


def test_list_profiles_returns_dirs_and_default(controller, tmp_path):
    ctrl, _fake = controller
    (tmp_path / "Shipii").mkdir()
    (tmp_path / "motonave").mkdir()
    (tmp_path / "ignore.txt").write_text("x", encoding="utf-8")
    (tmp_path / "../bad").mkdir(exist_ok=True)

    response = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "lp",
            "action": "list_profiles",
            "payload": {},
        }
    )
    assert response["ok"] is True
    assert response["data"]["profiles"] == ["motonave", "Shipii"]
    assert response["data"]["default_profile"] == "Shipii"


def test_start_recording_uses_profile_from_payload(controller, monkeypatch):
    ctrl, _fake = controller
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.resolve_meet_window",
        lambda **_k: X11Window(1, "Meet", 800, 600, 0, 0, "firefox"),
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.video_target_for_window",
        lambda _w, environ=None: VideoTarget(
            "window", ":1", 800, 600, window_id=1, label="w"
        ),
    )
    response = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "p1",
            "action": "start_recording",
            "payload": {
                "url": "https://meet.google.com/abc-defg-hij",
                "title": "Meet",
                "profile": "motonave",
            },
        }
    )
    assert response["ok"] is True
    assert response["data"]["profile"] == "motonave"
    assert "motonave" in response["data"]["meeting_dir"]


def test_start_recording_window_success(controller, monkeypatch):
    ctrl, fake = controller
    window = X11Window(0xABC, "Standup - Google Meet", 1280, 720, 0, 0, "Navigator, firefox")
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.resolve_meet_window",
        lambda **_k: window,
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.video_target_for_window",
        lambda _w, environ=None: VideoTarget(
            source="window",
            display=":1",
            width=1280,
            height=720,
            window_id=0xABC,
            label="window:test",
        ),
    )

    response = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "r2",
            "action": "start_recording",
            "payload": {
                "url": "https://meet.google.com/abc-defg-hij",
                "title": "Standup",
            },
        }
    )
    assert response["ok"] is True
    assert response["data"]["status"] == "recording"
    assert response["data"]["session_id"]
    assert response["data"]["video_source"] == "window"
    assert fake.returncode is None

    status = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "r3",
            "action": "get_status",
            "payload": {},
        }
    )
    assert status["data"]["status"] == "recording"
    assert status["data"]["session_id"] == response["data"]["session_id"]


def test_start_recording_duplicate_is_busy(controller, monkeypatch):
    ctrl, _fake = controller
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.resolve_meet_window",
        lambda **_k: X11Window(1, "Meet", 800, 600, 0, 0, "firefox"),
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.video_target_for_window",
        lambda _w, environ=None: VideoTarget(
            "window", ":1", 800, 600, window_id=1, label="w"
        ),
    )
    first = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Meet"},
        }
    )
    assert first["ok"] is True
    second = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "b",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Meet"},
        }
    )
    assert second["ok"] is False
    assert second["error"]["code"] == "BUSY"


def test_stop_without_session(controller):
    ctrl, _fake = controller
    response = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "r",
            "action": "stop_recording",
            "payload": {"session_id": "missing"},
        }
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "NO_SESSION"


def test_stop_recording_validates_and_returns_files(controller, monkeypatch):
    ctrl, fake = controller
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.resolve_meet_window",
        lambda **_k: X11Window(1, "Meet", 800, 600, 0, 0, "firefox"),
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.video_target_for_window",
        lambda _w, environ=None: VideoTarget(
            "window", ":1", 800, 600, window_id=1, label="w"
        ),
    )
    started = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Meet"},
        }
    )
    session_id = started["data"]["session_id"]
    stopped = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "b",
            "action": "stop_recording",
            "payload": {"session_id": session_id},
        }
    )
    assert stopped["ok"] is True
    assert stopped["data"]["status"] == "ready"
    assert stopped["data"]["files"]["video"].endswith("reunion.mp4")
    assert stopped["data"]["transcribed"] is False
    assert fake.signals == [SIGINT]


def test_stop_recording_can_transcribe(controller, monkeypatch):
    ctrl, _fake = controller
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.resolve_meet_window",
        lambda **_k: X11Window(1, "Meet", 800, 600, 0, 0, "firefox"),
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.video_target_for_window",
        lambda _w, environ=None: VideoTarget(
            "window", ":1", 800, 600, window_id=1, label="w"
        ),
    )
    called = {}
    started_gate = threading.Event()
    finish_gate = threading.Event()

    def fake_transcribe(settings, profile, paths, *, on_progress=None, echo_stdout=True):
        called["profile"] = profile.name
        called["echo_stdout"] = echo_stdout
        started_gate.set()
        assert finish_gate.wait(2.0)
        if on_progress is not None:
            from meetings_transcriber.progress import Progress

            on_progress(Progress(current=30.0, total=60.0))
        paths.plain_transcript.write_text("hola", encoding="utf-8")
        paths.speaker_transcript.write_text("SPEAKER_00: hola", encoding="utf-8")

    monkeypatch.setattr(
        "meetings_transcriber.native_controller.transcribe_whisperx",
        fake_transcribe,
    )
    started = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Meet"},
        }
    )
    session_id = started["data"]["session_id"]
    stopped = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "b",
            "action": "stop_recording",
            "payload": {"session_id": session_id, "transcribe": True},
        }
    )
    assert stopped["ok"] is True
    assert stopped["data"]["transcription_started"] is True
    assert stopped["data"]["transcribed"] is False
    assert stopped["data"]["status"] == "transcribing"
    assert started_gate.wait(2.0)

    status = ctrl.get_status()
    assert status["status"] == "transcribing"
    assert status["meeting_dir"]

    finish_gate.set()
    assert ctrl._tx_thread is not None
    ctrl._tx_thread.join(timeout=2.0)

    done = ctrl.get_status()
    assert done["status"] == "ready"
    assert done["transcribed"] is True
    assert done["plain_transcript"].endswith("transcripcion.txt")
    assert called["profile"] == "Shipii"
    assert called["echo_stdout"] is False


def test_stop_recording_transcription_error_still_ok(controller, monkeypatch):
    ctrl, _fake = controller
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.resolve_meet_window",
        lambda **_k: X11Window(1, "Meet", 800, 600, 0, 0, "firefox"),
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.video_target_for_window",
        lambda _w, environ=None: VideoTarget(
            "window", ":1", 800, 600, window_id=1, label="w"
        ),
    )

    def boom(*_a, **_k):
        raise RuntimeError("sin GPU")

    monkeypatch.setattr(
        "meetings_transcriber.native_controller.transcribe_whisperx",
        boom,
    )
    started = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Meet"},
        }
    )
    stopped = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "b",
            "action": "stop_recording",
            "payload": {
                "session_id": started["data"]["session_id"],
                "transcribe": True,
            },
        }
    )
    assert stopped["ok"] is True
    assert stopped["data"]["transcription_started"] is True
    assert stopped["data"]["transcribed"] is False
    assert ctrl._tx_thread is not None
    ctrl._tx_thread.join(timeout=2.0)
    done = ctrl.get_status()
    assert done["status"] == "ready"
    assert done["transcribed"] is False
    assert "sin GPU" in done["transcription_error"]


def test_window_unavailable_is_explicit_error(controller, monkeypatch):
    ctrl, _fake = controller
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.resolve_meet_window",
        Mock(
            side_effect=WindowCaptureError(
                "WINDOW_CAPTURE_UNAVAILABLE",
                "No hay ventanas Firefox visibles en X11.",
            )
        ),
    )
    response = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Meet"},
        }
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "WINDOW_CAPTURE_UNAVAILABLE"
    assert "No hay ventanas Firefox" in response["error"]["message"]


def test_monitor_fallback_requires_explicit_env(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    environ = {
        "NATIVE_MESSAGING_PROFILE": "Shipii",
        "NATIVE_VIDEO_SOURCE": "monitor",
        "DISPLAY": ":1",
    }
    ctrl = NativeHostController(settings=settings, project_dir=tmp_path, environ=environ)
    fake = FakePopen()
    monkeypatch.setattr(
        "meetings_transcriber.audio.subprocess.Popen",
        lambda *_a, **_k: fake,
    )
    monkeypatch.setattr("meetings_transcriber.audio.resolve_audio_devices", lambda _s: ("sink", "mic"))
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.detect_video_codec",
        lambda *_a, **_k: "libx264",
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.resolve_monitor_video_target",
        lambda *_a, **_k: (
            VideoTarget("monitor", ":1", 1920, 1080, 0, 0, label="monitor:DP-0"),
            "libx264",
        ),
    )
    response = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Meet"},
        }
    )
    assert response["ok"] is True
    assert response["data"]["video_source"] == "monitor"


def test_shutdown_stops_orphan_ffmpeg(controller, monkeypatch):
    ctrl, fake = controller
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.resolve_meet_window",
        lambda **_k: X11Window(1, "Meet", 800, 600, 0, 0, "firefox"),
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.video_target_for_window",
        lambda _w, environ=None: VideoTarget(
            "window", ":1", 800, 600, window_id=1, label="w"
        ),
    )
    ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Meet"},
        }
    )
    ctrl.shutdown()
    assert fake.signals == [SIGINT]
    assert ctrl.get_status()["status"] in {"ready", "error"}


def test_missing_profile_env(tmp_path):
    settings = make_settings(tmp_path)
    ctrl = NativeHostController(
        settings=settings,
        project_dir=tmp_path,
        environ={"NATIVE_VIDEO_SOURCE": "window", "DISPLAY": ":1"},
    )
    response = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Meet"},
        }
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "PROFILE_NOT_CONFIGURED"


def test_start_without_env_ok_when_profile_in_payload(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    ctrl = NativeHostController(
        settings=settings,
        project_dir=tmp_path,
        environ={"NATIVE_VIDEO_SOURCE": "window", "DISPLAY": ":1"},
    )
    fake = FakePopen()
    monkeypatch.setattr(
        "meetings_transcriber.audio.subprocess.Popen",
        lambda *_a, **_k: fake,
    )
    monkeypatch.setattr("meetings_transcriber.audio.resolve_audio_devices", lambda _s: ("sink", "mic"))
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.detect_video_codec",
        lambda *_a, **_k: "libx264",
    )
    monkeypatch.setattr("meetings_transcriber.audio.validate_audio", lambda *_a, **_k: 1.0)
    monkeypatch.setattr("meetings_transcriber.audio.validate_video", lambda *_a, **_k: 1.0)
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.resolve_meet_window",
        lambda **_k: X11Window(1, "Meet", 800, 600, 0, 0, "firefox"),
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.video_target_for_window",
        lambda _w, environ=None: VideoTarget(
            "window", ":1", 800, 600, window_id=1, label="w"
        ),
    )
    response = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {
                "url": "https://meet.google.com/x",
                "title": "Meet",
                "profile": "Shipii",
            },
        }
    )
    assert response["ok"] is True
    assert response["data"]["profile"] == "Shipii"


def test_wayland_window_uses_portal_not_x11(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    environ = {
        "NATIVE_MESSAGING_PROFILE": "Shipii",
        "NATIVE_VIDEO_SOURCE": "window",
        "XDG_SESSION_TYPE": "wayland",
        "WAYLAND_DISPLAY": "wayland-0",
        "DISPLAY": ":1",
    }
    ctrl = NativeHostController(settings=settings, project_dir=tmp_path, environ=environ)
    fake = FakePopen()
    monkeypatch.setattr(
        "meetings_transcriber.audio.subprocess.Popen",
        lambda *_a, **_k: fake,
    )
    monkeypatch.setattr("meetings_transcriber.audio.resolve_audio_devices", lambda _s: ("sink", "mic"))
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.detect_video_codec",
        lambda *_a, **_k: "libx264",
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.ensure_gst_pipewire_available",
        lambda: None,
    )
    handle = Mock()
    handle.close = Mock()
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.open_portal_capture",
        lambda kind, environ=None: handle if kind == "window" else (_ for _ in ()).throw(AssertionError(kind)),
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.video_target_from_portal",
        lambda _handle: VideoTarget(
            source="window",
            display="",
            width=1280,
            height=720,
            backend="portal",
            pipewire_node_id=99,
            label="portal:window:node=99",
        ),
    )
    # Evitar que RecordingSession intente gst real: forzar backend x11 tras resolver.
    # En su lugar mockeamos _start_portal_pipeline.
    monkeypatch.setattr(
        "meetings_transcriber.audio.RecordingSession._start_portal_pipeline",
        lambda self, sink, microphone, target, codec: setattr(
            self, "_process", fake
        ),
    )
    monkeypatch.setattr("meetings_transcriber.audio.validate_audio", lambda *_a, **_k: 1.0)
    monkeypatch.setattr("meetings_transcriber.audio.validate_video", lambda *_a, **_k: 1.0)

    response = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "w1",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/abc-defg-hij", "title": "Standup"},
        }
    )
    assert response["ok"] is True
    assert response["data"]["video_source"] == "window"
    assert "portal" in response["data"]["video_label"]


def test_ffmpeg_error_on_bad_return_code(controller, monkeypatch):
    ctrl, fake = controller

    def boom_wait():
        fake.returncode = 187
        return 187

    fake.wait = boom_wait  # type: ignore[method-assign]
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.resolve_meet_window",
        lambda **_k: X11Window(1, "Meet", 800, 600, 0, 0, "firefox"),
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.video_target_for_window",
        lambda _w, environ=None: VideoTarget(
            "window", ":1", 800, 600, window_id=1, label="w"
        ),
    )
    started = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Meet"},
        }
    )
    assert started["ok"] is True
    stopped = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "b",
            "action": "stop_recording",
            "payload": {"session_id": started["data"]["session_id"]},
        }
    )
    assert stopped["ok"] is False
    assert stopped["error"]["code"] == "FFMPEG_ERROR"


def test_record_meet_event_persists_jsonl(controller, monkeypatch):
    ctrl, _fake = controller
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.resolve_meet_window",
        lambda **_k: X11Window(1, "Meet", 800, 600, 0, 0, "firefox"),
    )
    monkeypatch.setattr(
        "meetings_transcriber.native_controller.video_target_for_window",
        lambda _w, environ=None: VideoTarget(
            "window", ":1", 800, 600, window_id=1, label="w"
        ),
    )
    started = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "a",
            "action": "start_recording",
            "payload": {"url": "https://meet.google.com/x", "title": "Meet"},
        }
    )
    assert started["ok"] is True
    session_id = started["data"]["session_id"]
    meeting_dir = Path(started["data"]["meeting_dir"])
    assert (meeting_dir / "session.json").is_file()

    recorded = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "e1",
            "action": "record_meet_event",
            "payload": {
                "session_id": session_id,
                "event_type": "active_speaker_changed",
                "timestamp_epoch_ms": 1_700_000_000_000,
                "display_name": "Nacho",
                "participant_key": "dom:nacho",
                "confidence": 0.7,
                "source": "dom_speaking_attr",
            },
        }
    )
    assert recorded["ok"] is True
    assert recorded["data"]["recorded"] is True
    events_path = meeting_dir / "meet_events.jsonl"
    assert events_path.is_file()
    assert "Nacho" in events_path.read_text(encoding="utf-8")

    wrong = ctrl.handle(
        {
            "protocol_version": 1,
            "request_id": "e2",
            "action": "record_meet_event",
            "payload": {
                "session_id": "other",
                "event_type": "participant_joined",
                "timestamp_epoch_ms": 1,
            },
        }
    )
    assert wrong["ok"] is False
    assert wrong["error"]["code"] == "NO_SESSION"
