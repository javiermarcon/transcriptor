from pathlib import Path
from unittest.mock import Mock

import pytest

from meetings_transcriber.cli import build_parser, load_env_file, main
from meetings_transcriber.config import Settings
from meetings_transcriber.models import ProfilePaths, RunPaths


def make_settings(base_dir):
    return Settings(
        base_dir=base_dir,
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


def test_load_env_file_parses_exported_and_plain(tmp_path, monkeypatch):
    env_file = tmp_path / "config.env"
    env_file.write_text(
        "export TEST_VAR=1\nFOO='bar'\n# comment\n"
    )
    monkeypatch.delenv("TEST_VAR", raising=False)
    monkeypatch.delenv("FOO", raising=False)

    load_env_file(env_file)

    assert Path.home()  # sanity check to avoid lint warnings
    assert "1" == __import__("os").environ["TEST_VAR"]
    assert "bar" == __import__("os").environ["FOO"]


def test_load_env_file_does_nothing_when_file_missing(tmp_path):
    load_env_file(tmp_path / "missing.env")


def test_main_list_profiles(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: make_settings(tmp_path))

    (tmp_path / "profile1").mkdir()
    (tmp_path / "profile2").mkdir()
    (tmp_path / "ignore.txt").write_text("ignored")

    result = main(["--list-profiles", "--config", str(env_file)])

    captured = capsys.readouterr()
    assert result == 0
    assert "profile1" in captured.out
    assert "profile2" in captured.out
    assert "ignore.txt" not in captured.out


def test_main_returns_130_on_keyboardinterrupt(tmp_path, monkeypatch):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    settings = make_settings(tmp_path)
    profile = ProfilePaths(
        name="Shipii",
        directory=tmp_path,
        initial_prompt=tmp_path / "prompt.txt",
        hotwords=tmp_path / "hotwords.txt",
    )
    paths = RunPaths(
        tmp_path,
        tmp_path / "system.wav",
        tmp_path / "microphone.wav",
        tmp_path / "mixed.wav",
        tmp_path / "result.json",
        tmp_path / "transcription.txt",
        tmp_path / "speakers.txt",
    )

    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: settings)
    monkeypatch.setattr("meetings_transcriber.cli.ensure_profile", lambda base_dir, name: profile)
    monkeypatch.setattr("meetings_transcriber.cli.create_run_paths", lambda profile: paths)
    monkeypatch.setattr("meetings_transcriber.cli.record_meeting", lambda settings, paths: (_ for _ in ()).throw(KeyboardInterrupt()))
    monkeypatch.setattr("meetings_transcriber.cli.transcribe_whisperx", lambda *args, **kwargs: None)

    result = main(["--profile", "Shipii", "--config", str(env_file)])

    assert result == 130


def test_main_returns_1_on_transcribe_error(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    settings = make_settings(tmp_path)
    profile = ProfilePaths(
        name="Shipii",
        directory=tmp_path,
        initial_prompt=tmp_path / "prompt.txt",
        hotwords=tmp_path / "hotwords.txt",
    )
    paths = RunPaths(
        tmp_path,
        tmp_path / "system.wav",
        tmp_path / "microphone.wav",
        tmp_path / "mixed.wav",
        tmp_path / "result.json",
        tmp_path / "transcription.txt",
        tmp_path / "speakers.txt",
    )

    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: settings)
    monkeypatch.setattr("meetings_transcriber.cli.ensure_profile", lambda base_dir, name: profile)
    monkeypatch.setattr("meetings_transcriber.cli.create_run_paths", lambda profile: paths)
    monkeypatch.setattr("meetings_transcriber.cli.record_meeting", lambda settings, paths: 0)
    monkeypatch.setattr("meetings_transcriber.cli.transcribe_whisperx", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("boom")))

    result = main(["--profile", "Shipii", "--config", str(env_file)])
    captured = capsys.readouterr()

    assert result == 1
    assert "Error: boom" in captured.err


def test_main_requires_profile(tmp_path, monkeypatch):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: make_settings(tmp_path))
    monkeypatch.setattr("meetings_transcriber.cli.ensure_profile", lambda base_dir, name: None)
    monkeypatch.setattr("meetings_transcriber.cli.create_run_paths", lambda profile: None)

    with pytest.raises(SystemExit):
        main(["--config", str(env_file)])


def test_main_processes_multiple_audio_sources(tmp_path, monkeypatch):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    settings = make_settings(tmp_path)
    profile = ProfilePaths(
        name="Shipii",
        directory=tmp_path,
        initial_prompt=tmp_path / "prompt.txt",
        hotwords=tmp_path / "hotwords.txt",
    )
    paths = RunPaths(
        tmp_path,
        tmp_path / "system.wav",
        tmp_path / "microphone.wav",
        tmp_path / "mixed.wav",
        tmp_path / "result.json",
        tmp_path / "transcription.txt",
        tmp_path / "speakers.txt",
    )
    audio_calls = []

    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: settings)
    monkeypatch.setattr("meetings_transcriber.cli.ensure_profile", lambda base_dir, name: profile)
    monkeypatch.setattr("meetings_transcriber.cli.create_run_paths", lambda profile: paths)
    monkeypatch.setattr("meetings_transcriber.cli.import_existing_audio", lambda sources, paths: audio_calls.append(tuple(sources)))
    monkeypatch.setattr("meetings_transcriber.cli.transcribe_whisperx", lambda *args, **kwargs: None)

    result = main([
        "--profile", "Shipii",
        "--audio", "one.ogg", "two.ogg",
        "--config", str(env_file),
    ])

    assert result == 0
    assert audio_calls == [(Path("one.ogg"), Path("two.ogg"))]


def test_main_prints_ffmpeg_ctrlc_message(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    settings = make_settings(tmp_path)
    profile = ProfilePaths(
        name="Shipii",
        directory=tmp_path,
        initial_prompt=tmp_path / "prompt.txt",
        hotwords=tmp_path / "hotwords.txt",
    )
    paths = RunPaths(
        tmp_path,
        tmp_path / "system.wav",
        tmp_path / "microphone.wav",
        tmp_path / "mixed.wav",
        tmp_path / "result.json",
        tmp_path / "transcription.txt",
        tmp_path / "speakers.txt",
    )

    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: settings)
    monkeypatch.setattr("meetings_transcriber.cli.ensure_profile", lambda base_dir, name: profile)
    monkeypatch.setattr("meetings_transcriber.cli.create_run_paths", lambda profile: paths)
    monkeypatch.setattr("meetings_transcriber.cli.record_meeting", lambda settings, paths: 255)
    monkeypatch.setattr("meetings_transcriber.cli.transcribe_whisperx", lambda *args, **kwargs: None)

    result = main(["--profile", "Shipii", "--config", str(env_file)])
    captured = capsys.readouterr()

    assert result == 0
    assert "FFmpeg recibió Ctrl+C y cerró correctamente los WAV." in captured.out


def test_main_debug_prints_traceback_on_error(tmp_path, monkeypatch, capsys):
    import os
    import runpy

    env_file = tmp_path / "config.env"
    env_file.write_text("")
    settings = make_settings(tmp_path)
    profile = ProfilePaths(
        name="Shipii",
        directory=tmp_path,
        initial_prompt=tmp_path / "prompt.txt",
        hotwords=tmp_path / "hotwords.txt",
    )
    paths = RunPaths(
        tmp_path,
        tmp_path / "system.wav",
        tmp_path / "microphone.wav",
        tmp_path / "mixed.wav",
        tmp_path / "result.json",
        tmp_path / "transcription.txt",
        tmp_path / "speakers.txt",
    )

    monkeypatch.setenv("DEBUG", "1")
    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: settings)
    monkeypatch.setattr("meetings_transcriber.cli.ensure_profile", lambda base_dir, name: profile)
    monkeypatch.setattr("meetings_transcriber.cli.create_run_paths", lambda profile: paths)
    monkeypatch.setattr("meetings_transcriber.cli.record_meeting", lambda settings, paths: 0)
    monkeypatch.setattr("meetings_transcriber.cli.transcribe_whisperx", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("boom")))

    result = main(["--profile", "Shipii", "--config", str(env_file)])
    captured = capsys.readouterr()

    assert result == 1
    assert "Traceback" in captured.err


def test_main_module_entrypoint(tmp_path, monkeypatch):
    import runpy
    import sys

    env_file = tmp_path / "config.env"
    env_file.write_text("")
    base_dir = tmp_path / "profiles"
    base_dir.mkdir()
    (base_dir / "profile").mkdir()

    monkeypatch.setenv("BASE_DIR", str(base_dir))
    monkeypatch.setenv("HF_TOKEN", "secret")
    monkeypatch.setenv("DEVICE", "cpu")
    monkeypatch.setattr(sys, "argv", ["meetings_transcriber.cli", "--list-profiles", "--config", str(env_file)])
    monkeypatch.delitem(sys.modules, "meetings_transcriber.cli", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("meetings_transcriber.cli", run_name="__main__", alter_sys=True)

    assert excinfo.value.code == 0
