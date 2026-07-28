from meetings_transcriber.postprocess import (
    clean_segments,
    collapse_repeated_sentences,
    process_whisperx_json,
    render_transcripts,
)


def test_collapses_exact_repeated_sentences():
    assert collapse_repeated_sentences("¿Qué? ¿Qué? ¿Qué?") == "¿Qué?"


def test_preserves_natural_repetition_inside_sentence():
    text = "No, no, no es un cambio."
    assert collapse_repeated_sentences(text) == text


def test_clean_segments_removes_consecutive_duplicates():
    segments = [
        {"text": "Hola.", "speaker": "SPEAKER_00"},
        {"text": "Hola.", "speaker": "SPEAKER_00"},
        {"text": "Chau.", "speaker": "SPEAKER_01"},
    ]
    assert [item["text"] for item in clean_segments(segments)] == ["Hola.", "Chau."]


def test_render_transcripts_groups_speakers():
    plain, speakers = render_transcripts([
        {"text": "Hola.", "speaker": "SPEAKER_00"},
        {"text": "Todo bien.", "speaker": "SPEAKER_00"},
        {"text": "Sí.", "speaker": "SPEAKER_01"},
    ])
    assert plain == "Hola.\nTodo bien.\nSí.\n"
    assert speakers == "[SPEAKER_00] Hola. Todo bien.\n[SPEAKER_01] Sí.\n"


def test_collapse_repeated_sentences_returns_original_when_no_sentences():
    assert collapse_repeated_sentences("") == ""
    assert collapse_repeated_sentences("hola hola") == "hola hola"


def test_segment_speaker_returns_word_level_speaker():
    assert render_transcripts([
        {"text": "Hola.", "words": [{"speaker": "SPEAKER_01"}]},
    ])[1] == "[SPEAKER_01] Hola.\n"


def test_segment_speaker_returns_unknown_when_no_speaker():
    assert render_transcripts([
        {"text": "Hola."},
    ])[1] == "[SPEAKER_UNKNOWN] Hola.\n"


def test_process_whisperx_json_writes_files(tmp_path):
    json_path = tmp_path / "input.json"
    plain_path = tmp_path / "plain.txt"
    speaker_path = tmp_path / "speaker.txt"
    json_path.write_text(
        '{"segments": [{"text": "Hola.", "speaker": "SPEAKER_00"}]}',
        encoding="utf-8",
    )

    process_whisperx_json(json_path, plain_path, speaker_path)

    assert plain_path.read_text(encoding="utf-8") == "Hola.\n"
    assert speaker_path.read_text(encoding="utf-8") == "[SPEAKER_00] Hola.\n"
