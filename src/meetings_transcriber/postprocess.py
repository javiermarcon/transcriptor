from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SPACE_RE = re.compile(r"\s+")
SENTENCE_RE = re.compile(r"[¡¿]?[^.!?¡¿\n]+(?:[.!?]+|$)", re.UNICODE)

# Frases típicas de alucinación en silencios (Whisper). Matching casefold/normalize.
DEFAULT_HALLUCINATION_PHRASES: tuple[str, ...] = (
    "gracias por ver el video",
    "thanks for watching",
    "cc por antarctica films argentina",
    "subtitles by the amara.org community",
    "subscribe to my channel",
    "like and subscribe",
    "thank you for watching",
    "amara.org",
)


def normalize(text: str) -> str:
    text = SPACE_RE.sub(" ", text).strip().casefold()
    return text.strip(" \t\r\n.,;:!?¡¿\"'()[]{}")


def is_hallucination_phrase(text: str, phrases: Sequence[str]) -> bool:
    key = normalize(text)
    if not key:
        return True
    for phrase in phrases:
        needle = normalize(phrase)
        if not needle:
            continue
        if len(needle) < 12:
            if key == needle:
                return True
            continue
        if needle in key or key in needle:
            return True
    return False


def collapse_repeated_sentences(text: str) -> str:
    units = [match.group(0).strip() for match in SENTENCE_RE.finditer(text)]
    if not units:
        return SPACE_RE.sub(" ", text).strip()
    output: list[str] = []
    previous = ""
    for unit in units:
        key = normalize(unit)
        if key and key == previous:
            continue
        output.append(unit)
        previous = key
    return SPACE_RE.sub(" ", " ".join(output)).strip()


def clean_segments(
    segments: list[dict[str, Any]],
    hallucination_phrases: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    phrases = tuple(hallucination_phrases or ())
    cleaned: list[dict[str, Any]] = []
    previous = ""
    for segment in segments:
        text = collapse_repeated_sentences(str(segment.get("text", "")).strip())
        key = normalize(text)
        if not key or key == previous:
            continue
        if phrases and is_hallucination_phrase(text, phrases):
            continue
        copy = dict(segment)
        copy["text"] = text
        cleaned.append(copy)
        previous = key
    return cleaned


def segment_speaker(segment: dict[str, Any]) -> str:
    if segment.get("speaker"):
        return str(segment["speaker"])
    for word in segment.get("words") or []:
        if word.get("speaker"):
            return str(word["speaker"])
    return "SPEAKER_UNKNOWN"


def render_transcripts(
    segments: list[dict[str, Any]],
    hallucination_phrases: Sequence[str] | None = None,
) -> tuple[str, str]:
    segments = clean_segments(segments, hallucination_phrases=hallucination_phrases)
    plain = "\n".join(segment["text"] for segment in segments).rstrip() + "\n"
    speaker_lines: list[str] = []
    current_speaker: str | None = None
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_speaker, current_parts
        text = collapse_repeated_sentences(" ".join(current_parts))
        if text:
            speaker_lines.append(f"[{current_speaker or 'SPEAKER_UNKNOWN'}] {text}")
        current_speaker = None
        current_parts = []

    for segment in segments:
        speaker = segment_speaker(segment)
        if current_speaker is None:
            current_speaker = speaker
        elif speaker != current_speaker:
            flush()
            current_speaker = speaker
        current_parts.append(segment["text"])
    flush()
    return plain, "\n".join(speaker_lines).rstrip() + "\n"


def process_whisperx_json(
    json_path: Path,
    plain_path: Path,
    speaker_path: Path,
    hallucination_phrases: Sequence[str] | None = None,
) -> None:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    plain, speakers = render_transcripts(
        data.get("segments", []),
        hallucination_phrases=hallucination_phrases,
    )
    plain_path.write_text(plain, encoding="utf-8")
    speaker_path.write_text(speakers, encoding="utf-8")
