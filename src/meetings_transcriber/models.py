from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProfilePaths:
    name: str
    directory: Path
    initial_prompt: Path
    hotwords: Path


@dataclass(frozen=True)
class RunPaths:
    directory: Path
    system_audio: Path
    microphone_audio: Path
    mixed_audio: Path
    json_result: Path
    plain_transcript: Path
    speaker_transcript: Path


@dataclass(frozen=True)
class MeetingSummary:
    name: str
    directory: Path
    has_transcription: bool
