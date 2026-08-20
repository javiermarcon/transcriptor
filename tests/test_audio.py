from pathlib import Path
from signal import SIGINT
from unittest.mock import Mock

import pytest

from meetings_transcriber.audio import (
    build_ffmpeg_command,
    command_output,
    ffprobe_duration,
    record_meeting,
    resolve_audio_devices,
    validate_audio,
)


def completed(stdout: str):
    result = Mock()
    result.stdout = stdout
    return result


def test_ffprobe_duration():
    runner = Mock(return_value=completed("123.5\n"))
    assert ffprobe_duration(Path("audio.wav"), runner) == 123.5


def test_ffprobe_duration_rejects_zero():
    runner = Mock(return_value=completed("0.0\n"))
    with pytest.raises(ValueError, match="Duración inválida"):
        ffprobe_duration(Path("audio.wav"), runner)


def test_validate_audio_rejects_empty(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.touch()
    with pytest.raises(ValueError, match="Audio inexistente o vacío"):
        validate_audio(audio)


def test_validate_audio_rejects_missing():
    with pytest.raises(ValueError, match="Audio inexistente o vacío"):
        validate_audio(Path("missing.wav"))


def test_build_ffmpeg_command_contains_audio_paths(tmp_path):
    from meetings_transcriber.config import Settings
    from meetings_transcriber.models import RunPaths

    settings = Settings(
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
        sink="default",
        microphone="default",
    )
    paths = RunPaths(
        tmp_path,
        tmp_path / "sistema.wav",
        tmp_path / "microfono.wav",
        tmp_path / "reunion_mezclada.wav",
        tmp_path / "reunion_mezclada.json",
        tmp_path / "transcripcion.txt",
        tmp_path / "transcripcion_speakers.txt",
    )
    command = build_ffmpeg_command(settings, paths, "sink", "microphone")
    assert "-filter_complex" in command
    assert command.count("-thread_queue_size") == 2
    assert command.count("1024") == 2
    assert str(paths.system_audio) in command
    assert str(paths.microphone_audio) in command
    assert str(paths.mixed_audio) in command


class FakePopen:
    def __init__(self, return_codes):
        self.return_codes = iter(return_codes)
        self.signals = []
        self.stdout = None

    def wait(self):
        value = next(self.return_codes)
        if isinstance(value, BaseException):
            raise value
        return value

    def send_signal(self, signal):
        self.signals.append(signal)


def test_record_meeting_handles_keyboardinterrupt(tmp_path, monkeypatch):
    from meetings_transcriber.config import Settings
    from meetings_transcriber.models import RunPaths

    settings = Settings(
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
    )
    paths = RunPaths(
        tmp_path,
        tmp_path / "sistema.wav",
        tmp_path / "microfono.wav",
        tmp_path / "reunion_mezclada.wav",
        tmp_path / "reunion_mezclada.json",
        tmp_path / "transcripcion.txt",
        tmp_path / "transcripcion_speakers.txt",
    )

    fake_process = FakePopen([KeyboardInterrupt(), 0])
    monkeypatch.setattr("meetings_transcriber.audio.resolve_audio_devices", lambda settings: ("sink", "microphone"))
    monkeypatch.setattr("meetings_transcriber.audio.subprocess.Popen", lambda *_args, **_kwargs: fake_process)
    monkeypatch.setattr("meetings_transcriber.audio.validate_audio", lambda *_args, **_kwargs: 1)

    assert record_meeting(settings, paths) == 0
    assert fake_process.signals == [SIGINT]


def test_record_meeting_errors_on_unexpected_return(tmp_path, monkeypatch):
    from meetings_transcriber.config import Settings
    from meetings_transcriber.models import RunPaths

    settings = Settings(
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
    )
    paths = RunPaths(
        tmp_path,
        tmp_path / "sistema.wav",
        tmp_path / "microfono.wav",
        tmp_path / "reunion_mezclada.wav",
        tmp_path / "reunion_mezclada.json",
        tmp_path / "transcripcion.txt",
        tmp_path / "transcripcion_speakers.txt",
    )

    fake_process = FakePopen([5])
    monkeypatch.setattr("meetings_transcriber.audio.resolve_audio_devices", lambda settings: ("sink", "microphone"))
    monkeypatch.setattr("meetings_transcriber.audio.subprocess.Popen", lambda *_args, **_kwargs: fake_process)

    with pytest.raises(RuntimeError, match="FFmpeg terminó con código inesperado"):
        record_meeting(settings, paths)


def test_command_output_uses_runner():
    runner = Mock(return_value=completed("output\n"))
    assert command_output(["cmd"], runner) == "output"
    runner.assert_called_once_with(["cmd"], check=True, text=True, capture_output=True)


def test_resolve_audio_devices_queries_pulse_when_not_set(monkeypatch):
    from meetings_transcriber.config import Settings

    settings = Settings(
        base_dir=Path("/tmp"),
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
        sink=None,
        microphone=None,
    )

    def fake_runner(command, check, text, capture_output):
        assert command in (["pactl", "get-default-sink"], ["pactl", "get-default-source"])
        return completed("value\n")

    sink, microphone = resolve_audio_devices(settings, fake_runner)
    assert sink == "value"
    assert microphone == "value"


def test_validate_audio_calls_ffprobe_duration(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.write_text("audio", encoding="utf-8")

    runner = Mock(return_value=completed("12.0\n"))
    assert validate_audio(audio, runner) == 12.0
