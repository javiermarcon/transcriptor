from unittest.mock import Mock

import pytest

from meetings_transcriber.window_capture import (
    WindowCaptureError,
    is_meet_url,
    list_candidate_windows,
    resolve_meet_window,
    video_target_for_window,
)


def completed(stdout: str = "", returncode: int = 0):
    result = Mock()
    result.stdout = stdout
    result.stderr = ""
    result.returncode = returncode
    return result


TREE = """\
  0x2000001 "Meet standup - Google Meet": ("Navigator" "firefox")  1280x720+10+20
  0x2000002 "Other": ("Navigator" "firefox")  800x600+0+0
  0x2000003 "tiny": ("Navigator" "firefox")  20x20+0+0
"""


def test_is_meet_url():
    assert is_meet_url("https://meet.google.com/abc-defg-hij")
    assert not is_meet_url("http://meet.google.com/abc")
    assert not is_meet_url("https://example.com/")


def test_list_candidate_windows_filters_firefox_visible(monkeypatch):
    props = {
        "0x2000001": (
            'WM_CLASS(STRING) = "Navigator", "firefox"\n'
            '_NET_WM_NAME(UTF8_STRING) = "Meet standup - Google Meet"\n'
        ),
        "0x2000002": (
            'WM_CLASS(STRING) = "Navigator", "firefox"\n'
            '_NET_WM_NAME(UTF8_STRING) = "Other"\n'
            "_NET_WM_STATE(ATOM) = _NET_WM_STATE_HIDDEN\n"
        ),
        "0x2000003": 'WM_CLASS(STRING) = "Navigator", "firefox"\n',
    }

    def runner(command, check=False, text=True, capture_output=True):
        if command[:2] == ["xwininfo", "-root"]:
            return completed(TREE)
        if command[0] == "xprop":
            wid = command[2]
            return completed(props.get(wid, ""))
        raise AssertionError(command)

    windows = list_candidate_windows(runner)
    assert len(windows) == 1
    assert windows[0].window_id == 0x2000001
    assert "Meet standup" in windows[0].title


def test_resolve_meet_window_matches_title():
    def runner(command, check=False, text=True, capture_output=True):
        if command[:2] == ["xwininfo", "-root"]:
            return completed(TREE)
        if command[0] == "xprop":
            wid = command[2]
            if wid == "0x2000001":
                return completed(
                    'WM_CLASS(STRING) = "Navigator", "firefox"\n'
                    '_NET_WM_NAME(UTF8_STRING) = "Meet standup - Google Meet"\n'
                )
            if wid == "0x2000002":
                return completed(
                    'WM_CLASS(STRING) = "Navigator", "firefox"\n'
                    '_NET_WM_NAME(UTF8_STRING) = "Other"\n'
                    "_NET_WM_STATE(ATOM) = _NET_WM_STATE_HIDDEN\n"
                )
            return completed('WM_CLASS(STRING) = "Navigator", "firefox"\n')
        raise AssertionError(command)

    window = resolve_meet_window(
        url="https://meet.google.com/abc-defg-hij",
        title="Meet standup",
        runner=runner,
        environ={"DISPLAY": ":1"},
    )
    assert window.window_id == 0x2000001
    target = video_target_for_window(window, environ={"DISPLAY": ":1"})
    assert target.source == "window"
    assert target.window_id == 0x2000001


def test_resolve_meet_window_errors_without_candidates():
    def runner(command, check=False, text=True, capture_output=True):
        if command[:2] == ["xwininfo", "-root"]:
            return completed("Screen 0\n")
        raise AssertionError(command)

    with pytest.raises(WindowCaptureError, match="No hay ventanas Firefox") as exc:
        resolve_meet_window(
            url="https://meet.google.com/abc-defg-hij",
            title="Meet standup",
            runner=runner,
            environ={"DISPLAY": ":1"},
        )
    assert exc.value.code == "WINDOW_CAPTURE_UNAVAILABLE"


def test_resolve_meet_window_rejects_title_only_without_firefox_class():
    tree = '  0x3000001 "Meet standup": ("Chromium" "chromium")  1280x720+0+0\n'

    def runner(command, check=False, text=True, capture_output=True):
        if command[:2] == ["xwininfo", "-root"]:
            return completed(tree)
        if command[0] == "xprop":
            return completed('WM_CLASS(STRING) = "Chromium", "chromium"\n')
        raise AssertionError(command)

    with pytest.raises(WindowCaptureError) as exc:
        resolve_meet_window(
            url="https://meet.google.com/abc-defg-hij",
            title="Meet standup",
            runner=runner,
            environ={"DISPLAY": ":1"},
        )
    assert exc.value.code == "WINDOW_CAPTURE_UNAVAILABLE"


def test_resolve_meet_window_invalid_url():
    with pytest.raises(WindowCaptureError) as exc:
        resolve_meet_window(url="https://example.com", title="x", environ={"DISPLAY": ":1"})
    assert exc.value.code == "INVALID_MEET_URL"
