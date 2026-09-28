from pathlib import Path

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
    monkeypatch.setattr("meetings_transcriber.cli.ask_transcribe_now", lambda: True)
    monkeypatch.setattr("meetings_transcriber.cli.transcribe_whisperx", lambda *args, **kwargs: None)

    result = main(["--profile", "Shipii", "--config", str(env_file)])
    captured = capsys.readouterr()

    assert result == 0
    assert "FFmpeg recibió Ctrl+C y cerró correctamente los archivos de grabación." in captured.out
    assert "Dispositivo: cpu (int8)" in captured.out


def test_main_debug_prints_traceback_on_error(tmp_path, monkeypatch, capsys):

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


def test_parser_accepts_meeting_flag():
    parser = build_parser()
    args = parser.parse_args(["--profile", "Shipii", "--meeting", "Reunion_2026-07-24_11-09-47"])
    assert args.meeting == Path("Reunion_2026-07-24_11-09-47")
    assert args.audio is None


def test_main_rejects_audio_and_meeting_together(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: make_settings(tmp_path))

    with pytest.raises(SystemExit) as excinfo:
        main([
            "--profile", "Shipii",
            "--audio", "one.ogg",
            "--meeting", str(tmp_path / "Reunion_x"),
            "--config", str(env_file),
        ])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "--audio y --meeting son mutuamente excluyentes" in captured.err


def test_main_meeting_transcribes_in_place_without_new_folder(tmp_path, monkeypatch):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: make_settings(tmp_path))

    transcribed = []
    monkeypatch.setattr(
        "meetings_transcriber.cli.transcribe_whisperx",
        lambda settings, profile, paths: transcribed.append(paths),
    )
    monkeypatch.setattr(
        "meetings_transcriber.cli.record_meeting",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no debe grabar")),
    )
    monkeypatch.setattr(
        "meetings_transcriber.cli.import_existing_audio",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no debe importar")),
    )

    profile_dir = tmp_path / "Shipii"
    meeting = profile_dir / "Reunion_2026-07-24_11-09-47"
    meeting.mkdir(parents=True)
    (meeting / "reunion_mezclada.wav").write_bytes(b"audio")

    result = main(["--profile", "Shipii", "--meeting", str(meeting), "--config", str(env_file)])

    assert result == 0
    assert len(transcribed) == 1
    assert transcribed[0].directory == meeting.resolve()
    assert transcribed[0].mixed_audio == meeting.resolve() / "reunion_mezclada.wav"
    assert transcribed[0].plain_transcript == meeting.resolve() / "transcripcion.txt"
    assert list(profile_dir.glob("Reunion_*")) == [meeting]


def test_main_meeting_accepts_folder_name_under_profile(tmp_path, monkeypatch):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: make_settings(tmp_path))
    transcribed = []
    monkeypatch.setattr(
        "meetings_transcriber.cli.transcribe_whisperx",
        lambda settings, profile, paths: transcribed.append(paths),
    )

    profile_dir = tmp_path / "Shipii"
    meeting = profile_dir / "Reunion_2026-07-24_11-09-47"
    meeting.mkdir(parents=True)
    (meeting / "reunion_mezclada.wav").write_bytes(b"audio")

    result = main([
        "--profile", "Shipii",
        "--meeting", "Reunion_2026-07-24_11-09-47",
        "--config", str(env_file),
    ])

    assert result == 0
    assert transcribed[0].directory == meeting.resolve()


def test_main_skips_transcription_when_user_declines(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    settings = make_settings(tmp_path)
    profile = ProfilePaths(
        name="Shipii",
        directory=tmp_path,
        initial_prompt=tmp_path / "prompt.txt",
        hotwords=tmp_path / "hotwords.txt",
    )
    meeting_dir = tmp_path / "Reunion_2026-07-24_11-09-47"
    meeting_dir.mkdir()
    paths = RunPaths(
        meeting_dir,
        meeting_dir / "sistema.wav",
        meeting_dir / "microfono.wav",
        meeting_dir / "reunion_mezclada.wav",
        meeting_dir / "reunion_mezclada.json",
        meeting_dir / "transcripcion.txt",
        meeting_dir / "transcripcion_speakers.txt",
    )
    transcribed = []

    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: settings)
    monkeypatch.setattr("meetings_transcriber.cli.ensure_profile", lambda base_dir, name: profile)
    monkeypatch.setattr("meetings_transcriber.cli.create_run_paths", lambda profile: paths)
    monkeypatch.setattr("meetings_transcriber.cli.record_meeting", lambda settings, paths: 255)
    monkeypatch.setattr("meetings_transcriber.cli.ask_transcribe_now", lambda: False)
    monkeypatch.setattr(
        "meetings_transcriber.cli.transcribe_whisperx",
        lambda *args, **kwargs: transcribed.append(True),
    )

    result = main(["--profile", "Shipii", "--config", str(env_file)])
    captured = capsys.readouterr()

    assert result == 0
    assert transcribed == []
    assert str(meeting_dir) in captured.out
    assert "--meeting" in captured.out
    assert "Shipii" in captured.out


def test_main_transcribes_after_recording_when_user_accepts(tmp_path, monkeypatch):
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
    transcribed = []

    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: settings)
    monkeypatch.setattr("meetings_transcriber.cli.ensure_profile", lambda base_dir, name: profile)
    monkeypatch.setattr("meetings_transcriber.cli.create_run_paths", lambda profile: paths)
    monkeypatch.setattr("meetings_transcriber.cli.record_meeting", lambda settings, paths: 255)
    monkeypatch.setattr("meetings_transcriber.cli.ask_transcribe_now", lambda: True)
    monkeypatch.setattr(
        "meetings_transcriber.cli.transcribe_whisperx",
        lambda *args, **kwargs: transcribed.append(True),
    )

    result = main(["--profile", "Shipii", "--config", str(env_file)])

    assert result == 0
    assert transcribed == [True]


def test_main_audio_does_not_ask_to_transcribe(tmp_path, monkeypatch):
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
    asked = []

    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: settings)
    monkeypatch.setattr("meetings_transcriber.cli.ensure_profile", lambda base_dir, name: profile)
    monkeypatch.setattr("meetings_transcriber.cli.create_run_paths", lambda profile: paths)
    monkeypatch.setattr("meetings_transcriber.cli.import_existing_audio", lambda sources, paths: None)
    monkeypatch.setattr("meetings_transcriber.cli.transcribe_whisperx", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "meetings_transcriber.cli.ask_transcribe_now",
        lambda: asked.append(True) or True,
    )

    result = main(["--profile", "Shipii", "--audio", "one.ogg", "--config", str(env_file)])

    assert result == 0
    assert asked == []


def test_ask_transcribe_now_accepts_yes():
    from meetings_transcriber.cli import ask_transcribe_now

    answers = iter(["s"])
    assert ask_transcribe_now(reader=lambda _prompt: next(answers), is_interactive=lambda: True) is True


def test_ask_transcribe_now_accepts_empty_as_yes():
    from meetings_transcriber.cli import ask_transcribe_now

    answers = iter([""])
    assert ask_transcribe_now(reader=lambda _prompt: next(answers), is_interactive=lambda: True) is True


def test_ask_transcribe_now_accepts_no():
    from meetings_transcriber.cli import ask_transcribe_now

    answers = iter(["n"])
    assert ask_transcribe_now(reader=lambda _prompt: next(answers), is_interactive=lambda: True) is False


def test_ask_transcribe_now_retries_invalid_then_accepts(capsys):
    from meetings_transcriber.cli import ask_transcribe_now

    answers = iter(["tal vez", "s"])
    assert ask_transcribe_now(reader=lambda _prompt: next(answers), is_interactive=lambda: True) is True
    captured = capsys.readouterr()
    assert "Respondé s para transcribir o n para terminar." in captured.out


def test_ask_transcribe_now_non_interactive_transcribes(capsys):
    from meetings_transcriber.cli import ask_transcribe_now

    assert ask_transcribe_now(is_interactive=lambda: False) is True
    captured = capsys.readouterr()
    assert "Entrada no interactiva" in captured.out


def test_ask_transcribe_now_eof_means_finish():
    from meetings_transcriber.cli import ask_transcribe_now

    def raise_eof(_prompt):
        raise EOFError

    assert ask_transcribe_now(reader=raise_eof, is_interactive=lambda: True) is False


def test_ask_transcribe_now_uses_input_by_default(monkeypatch):
    from meetings_transcriber.cli import ask_transcribe_now

    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert ask_transcribe_now(is_interactive=lambda: True) is False


def test_parser_accepts_list_meetings_flag():
    parser = build_parser()
    args = parser.parse_args(["--profile", "Shipii", "--list-meetings"])
    assert args.list_meetings is True


def test_main_list_meetings_requires_profile(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: make_settings(tmp_path))

    with pytest.raises(SystemExit) as excinfo:
        main(["--list-meetings", "--config", str(env_file)])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "--profile es obligatorio" in captured.err


def test_main_list_meetings_rejects_audio(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: make_settings(tmp_path))

    with pytest.raises(SystemExit) as excinfo:
        main([
            "--profile", "Shipii",
            "--list-meetings",
            "--audio", "one.ogg",
            "--config", str(env_file),
        ])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "--list-meetings no se combina con --audio ni --meeting" in captured.err


def test_main_list_meetings_prints_status_without_recording(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: make_settings(tmp_path))
    monkeypatch.setattr(
        "meetings_transcriber.cli.create_run_paths",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no debe crear reunión")),
    )
    monkeypatch.setattr(
        "meetings_transcriber.cli.record_meeting",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no debe grabar")),
    )

    profile_dir = tmp_path / "Shipii"
    with_transcript = profile_dir / "Reunion_2026-07-24_11-09-47"
    without_transcript = profile_dir / "Reunion_2026-07-25_09-00-00"
    with_transcript.mkdir(parents=True)
    without_transcript.mkdir(parents=True)
    (with_transcript / "transcripcion.txt").write_text("hola", encoding="utf-8")

    result = main(["--profile", "Shipii", "--list-meetings", "--config", str(env_file)])
    captured = capsys.readouterr()

    assert result == 0
    assert "Reunion_2026-07-24_11-09-47\tcon transcripción" in captured.out
    assert "Reunion_2026-07-25_09-00-00\tsin transcripción" in captured.out


def test_main_list_meetings_empty_prints_message(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "config.env"
    env_file.write_text("")
    monkeypatch.setattr("meetings_transcriber.cli.load_settings", lambda project_dir: make_settings(tmp_path))

    result = main(["--profile", "Shipii", "--list-meetings", "--config", str(env_file)])
    captured = capsys.readouterr()

    assert result == 0
    assert "No hay reuniones" in captured.out
    assert "Shipii" in captured.out
