from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from meetings_transcriber.cli import build_parser
from meetings_transcriber.config import Settings
from meetings_transcriber.models import ProfilePaths, RunPaths
from meetings_transcriber.transcription import build_whisperx_command, import_existing_audio


def make_settings(tmp_path):
    executable = tmp_path / "whisperx"
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)
    return Settings(
        base_dir=tmp_path,
        whisperx_bin=executable,
        whisper_ctranslate2_bin=None,
        hf_token="secret",
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


def test_command_uses_short_prompt_and_hotwords(tmp_path):
    prompt = tmp_path / "initial_prompt.txt"
    prompt.write_text("Conversación en español rioplatense de Argentina.", encoding="utf-8")
    hotwords = tmp_path / "hotwords.txt"
    hotwords.write_text("Shipii\nFulfillment\nTienda Nube\n", encoding="utf-8")
    profile = ProfilePaths("Shipii", tmp_path, prompt, hotwords)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    paths = RunPaths(
        run_dir,
        run_dir / "sistema.wav",
        run_dir / "microfono.wav",
        run_dir / "reunion_mezclada.wav",
        run_dir / "reunion_mezclada.json",
        run_dir / "transcripcion.txt",
        run_dir / "transcripcion_speakers.txt",
    )
    command = build_whisperx_command(make_settings(tmp_path), profile, paths)
    assert command[command.index("--initial_prompt") + 1] == "Conversación en español rioplatense de Argentina."
    assert command[command.index("--hotwords") + 1] == "Shipii, Fulfillment, Tienda Nube"
    assert command[command.index("--condition_on_previous_text") + 1] == "False"
    assert command[command.index("--print_progress") + 1] == "True"


def test_command_includes_quality_and_anti_hallucination_flags(tmp_path):
    settings = make_settings(tmp_path)
    settings = Settings(
        **{
            **settings.__dict__,
            "temperature": 0.0,
            "best_of": 5,
            "beam_size": 8,
            "patience": 1.2,
            "length_penalty": 1.0,
            "suppress_tokens": "-1",
            "suppress_numerals": True,
            "temperature_increment_on_fallback": 0.2,
            "compression_ratio_threshold": 2.2,
            "logprob_threshold": -0.8,
            "no_speech_threshold": 0.7,
            "min_speakers": 2,
            "max_speakers": 4,
            "condition_on_previous_text": False,
        }
    )
    prompt = tmp_path / "initial_prompt.txt"
    prompt.write_text("Hola", encoding="utf-8")
    hotwords = tmp_path / "hotwords.txt"
    hotwords.write_text("Shipii", encoding="utf-8")
    profile = ProfilePaths("Shipii", tmp_path, prompt, hotwords)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    paths = RunPaths(
        run_dir,
        run_dir / "sistema.wav",
        run_dir / "microfono.wav",
        run_dir / "reunion_mezclada.wav",
        run_dir / "reunion_mezclada.json",
        run_dir / "transcripcion.txt",
        run_dir / "transcripcion_speakers.txt",
    )

    command = build_whisperx_command(settings, profile, paths)

    assert command[command.index("--beam_size") + 1] == "8"
    assert command[command.index("--patience") + 1] == "1.2"
    assert command[command.index("--length_penalty") + 1] == "1.0"
    assert command[command.index("--no_speech_threshold") + 1] == "0.7"
    assert command[command.index("--logprob_threshold") + 1] == "-0.8"
    assert command[command.index("--compression_ratio_threshold") + 1] == "2.2"
    assert command[command.index("--min_speakers") + 1] == "2"
    assert command[command.index("--max_speakers") + 1] == "4"
    assert "--suppress_numerals" in command


def test_command_omits_optional_speaker_bounds_and_length_penalty(tmp_path):
    settings = make_settings(tmp_path)
    prompt = tmp_path / "initial_prompt.txt"
    prompt.write_text("Hola", encoding="utf-8")
    hotwords = tmp_path / "hotwords.txt"
    hotwords.write_text("", encoding="utf-8")
    profile = ProfilePaths("Shipii", tmp_path, prompt, hotwords)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    paths = RunPaths(
        run_dir,
        run_dir / "sistema.wav",
        run_dir / "microfono.wav",
        run_dir / "reunion_mezclada.wav",
        run_dir / "reunion_mezclada.json",
        run_dir / "transcripcion.txt",
        run_dir / "transcripcion_speakers.txt",
    )

    command = build_whisperx_command(settings, profile, paths)

    assert "--min_speakers" not in command
    assert "--max_speakers" not in command
    assert "--length_penalty" not in command
    assert "--suppress_numerals" not in command


def test_cli_accepts_multiple_audio_flags():
    parser = build_parser()
    args = parser.parse_args([
        "--profile",
        "Shipii",
        "--audio",
        "one.ogg",
        "two.ogg",
        "--audio",
        "three.ogg",
    ])
    assert len(args.audio) == 2
    assert args.audio[0] == [Path("one.ogg"), Path("two.ogg")]
    assert args.audio[1] == [Path("three.ogg")]


def test_import_existing_audio_concatenates_multiple_sources(tmp_path):
    src1 = tmp_path / "one.ogg"
    src2 = tmp_path / "two.ogg"
    src1.write_text("audio1", encoding="utf-8")
    src2.write_text("audio2", encoding="utf-8")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    paths = RunPaths(
        run_dir,
        run_dir / "sistema.wav",
        run_dir / "microfono.wav",
        run_dir / "reunion_mezclada.wav",
        run_dir / "reunion_mezclada.json",
        run_dir / "transcripcion.txt",
        run_dir / "transcripcion_speakers.txt",
    )

    fake_result = Mock()
    fake_result.returncode = 0
    with patch("meetings_transcriber.transcription.subprocess.run", fake_result) as mock_run:
        import_existing_audio([src1, src2], paths)

    command = mock_run.call_args.args[0]
    assert command[0:4] == ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    assert command.count("-thread_queue_size") == 2
    assert command.count("1024") == 2
    assert str(src1) in command
    assert str(src2) in command
    assert str(paths.mixed_audio) in command


def test_build_whisperx_command_requires_whisperx_bin(tmp_path):
    from meetings_transcriber.config import Settings
    from meetings_transcriber.models import ProfilePaths, RunPaths

    prompt = tmp_path / "initial_prompt.txt"
    prompt.write_text("Hola", encoding="utf-8")
    hotwords = tmp_path / "hotwords.txt"
    hotwords.write_text("Shipii", encoding="utf-8")

    settings = Settings(
        base_dir=tmp_path,
        whisperx_bin=None,
        whisper_ctranslate2_bin=None,
        hf_token="secret",
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
    profile = ProfilePaths("Shipii", tmp_path, prompt, hotwords)
    paths = RunPaths(
        tmp_path,
        tmp_path / "system.wav",
        tmp_path / "microphone.wav",
        tmp_path / "mixed.wav",
        tmp_path / "result.json",
        tmp_path / "transcription.txt",
        tmp_path / "speakers.txt",
    )

    import pytest

    with pytest.raises(RuntimeError, match="WhisperX no está disponible"):
        build_whisperx_command(settings, profile, paths)


def test_build_whisperx_command_requires_hf_token(tmp_path):
    from meetings_transcriber.config import Settings
    from meetings_transcriber.models import ProfilePaths, RunPaths

    executable = tmp_path / "whisperx"
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)
    prompt = tmp_path / "initial_prompt.txt"
    prompt.write_text("Hola", encoding="utf-8")
    hotwords = tmp_path / "hotwords.txt"
    hotwords.write_text("Shipii", encoding="utf-8")

    settings = Settings(
        base_dir=tmp_path,
        whisperx_bin=executable,
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
    profile = ProfilePaths("Shipii", tmp_path, prompt, hotwords)
    paths = RunPaths(
        tmp_path,
        tmp_path / "system.wav",
        tmp_path / "microphone.wav",
        tmp_path / "mixed.wav",
        tmp_path / "result.json",
        tmp_path / "transcription.txt",
        tmp_path / "speakers.txt",
    )

    import pytest

    with pytest.raises(RuntimeError, match="HF_TOKEN no está configurado"):
        build_whisperx_command(settings, profile, paths)


def test_run_streaming_prints_progress_and_exits_zero(monkeypatch, tmp_path, capsys):

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.stdout = [
                "Transcript: [1.00 --> 2.00]\n",
                "Transcript: [2.00 --> 3.00]\n",
            ]

        def wait(self):
            return 0

    monkeypatch.setattr("meetings_transcriber.transcription.subprocess.Popen", FakePopen)
    from meetings_transcriber.transcription import run_streaming

    run_streaming(["echo"], 5.0)
    captured = capsys.readouterr()
    assert "Progreso de audio" in captured.out


def test_run_streaming_callback_without_stdout(monkeypatch, capsys):
    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.stdout = ["Transcript: [1.00 --> 2.50]\n"]

        def wait(self):
            return 0

    monkeypatch.setattr("meetings_transcriber.transcription.subprocess.Popen", FakePopen)
    from meetings_transcriber.transcription import run_streaming

    seen = []
    run_streaming(
        ["echo"],
        5.0,
        on_progress=lambda p: seen.append(p.render()),
        echo_stdout=False,
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert seen
    assert "2.50" in seen[0] or "%" in seen[0]


def test_run_streaming_raises_on_nonzero_exit(monkeypatch):
    import pytest

    from meetings_transcriber.transcription import run_streaming

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.stdout = ["ModuleNotFoundError: No module named 'whisperx'\n"]

        def wait(self):
            return 1

    monkeypatch.setattr("meetings_transcriber.transcription.subprocess.Popen", FakePopen)

    with pytest.raises(RuntimeError, match=r"WhisperX falló \(código 1\)"):
        run_streaming(["echo"], 10.0)


def test_redact_secrets_hides_hf_token():
    from meetings_transcriber.transcription import redact_secrets

    raw = "cmd --hf_token hf_SECRETtokenEXAMPLE1234567890ABCD boom"
    out = redact_secrets(raw)
    assert "hf_SECRET" not in out
    assert "--hf_token ***" in out or "hf_***" in out


def test_find_generated_json_returns_existing_result(tmp_path):
    from meetings_transcriber.models import RunPaths

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result_path = run_dir / "reunion_mezclada.json"
    result_path.write_text("{}", encoding="utf-8")
    paths = RunPaths(
        run_dir,
        run_dir / "system.wav",
        run_dir / "microphone.wav",
        run_dir / "mixed.wav",
        result_path,
        run_dir / "transcription.txt",
        run_dir / "speakers.txt",
    )

    from meetings_transcriber.transcription import find_generated_json
    assert find_generated_json(paths) == result_path


def test_find_generated_json_raises_when_no_json(tmp_path):
    from meetings_transcriber.models import RunPaths

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    paths = RunPaths(
        run_dir,
        run_dir / "system.wav",
        run_dir / "microphone.wav",
        run_dir / "mixed.wav",
        run_dir / "reunion_mezclada.json",
        run_dir / "transcription.txt",
        run_dir / "speakers.txt",
    )

    import pytest

    from meetings_transcriber.transcription import find_generated_json

    with pytest.raises(FileNotFoundError, match="WhisperX terminó sin generar un JSON"):
        find_generated_json(paths)


def test_import_existing_audio_single_source_copies_file(tmp_path, monkeypatch):

    from meetings_transcriber.models import RunPaths

    src = tmp_path / "one.ogg"
    src.write_text("audio1", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    paths = RunPaths(
        run_dir,
        run_dir / "system.wav",
        run_dir / "microphone.wav",
        run_dir / "reunion_mezclada.wav",
        run_dir / "reunion_mezclada.json",
        run_dir / "transcripcion.txt",
        run_dir / "transcripcion_speakers.txt",
    )

    copied = []

    def fake_copy(src_path, dest_path):
        copied.append((src_path, dest_path))

    monkeypatch.setattr("meetings_transcriber.transcription.shutil.copy2", fake_copy)
    monkeypatch.setattr("meetings_transcriber.transcription.subprocess.run", lambda *args, **kwargs: None)
    from meetings_transcriber.transcription import import_existing_audio

    import_existing_audio([src], paths)
    assert copied == [(src, paths.mixed_audio)]


def test_transcribe_whisperx_calls_pipeline(tmp_path, monkeypatch):
    from meetings_transcriber.config import Settings
    from meetings_transcriber.models import ProfilePaths, RunPaths
    
    settings = Settings(
        base_dir=tmp_path,
        whisperx_bin=tmp_path / "whisperx",
        whisper_ctranslate2_bin=None,
        hf_token="secret",
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
    prompt = tmp_path / "initial_prompt.txt"
    prompt.write_text("hola", encoding="utf-8")
    hotwords = tmp_path / "hotwords.txt"
    hotwords.write_text("Shipii", encoding="utf-8")
    profile = ProfilePaths("Shipii", tmp_path, prompt, hotwords)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    paths = RunPaths(
        run_dir,
        run_dir / "system.wav",
        run_dir / "microphone.wav",
        run_dir / "mixed.wav",
        run_dir / "reunion_mezclada.json",
        run_dir / "transcripcion.txt",
        run_dir / "transcripcion_speakers.txt",
    )

    monkeypatch.setattr(
        "meetings_transcriber.transcription.prepare_transcription_audio",
        lambda *_a, **_k: (paths.mixed_audio, "mixed_wav"),
    )
    monkeypatch.setattr("meetings_transcriber.transcription.ffprobe_duration", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr("meetings_transcriber.transcription.run_streaming", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("meetings_transcriber.transcription.find_generated_json", lambda *_args, **_kwargs: paths.json_result)
    monkeypatch.setattr("meetings_transcriber.transcription.process_whisperx_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "meetings_transcriber.transcription.write_attributed_transcript",
        lambda *_args, **_kwargs: None,
    )

    paths.json_result.write_text("{}", encoding="utf-8")

    from meetings_transcriber.transcription import transcribe_whisperx
    transcribe_whisperx(settings, profile, paths)


def test_find_generated_json_returns_most_recent_candidate(tmp_path):
    from meetings_transcriber.models import RunPaths

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result_path = run_dir / "reunion_mezclada.json"
    result_path.touch()
    candidate_old = run_dir / "old.json"
    candidate_old.write_text("{}", encoding="utf-8")
    candidate_new = run_dir / "new.json"
    candidate_new.write_text("{}", encoding="utf-8")

    paths = RunPaths(
        run_dir,
        run_dir / "system.wav",
        run_dir / "microphone.wav",
        run_dir / "mixed.wav",
        result_path,
        run_dir / "transcription.txt",
        run_dir / "speakers.txt",
    )

    from meetings_transcriber.transcription import find_generated_json
    assert find_generated_json(paths) == candidate_new


def test_import_existing_audio_raises_when_source_missing(tmp_path):
    from meetings_transcriber.models import RunPaths
    from meetings_transcriber.transcription import import_existing_audio

    missing = tmp_path / "missing.ogg"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    paths = RunPaths(
        run_dir,
        run_dir / "system.wav",
        run_dir / "microphone.wav",
        run_dir / "reunion_mezclada.wav",
        run_dir / "reunion_mezclada.json",
        run_dir / "transcripcion.txt",
        run_dir / "transcripcion_speakers.txt",
    )

    with pytest.raises(FileNotFoundError):
        import_existing_audio([missing], paths)
