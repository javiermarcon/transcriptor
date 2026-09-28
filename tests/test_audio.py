from pathlib import Path
from signal import SIGINT
from unittest.mock import Mock

import pytest

from meetings_transcriber.audio import (
    Monitor,
    build_ffmpeg_command,
    command_output,
    detect_video_codec,
    ffprobe_duration,
    parse_xrandr_output,
    record_meeting,
    resolve_audio_devices,
    resolve_monitor,
    resolve_video_capture,
    validate_audio,
    validate_video,
)


def completed(stdout: str):
    result = Mock()
    result.stdout = stdout
    return result


XRANDR_OUTPUT = """\
Screen 0: minimum 8 x 8, current 4480 x 1440, maximum 32767 x 32767
DP-0 connected 1920x1080+0+360 (normal left inverted right x axis y axis) 598mm x 336mm
DP-1 connected primary 2560x1440+1920+0 (normal left inverted right x axis y axis) 597mm x 336mm
HDMI-0 disconnected (normal left inverted right x axis y axis)
"""


def test_parse_xrandr_output_reads_outputs_and_positive_offsets():
    monitors = parse_xrandr_output(XRANDR_OUTPUT)

    assert monitors == [
        Monitor("DP-0", True, False, 1920, 1080, 0, 360),
        Monitor("DP-1", True, True, 2560, 1440, 1920, 0),
        Monitor("HDMI-0", False, False),
    ]


def test_resolve_monitor_selects_primary():
    monitor = resolve_monitor("primary", parse_xrandr_output(XRANDR_OUTPUT))
    assert monitor.name == "DP-1"
    assert (monitor.width, monitor.height, monitor.offset_x, monitor.offset_y) == (
        2560,
        1440,
        1920,
        0,
    )


def test_resolve_monitor_selects_explicit_name():
    assert resolve_monitor("DP-0", parse_xrandr_output(XRANDR_OUTPUT)).name == "DP-0"


def test_resolve_monitor_rejects_missing_output():
    with pytest.raises(ValueError, match="salida inexistente"):
        resolve_monitor("DP-9", parse_xrandr_output(XRANDR_OUTPUT))


def test_resolve_monitor_rejects_disconnected_output():
    with pytest.raises(ValueError, match="está desconectada"):
        resolve_monitor("HDMI-0", parse_xrandr_output(XRANDR_OUTPUT))


def test_resolve_monitor_rejects_missing_primary():
    with pytest.raises(ValueError, match="ningún monitor conectado como primary"):
        resolve_monitor("primary", [Monitor("DP-0", True, False, 1920, 1080, 0, 0)])


def test_resolve_monitor_rejects_invalid_geometry():
    with pytest.raises(ValueError, match="Geometría inválida"):
        resolve_monitor("DP-0", [Monitor("DP-0", True, False)])


def test_resolve_video_capture_requires_display(tmp_path):
    from meetings_transcriber.config import Settings

    settings = Settings(
        tmp_path, None, None, None, "large-v3", 2, 4, "cpu", "int8", 0.7, 2.0,
        "pyannote", 0.5, 0.363, 30, None, None, record_video=True,
    )
    with pytest.raises(ValueError, match="DISPLAY no está definido"):
        resolve_video_capture(settings, environ={})


def test_detect_video_codec_prefers_nvenc():
    runner = Mock(return_value=completed(" V..... h264_nvenc NVIDIA NVENC H.264 encoder\n"))
    assert detect_video_codec(runner) == "h264_nvenc"


def test_detect_video_codec_falls_back_to_libx264():
    runner = Mock(return_value=completed(" V..... libx264 libx264 H.264 encoder\n"))
    assert detect_video_codec(runner) == "libx264"


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
    assert command.count("-map") == 3
    assert "x11grab" not in command
    assert "[mezcla]" in command


def test_build_ffmpeg_command_with_video_maps_monitor_and_mixed_audio(tmp_path):
    from meetings_transcriber.config import Settings
    from meetings_transcriber.profiles import run_paths_for_directory

    settings = Settings(
        tmp_path, None, None, None, "large-v3", 2, 4, "cpu", "int8", 0.7, 2.0,
        "pyannote", 0.5, 0.363, 30, "sink", "microphone",
        record_video=True, video_monitor="primary", video_fps=10,
    )
    paths = run_paths_for_directory(tmp_path)
    monitor = Monitor("DP-1", True, True, 2560, 1440, 1920, 0)

    command = build_ffmpeg_command(
        settings,
        paths,
        "sink",
        "microphone",
        display=":1.0",
        monitor=monitor,
        video_codec="h264_nvenc",
    )
    filters = command[command.index("-filter_complex") + 1]

    assert command.count("-thread_queue_size") == 3
    assert command.count("-map") == 5
    assert "x11grab" in command
    assert "2560x1440" in command
    assert ":1.0+1920,0" in command
    assert "-draw_mouse" in command
    assert "2:v:0" in command
    assert "[mezcla_video]" in command
    assert "asplit=2[mezcla_wav][mezcla_video]" in filters
    assert str(paths.system_audio) in command
    assert str(paths.microphone_audio) in command
    assert str(paths.mixed_audio) in command
    assert str(paths.video) in command
    assert "h264_nvenc" in command
    assert "aac" in command
    assert "yuv420p" in command


def test_build_ffmpeg_command_uses_low_cpu_libx264_options(tmp_path):
    from meetings_transcriber.config import Settings
    from meetings_transcriber.profiles import run_paths_for_directory

    settings = Settings(
        tmp_path, None, None, None, "large-v3", 2, 4, "cpu", "int8", 0.7, 2.0,
        "pyannote", 0.5, 0.363, 30, "sink", "microphone", record_video=True,
    )
    command = build_ffmpeg_command(
        settings,
        run_paths_for_directory(tmp_path),
        "sink",
        "microphone",
        display=":0",
        monitor=Monitor("DP-0", True, True, 1920, 1080, 0, 0),
        video_codec="libx264",
    )

    assert "libx264" in command
    assert "ultrafast" in command
    assert "-crf" in command


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


def test_record_meeting_audio_only_does_not_resolve_video(tmp_path, monkeypatch):
    from meetings_transcriber.config import Settings
    from meetings_transcriber.profiles import run_paths_for_directory

    settings = Settings(
        tmp_path, None, None, None, "large-v3", 2, 4, "cpu", "int8", 0.7, 2.0,
        "pyannote", 0.5, 0.363, 30, "sink", "microphone", record_video=False,
    )
    fake_process = FakePopen([0])
    monkeypatch.setattr(
        "meetings_transcriber.audio.resolve_video_capture",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no debe usar X11")),
    )
    monkeypatch.setattr(
        "meetings_transcriber.audio.subprocess.Popen", lambda *_args, **_kwargs: fake_process
    )
    monkeypatch.setattr("meetings_transcriber.audio.validate_audio", lambda *_args: 1.0)

    assert record_meeting(settings, run_paths_for_directory(tmp_path)) == 0


def test_record_meeting_video_validates_all_outputs(tmp_path, monkeypatch):
    from meetings_transcriber.config import Settings
    from meetings_transcriber.profiles import run_paths_for_directory

    settings = Settings(
        tmp_path, None, None, None, "large-v3", 2, 4, "cpu", "int8", 0.7, 2.0,
        "pyannote", 0.5, 0.363, 30, "sink", "microphone", record_video=True,
    )
    paths = run_paths_for_directory(tmp_path)
    fake_process = FakePopen([0])
    validated_audio = []
    validated_video = []
    monkeypatch.setattr(
        "meetings_transcriber.audio.resolve_video_capture",
        lambda _settings: (
            ":0",
            Monitor("DP-0", True, True, 1920, 1080, 0, 0),
            "libx264",
        ),
    )
    monkeypatch.setattr(
        "meetings_transcriber.audio.subprocess.Popen", lambda *_args, **_kwargs: fake_process
    )
    monkeypatch.setattr(
        "meetings_transcriber.audio.validate_audio",
        lambda path: validated_audio.append(path) or 1.0,
    )
    monkeypatch.setattr(
        "meetings_transcriber.audio.validate_video",
        lambda path: validated_video.append(path) or 1.0,
    )

    assert record_meeting(settings, paths) == 0
    assert validated_audio == [paths.system_audio, paths.microphone_audio, paths.mixed_audio]
    assert validated_video == [paths.video]


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


def test_validate_video_requires_readable_audio_and_video_streams(tmp_path):
    video = tmp_path / "reunion.mp4"
    video.write_bytes(b"mp4")
    runner = Mock(
        return_value=completed(
            '{"format": {"duration": "12.5"}, '
            '"streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}'
        )
    )

    assert validate_video(video, runner) == 12.5
    runner.assert_called_once_with(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type", "-of", "json", str(video),
        ],
        check=True,
        text=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    ("streams", "message"),
    [
        ([{"codec_type": "audio"}], "no contiene un stream de video"),
        ([{"codec_type": "video"}], "no contiene un stream de audio"),
    ],
)
def test_validate_video_rejects_missing_required_stream(tmp_path, streams, message):
    import json

    video = tmp_path / "reunion.mp4"
    video.write_bytes(b"mp4")
    runner = Mock(
        return_value=completed(json.dumps({"format": {"duration": "1.0"}, "streams": streams}))
    )

    with pytest.raises(ValueError, match=message):
        validate_video(video, runner)


def test_validate_video_rejects_empty_file(tmp_path):
    video = tmp_path / "reunion.mp4"
    video.touch()
    with pytest.raises(ValueError, match="Video inexistente o vacío"):
        validate_video(video)
