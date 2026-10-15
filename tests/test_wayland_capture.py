from unittest.mock import Mock

import pytest

from meetings_transcriber.portal_screencast import PortalScreenCastError
from meetings_transcriber.wayland_capture import (
    PortalCaptureHandle,
    build_pipewire_gst_command,
    is_wayland_session,
    session_type,
    video_target_from_portal,
)


def test_session_type_detects_wayland_and_x11():
    assert session_type({"XDG_SESSION_TYPE": "wayland"}) == "wayland"
    assert session_type({"XDG_SESSION_TYPE": "x11"}) == "x11"
    assert session_type({"WAYLAND_DISPLAY": "wayland-0"}) == "wayland"
    assert is_wayland_session({"XDG_SESSION_TYPE": "wayland"}) is True
    assert is_wayland_session({"DISPLAY": ":1"}) is False


def test_video_target_from_portal_even_dimensions():
    handle = PortalCaptureHandle(
        kind="window",
        node_id=42,
        width=1281,
        height=721,
        session_handle="/session/1",
        process=Mock(),
    )
    target = video_target_from_portal(handle)
    assert target.backend == "portal"
    assert target.pipewire_node_id == 42
    assert target.width == 1280
    assert target.height == 720


def test_build_pipewire_gst_command_has_safe_argv(monkeypatch):
    monkeypatch.setattr(
        "meetings_transcriber.wayland_capture.shutil.which",
        lambda name: "/usr/bin/gst-launch-1.0" if name == "gst-launch-1.0" else None,
    )
    command = build_pipewire_gst_command(node_id=9, width=640, height=480, fps=10)
    assert command[0] == "gst-launch-1.0"
    assert "path=9" in command
    assert "fdsink" in command
    # Sin shell: cada token es un argumento separado.
    assert all("|" not in part for part in command)


def test_build_pipewire_gst_command_requires_gst(monkeypatch):
    monkeypatch.setattr("meetings_transcriber.wayland_capture.shutil.which", lambda _name: None)
    with pytest.raises(PortalScreenCastError, match="gst-launch"):
        build_pipewire_gst_command(node_id=1, width=64, height=64, fps=10)
