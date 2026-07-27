from pathlib import Path
from unittest.mock import Mock

import pytest

from meetings_transcriber.audio import ffprobe_duration, validate_audio


def completed(stdout: str):
    result = Mock()
    result.stdout = stdout
    return result


def test_ffprobe_duration():
    runner = Mock(return_value=completed("123.5\n"))
    assert ffprobe_duration(Path("audio.wav"), runner) == 123.5


def test_validate_audio_rejects_empty(tmp_path):
    audio = tmp_path / "audio.wav"
    audio.touch()
    with pytest.raises(ValueError):
        validate_audio(audio)
