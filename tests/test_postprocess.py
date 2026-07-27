from meetings_transcriber.postprocess import clean_segments, collapse_repeated_sentences, render_transcripts


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
