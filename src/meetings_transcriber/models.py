from __future__ import annotations

from dataclasses import dataclass, field
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
    video: Path = field(init=False)
    session_meta: Path = field(init=False)
    meet_events: Path = field(init=False)
    attributed_transcript: Path = field(init=False)
    visual_evidence_dir: Path = field(init=False)
    visual_evidence_index: Path = field(init=False)
    transcription_audio: Path = field(init=False)
    transcription_audio_meta: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "video", self.directory / "reunion.mp4")
        object.__setattr__(self, "session_meta", self.directory / "session.json")
        object.__setattr__(self, "meet_events", self.directory / "meet_events.jsonl")
        object.__setattr__(
            self, "attributed_transcript", self.directory / "transcripcion_atribuida.json"
        )
        object.__setattr__(self, "visual_evidence_dir", self.directory / "evidencia_visual")
        object.__setattr__(
            self, "visual_evidence_index", self.directory / "evidencia_visual" / "index.json"
        )
        # Audio canónico para WhisperX cuando se demuxea el AAC del MP4.
        object.__setattr__(self, "transcription_audio", self.directory / "audio_transcripcion.wav")
        object.__setattr__(
            self,
            "transcription_audio_meta",
            self.directory / "audio_transcripcion_source.json",
        )


@dataclass(frozen=True)
class MeetingSummary:
    name: str
    directory: Path
    has_transcription: bool
