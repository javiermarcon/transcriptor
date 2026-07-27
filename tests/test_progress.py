from meetings_transcriber.progress import format_clock, parse_progress


def test_parse_progress():
    progress = parse_progress("Transcript: [741.569 --> 768.856] texto", 1200)
    assert progress is not None
    assert progress.current == 768.856
    assert progress.percent == 768.856 / 1200 * 100


def test_parse_progress_rejects_unrelated_line():
    assert parse_progress("sin timestamp", 1200) is None


def test_format_clock():
    assert format_clock(768.856) == "12:49"
    assert format_clock(3661) == "01:01:01"
