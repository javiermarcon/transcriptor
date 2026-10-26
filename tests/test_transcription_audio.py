from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from meetings_transcriber.profiles import run_paths_for_directory
from meetings_transcriber.transcription_audio import (
    demux_mp4_audio_to_wav,
    mp4_has_audio_stream,
    prepare_transcription_audio,
)


def test_mp4_has_audio_stream_reads_ffprobe(tmp_path):
    assert mp4_has_audio_stream(tmp_path / "missing.mp4") is False

    path = tmp_path / "v.mp4"
    path.write_bytes(b"x")

    def runner(command, check=False, text=True, capture_output=True):
        return Mock(returncode=0, stdout="audio\n", stderr="")

    assert mp4_has_audio_stream(path, runner=runner) is True

    def no_audio(command, check=False, text=True, capture_output=True):
        return Mock(returncode=0, stdout="", stderr="")

    assert mp4_has_audio_stream(path, runner=no_audio) is False


def test_prepare_prefers_mp4_demux(tmp_path):
    meeting = tmp_path / "Reunion_x"
    meeting.mkdir()
    paths = run_paths_for_directory(meeting)
    paths.video.write_bytes(b"fake-mp4-with-audio")
    paths.mixed_audio.write_bytes(b"RIFF")

    def runner(command, check=False, text=True, capture_output=True):
        cmd = list(command)
        if cmd[0] == "ffprobe":
            return Mock(returncode=0, stdout="audio\n", stderr="")
        if cmd[0] == "ffmpeg":
            assert "-map" in cmd and "0:a:0" in cmd and "-vn" in cmd
            out = Path(cmd[-1])
            out.write_bytes(b"RIFFWAV")
            return Mock(returncode=0, stdout="", stderr="")
        return Mock(returncode=1, stdout="", stderr="bad")

    audio, source = prepare_transcription_audio(paths, runner=runner)
    assert source == "mp4_demux"
    assert audio == paths.transcription_audio
    assert audio.is_file()
    meta = json.loads(paths.transcription_audio_meta.read_text(encoding="utf-8"))
    assert meta["source"] == "mp4_demux"


def test_prepare_falls_back_to_mixed_wav(tmp_path):
    meeting = tmp_path / "Reunion_y"
    meeting.mkdir()
    paths = run_paths_for_directory(meeting)
    paths.mixed_audio.write_bytes(b"RIFF")
    # Sin video

    audio, source = prepare_transcription_audio(paths)
    assert source == "mixed_wav"
    assert audio == paths.mixed_audio
    meta = json.loads(paths.transcription_audio_meta.read_text(encoding="utf-8"))
    assert meta["source"] == "mixed_wav"


def test_prepare_falls_back_when_mp4_has_no_audio(tmp_path):
    meeting = tmp_path / "Reunion_z"
    meeting.mkdir()
    paths = run_paths_for_directory(meeting)
    paths.video.write_bytes(b"mp4")
    paths.mixed_audio.write_bytes(b"RIFF")

    def runner(command, check=False, text=True, capture_output=True):
        if next(iter(command)) == "ffprobe":
            return Mock(returncode=0, stdout="", stderr="")
        return Mock(returncode=1, stdout="", stderr="x")

    audio, source = prepare_transcription_audio(paths, runner=runner)
    assert source == "mixed_wav"
    assert audio == paths.mixed_audio


def test_prepare_errors_without_any_audio(tmp_path):
    meeting = tmp_path / "Reunion_empty"
    meeting.mkdir()
    paths = run_paths_for_directory(meeting)
    with pytest.raises(FileNotFoundError, match="No hay audio"):
        prepare_transcription_audio(paths)


def test_demux_failure_raises(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    out = tmp_path / "o.wav"

    def runner(command, check=False, text=True, capture_output=True):
        return Mock(returncode=1, stdout="", stderr="demux fail")

    with pytest.raises(RuntimeError, match="demuxear"):
        demux_mp4_audio_to_wav(video, out, runner=runner)
