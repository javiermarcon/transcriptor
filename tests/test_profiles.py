from datetime import UTC, datetime
from pathlib import Path

import pytest

from meetings_transcriber.profiles import (
    create_run_paths,
    ensure_profile,
    list_meetings,
    list_profile_names,
    load_existing_run_paths,
    meeting_has_transcription,
    read_hotwords,
    read_initial_prompt,
    run_paths_for_directory,
    validate_profile_name,
)


def test_validate_profile_name():
    assert validate_profile_name("Shipii") == "Shipii"
    with pytest.raises(ValueError):
        validate_profile_name("../Shipii")


def test_ensure_profile_creates_context_files(tmp_path):
    profile = ensure_profile(tmp_path, "Shipii")
    assert profile.initial_prompt.exists()
    assert profile.hotwords.exists()
    assert "rioplatense" in read_initial_prompt(profile.initial_prompt)


def test_list_profile_names_only_valid_dirs(tmp_path):
    (tmp_path / "Shipii").mkdir()
    (tmp_path / "motonave").mkdir()
    (tmp_path / "not valid").mkdir()
    (tmp_path / "readme.txt").write_text("x", encoding="utf-8")
    assert list_profile_names(tmp_path) == ["motonave", "Shipii"]
    assert list_profile_names(tmp_path / "missing") == []


def test_read_hotwords_ignores_comments_and_duplicates(tmp_path):
    path = tmp_path / "hotwords.txt"
    path.write_text("# comentario\nShipii\nMeli\nShipii\n", encoding="utf-8")
    assert read_hotwords(path) == "Shipii, Meli"


def test_initial_prompt_has_length_limit(tmp_path):
    path = tmp_path / "initial_prompt.txt"
    path.write_text("x" * 181, encoding="utf-8")
    with pytest.raises(ValueError):
        read_initial_prompt(path)


def test_create_run_paths(tmp_path):
    profile = ensure_profile(tmp_path, "Shipii")
    run = create_run_paths(profile, datetime(2026, 7, 24, 11, 9, 47, tzinfo=UTC))
    assert run.directory.name == "Reunion_2026-07-24_11-09-47"
    assert run.mixed_audio.name == "reunion_mezclada.wav"
    assert run.video == run.directory / "reunion.mp4"


def test_run_paths_for_directory_uses_canonical_names(tmp_path):
    directory = tmp_path / "Reunion_2026-07-24_11-09-47"
    directory.mkdir()
    paths = run_paths_for_directory(directory)
    assert paths.directory == directory
    assert paths.system_audio == directory / "sistema.wav"
    assert paths.microphone_audio == directory / "microfono.wav"
    assert paths.mixed_audio == directory / "reunion_mezclada.wav"
    assert paths.video == directory / "reunion.mp4"
    assert paths.json_result == directory / "reunion_mezclada.json"
    assert paths.plain_transcript == directory / "transcripcion.txt"
    assert paths.speaker_transcript == directory / "transcripcion_speakers.txt"


def test_load_existing_run_paths_uses_meeting_folder(tmp_path):
    profile = ensure_profile(tmp_path, "Shipii")
    meeting = profile.directory / "Reunion_2026-07-24_11-09-47"
    meeting.mkdir()
    (meeting / "reunion_mezclada.wav").write_bytes(b"audio")

    paths = load_existing_run_paths(meeting, profile)

    assert paths.directory == meeting.resolve()
    assert paths.mixed_audio == meeting.resolve() / "reunion_mezclada.wav"
    assert paths.plain_transcript == meeting.resolve() / "transcripcion.txt"
    assert paths.speaker_transcript == meeting.resolve() / "transcripcion_speakers.txt"
    assert paths.video == meeting.resolve() / "reunion.mp4"
    assert not paths.video.exists()


def test_load_existing_run_paths_resolves_name_under_profile(tmp_path):
    profile = ensure_profile(tmp_path, "Shipii")
    meeting = profile.directory / "Reunion_2026-07-24_11-09-47"
    meeting.mkdir()
    (meeting / "reunion_mezclada.wav").write_bytes(b"audio")

    paths = load_existing_run_paths(Path("Reunion_2026-07-24_11-09-47"), profile)

    assert paths.directory == meeting.resolve()


def test_load_existing_run_paths_missing_directory(tmp_path):
    profile = ensure_profile(tmp_path, "Shipii")
    missing = tmp_path / "Reunion_inexistente"
    with pytest.raises(FileNotFoundError, match="Carpeta de reunión inexistente"):
        load_existing_run_paths(missing, profile)


def test_load_existing_run_paths_missing_mixed_audio(tmp_path):
    profile = ensure_profile(tmp_path, "Shipii")
    meeting = profile.directory / "Reunion_2026-07-24_11-09-47"
    meeting.mkdir()
    with pytest.raises(FileNotFoundError, match=r"reunion_mezclada\.wav"):
        load_existing_run_paths(meeting, profile)


def test_load_existing_run_paths_rejects_empty_mixed_audio(tmp_path):
    profile = ensure_profile(tmp_path, "Shipii")
    meeting = profile.directory / "Reunion_2026-07-24_11-09-47"
    meeting.mkdir()
    (meeting / "reunion_mezclada.wav").write_bytes(b"")
    with pytest.raises(FileNotFoundError, match=r"reunion_mezclada\.wav"):
        load_existing_run_paths(meeting, profile)


def test_meeting_has_transcription_requires_non_empty_plain(tmp_path):
    meeting = tmp_path / "Reunion_2026-07-24_11-09-47"
    meeting.mkdir()
    paths = run_paths_for_directory(meeting)

    assert meeting_has_transcription(paths) is False

    paths.plain_transcript.write_text("", encoding="utf-8")
    assert meeting_has_transcription(paths) is False

    paths.plain_transcript.write_text("hola", encoding="utf-8")
    assert meeting_has_transcription(paths) is True


def test_list_meetings_marks_transcription_status(tmp_path):
    profile = ensure_profile(tmp_path, "Shipii")
    with_transcript = profile.directory / "Reunion_2026-07-24_11-09-47"
    without_transcript = profile.directory / "Reunion_2026-07-25_09-00-00"
    ignored_file = profile.directory / "not_a_meeting.txt"
    other_dir = profile.directory / "not_reunion_dir"

    with_transcript.mkdir()
    without_transcript.mkdir()
    other_dir.mkdir()
    ignored_file.write_text("x", encoding="utf-8")
    (with_transcript / "reunion_mezclada.wav").write_bytes(b"audio")
    (without_transcript / "reunion_mezclada.wav").write_bytes(b"audio")
    (with_transcript / "transcripcion.txt").write_text("texto", encoding="utf-8")

    meetings = list_meetings(profile)

    assert [item.name for item in meetings] == [
        "Reunion_2026-07-24_11-09-47",
        "Reunion_2026-07-25_09-00-00",
    ]
    assert meetings[0].has_transcription is True
    assert meetings[1].has_transcription is False
    assert meetings[0].directory == with_transcript.resolve()


def test_list_meetings_empty_profile(tmp_path):
    profile = ensure_profile(tmp_path, "Shipii")
    assert list_meetings(profile) == []
