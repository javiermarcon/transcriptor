from datetime import datetime

import pytest

from meetings_transcriber.profiles import (
    create_run_paths,
    ensure_profile,
    read_hotwords,
    read_initial_prompt,
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
    run = create_run_paths(profile, datetime(2026, 7, 24, 11, 9, 47))
    assert run.directory.name == "Reunion_2026-07-24_11-09-47"
    assert run.mixed_audio.name == "reunion_mezclada.wav"
