import pytest

from meetings_transcriber.spatial_cues import (
    compile_patterns,
    find_spatial_cues,
    parse_extra_patterns,
    segment_as_cue_input,
)


def test_detects_common_spatial_phrases():
    samples = [
        "Fijate acá en el formulario.",
        "Este botón no responde.",
        "Cuando hago clic acá pasa esto.",
        "Esto tendría que aparecer ya.",
        "Mirá lo que pasa acá.",
        "Esto de acá no cierra.",
        "Mirá esta pantalla.",
    ]
    for text in samples:
        assert find_spatial_cues(text), text


def test_ignores_non_spatial_phrases():
    assert find_spatial_cues("Hola, arrancamos la reunión de standup.") == []
    assert find_spatial_cues("El deploy salió bien ayer.") == []


def test_parse_extra_patterns():
    assert parse_extra_patterns(None) == ()
    assert parse_extra_patterns("  ") == ()
    parsed = parse_extra_patterns(r"custom:\bfoo\b, other:\bbar\b")
    assert parsed == (("custom", r"\bfoo\b"), ("other", r"\bbar\b"))
    # Entradas vacías entre comas se ignoran.
    assert parse_extra_patterns(r"custom:\bfoo\b, ,") == (("custom", r"\bfoo\b"),)
    with pytest.raises(ValueError, match="id:regex"):
        parse_extra_patterns("sinseparador")
    with pytest.raises(ValueError, match="incompleto"):
        parse_extra_patterns("solo:")
    with pytest.raises(ValueError, match="incompleto"):
        parse_extra_patterns(":solo")


def test_duplicate_pattern_ids_dedup_matches():
    compiled = compile_patterns(
        (
            ("deixis_aca", r"\bacá\b"),
            ("deixis_aca", r"\bacá\b"),
        )
    )
    matches = find_spatial_cues("mirá acá", compiled)
    assert len(matches) == 1


def test_segment_as_cue_input():
    assert segment_as_cue_input({"text": "  Hola  "}) == "Hola"
    assert segment_as_cue_input({}) == ""
