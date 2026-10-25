from __future__ import annotations

import json
import struct
import wave
from pathlib import Path

from meetings_transcriber.attribution import (
    SpeakerAttribution,
    attribute_segments,
    meet_votes_for_speakers,
    merge_speaker_attributions,
    resolve_local_microphone_attribution,
    resolve_meet_attributions,
    write_attributed_transcript,
)
from meetings_transcriber.meet_events import write_session_meta
from meetings_transcriber.profiles import run_paths_for_directory


def _write_pcm16_wav(path: Path, samples: list[int], rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, s))) for s in samples))


def _dual_track_wavs(directory: Path, *, mic_levels: list[tuple[float, float, int]], sys_levels: list[tuple[float, float, int]], duration_s: float = 6.0) -> tuple[Path, Path]:
    """Construye microfono.wav y sistema.wav con tramos de amplitud constante."""
    rate = 16000
    n = int(duration_s * rate)
    mic = [0] * n
    sys = [0] * n

    def paint(target: list[int], levels: list[tuple[float, float, int]]) -> None:
        for start_s, end_s, amp in levels:
            a = int(start_s * rate)
            b = int(end_s * rate)
            for i in range(max(0, a), min(n, b)):
                target[i] = amp

    paint(mic, mic_levels)
    paint(sys, sys_levels)
    mic_path = directory / "microfono.wav"
    sys_path = directory / "sistema.wav"
    _write_pcm16_wav(mic_path, mic, rate=rate)
    _write_pcm16_wav(sys_path, sys, rate=rate)
    return mic_path, sys_path


def test_mic_attribution_identifies_local_speaker(tmp_path):
    mic, sys = _dual_track_wavs(
        tmp_path,
        mic_levels=[(0.0, 2.0, 12000), (2.0, 4.0, 200)],
        sys_levels=[(0.0, 2.0, 500), (2.0, 4.0, 10000)],
        duration_s=4.0,
    )
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hola soy Javier.", "speaker": "SPEAKER_00"},
        {"start": 2.0, "end": 4.0, "text": "Hola soy Nacho.", "speaker": "SPEAKER_01"},
    ]
    doc = attribute_segments(
        segments,
        microphone_audio=mic,
        system_audio=sys,
        local_participant_name="Javier",
    )
    assert doc["speakers"]["SPEAKER_00"]["attributed_name"] == "Javier"
    assert doc["speakers"]["SPEAKER_00"]["source"] == "local_microphone"
    # SPEAKER_01 no se nombra solo por hablar en el sistema.
    assert "SPEAKER_01" not in doc["speakers"]
    seg0 = doc["segments"][0]
    assert seg0["speaker_id"] == "SPEAKER_00"
    assert seg0["attributed_name"] == "Javier"
    assert seg0["attribution"]["source"] == "local_microphone"


def test_mic_attribution_ambiguous_dominance_stays_unknown(tmp_path):
    mic, sys = _dual_track_wavs(
        tmp_path,
        mic_levels=[(0.0, 2.0, 8000), (2.0, 4.0, 7800)],
        sys_levels=[(0.0, 2.0, 7000), (2.0, 4.0, 7200)],
        duration_s=4.0,
    )
    segments = [
        {"start": 0.0, "end": 2.0, "text": "A", "speaker": "SPEAKER_00"},
        {"start": 2.0, "end": 4.0, "text": "B", "speaker": "SPEAKER_01"},
    ]
    doc = attribute_segments(
        segments,
        microphone_audio=mic,
        system_audio=sys,
        local_participant_name="Javier",
    )
    assert doc["speakers"] == {}
    assert all(seg["attributed_name"] is None for seg in doc["segments"])


def test_meet_active_speaker_attribution_with_sync_window():
    started = 1_700_000_000_000.0
    segments = [
        {"start": 10.0, "end": 12.0, "text": "punto uno", "speaker": "SPEAKER_00"},
        {"start": 20.0, "end": 22.0, "text": "punto dos", "speaker": "SPEAKER_01"},
        {"start": 30.0, "end": 32.0, "text": "otra vez", "speaker": "SPEAKER_00"},
    ]
    events = [
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": started + 10_200,
            "display_name": "Nacho",
            "participant_key": "dom:nacho",
            "confidence": 0.7,
            "source": "dom_speaking_attr",
        },
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": started + 20_100,
            "display_name": "Javier",
            "participant_key": "dom:javier",
            "confidence": 0.7,
            "source": "dom_speaking_attr",
        },
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": started + 21_000,
            "display_name": "Javier",
            "participant_key": "dom:javier",
            "confidence": 0.7,
            "source": "dom_speaking_attr",
        },
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": started + 30_000,
            "display_name": "Nacho",
            "participant_key": "dom:nacho",
            "confidence": 0.75,
            "source": "dom_speaking_attr",
        },
        # Roster alone must not attribute.
        {
            "event_type": "participant_joined",
            "timestamp_epoch_ms": started + 1_000,
            "display_name": "Ana",
            "participant_key": "dom:ana",
            "confidence": 0.9,
        },
    ]
    doc = attribute_segments(
        segments,
        meet_events=events,
        recording_started_at_epoch_ms=started,
    )
    assert doc["speakers"]["SPEAKER_00"]["attributed_name"] == "Nacho"
    assert doc["speakers"]["SPEAKER_00"]["source"] == "meet_active_speaker"
    assert doc["speakers"]["SPEAKER_01"]["attributed_name"] == "Javier"
    assert "Ana" not in {
        info.get("attributed_name") for info in doc["speakers"].values()
    }
    assert any(
        ref.get("display_name") == "Nacho"
        for ref in doc["speakers"]["SPEAKER_00"]["evidence"]["meet_event_refs"]
    )
    assert all(seg["speaker_id"].startswith("SPEAKER_") for seg in doc["segments"])


def test_meet_large_desync_does_not_force_attribution():
    started = 1_700_000_000_000.0
    segments = [
        {"start": 10.0, "end": 12.0, "text": "hola", "speaker": "SPEAKER_00"},
    ]
    # Evento 8s fuera del segmento: incluso con incertidumbre 1.5s no solapa.
    events = [
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": started + 20_000,
            "display_name": "Nacho",
            "participant_key": "dom:nacho",
            "confidence": 0.9,
        }
    ]
    doc = attribute_segments(
        segments,
        meet_events=events,
        recording_started_at_epoch_ms=started,
        sync_uncertainty_s=1.5,
    )
    assert doc["speakers"] == {}
    assert doc["segments"][0]["attributed_name"] is None


def test_conflict_mic_vs_meet_keeps_unknown(tmp_path):
    mic, sys = _dual_track_wavs(
        tmp_path,
        mic_levels=[(0.0, 3.0, 14000)],
        sys_levels=[(0.0, 3.0, 400)],
        duration_s=3.0,
    )
    started = 1_000.0
    segments = [
        {"start": 0.0, "end": 3.0, "text": "conflicto", "speaker": "SPEAKER_00"},
    ]
    events = [
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": started + 500,
            "display_name": "Nacho",
            "participant_key": "dom:nacho",
            "confidence": 0.9,
        },
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": started + 1500,
            "display_name": "Nacho",
            "participant_key": "dom:nacho",
            "confidence": 0.9,
        },
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": started + 2500,
            "display_name": "Nacho",
            "participant_key": "dom:nacho",
            "confidence": 0.9,
        },
    ]
    doc = attribute_segments(
        segments,
        microphone_audio=mic,
        system_audio=sys,
        local_participant_name="Javier",
        meet_events=events,
        recording_started_at_epoch_ms=started,
    )
    # Mic→Javier y Meet→Nacho sobre el mismo SPEAKER_00: conflicto → desconocido.
    assert "SPEAKER_00" not in doc["speakers"] or doc["speakers"]["SPEAKER_00"]["attributed_name"] is None
    assert doc["segments"][0]["attributed_name"] is None


def test_repeated_display_names_with_different_keys_are_ambiguous():
    started = 0.0
    segments = [
        {"start": 1.0, "end": 3.0, "text": "hola", "speaker": "SPEAKER_00"},
        {"start": 4.0, "end": 6.0, "text": "chau", "speaker": "SPEAKER_00"},
    ]
    events = [
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": 1500,
            "display_name": "Nacho",
            "participant_key": "dom:nacho-a",
            "confidence": 0.9,
        },
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": 4500,
            "display_name": "Nacho",
            "participant_key": "dom:nacho-b",
            "confidence": 0.9,
        },
    ]
    votes = meet_votes_for_speakers(segments, events, started)
    # Ambiguous names produce no votes.
    assert votes == {} or all(not names for names in votes.values())
    attrs = resolve_meet_attributions(votes)
    assert attrs == {}


def test_conflicting_meet_names_on_same_speaker_stay_unknown():
    started = 0.0
    # Dos tramos del mismo SPEAKER_* con evidencia Meet fuerte pero nombres distintos.
    segments = [
        {"start": 0.0, "end": 2.0, "text": "a", "speaker": "SPEAKER_00"},
        {"start": 20.0, "end": 22.0, "text": "b", "speaker": "SPEAKER_00"},
    ]
    events = [
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": 800,
            "display_name": "Javier",
            "participant_key": "dom:javier",
            "confidence": 0.85,
        },
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": 1500,
            "display_name": "Javier",
            "participant_key": "dom:javier",
            "confidence": 0.85,
        },
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": 20_800,
            "display_name": "Nacho",
            "participant_key": "dom:nacho",
            "confidence": 0.85,
        },
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": 21_500,
            "display_name": "Nacho",
            "participant_key": "dom:nacho",
            "confidence": 0.85,
        },
    ]
    doc = attribute_segments(
        segments,
        meet_events=events,
        recording_started_at_epoch_ms=started,
    )
    assert "SPEAKER_00" not in doc["speakers"]


def test_does_not_map_speaker_order_to_fixed_names():
    """SPEAKER_00/01 no se mapean por convención a Javier/Nacho."""
    scores = {
        "SPEAKER_00": {"mic_dominance": 0.4, "speech_s": 5.0},
        "SPEAKER_01": {"mic_dominance": 0.41, "speech_s": 5.0},
    }
    assert resolve_local_microphone_attribution(scores, "Javier") is None


def test_combined_sources_agree(tmp_path):
    mic, sys = _dual_track_wavs(
        tmp_path,
        mic_levels=[(0.0, 3.0, 14000)],
        sys_levels=[(0.0, 3.0, 400)],
        duration_s=3.0,
    )
    started = 0.0
    segments = [
        {"start": 0.0, "end": 3.0, "text": "ok", "speaker": "SPEAKER_00"},
    ]
    events = [
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": 800,
            "display_name": "Javier",
            "participant_key": "dom:javier",
            "confidence": 0.85,
        },
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": 1600,
            "display_name": "Javier",
            "participant_key": "dom:javier",
            "confidence": 0.85,
        },
        {
            "event_type": "active_speaker_changed",
            "timestamp_epoch_ms": 2400,
            "display_name": "Javier",
            "participant_key": "dom:javier",
            "confidence": 0.85,
        },
    ]
    doc = attribute_segments(
        segments,
        microphone_audio=mic,
        system_audio=sys,
        local_participant_name="Javier",
        meet_events=events,
        recording_started_at_epoch_ms=started,
    )
    assert doc["speakers"]["SPEAKER_00"]["attributed_name"] == "Javier"
    assert doc["speakers"]["SPEAKER_00"]["source"] == "combined"


def test_write_attributed_transcript_roundtrip(tmp_path):
    paths = run_paths_for_directory(tmp_path)
    _dual_track_wavs(
        tmp_path,
        mic_levels=[(0.0, 2.0, 12000)],
        sys_levels=[(0.0, 2.0, 300)],
        duration_s=2.0,
    )
    whisper = tmp_path / "reunion_mezclada.json"
    whisper.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "start": 0.0,
                        "end": 2.0,
                        "text": "Hola.",
                        "speaker": "SPEAKER_00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    write_session_meta(
        paths.session_meta,
        {"session_id": "s1", "recording_started_at_epoch_ms": 0},
    )
    doc = write_attributed_transcript(
        whisper,
        paths.attributed_transcript,
        paths,
        local_participant_name="Javier",
    )
    assert paths.attributed_transcript.is_file()
    loaded = json.loads(paths.attributed_transcript.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == 1
    assert loaded["speakers"]["SPEAKER_00"]["attributed_name"] == "Javier"
    assert doc["segments"][0]["speaker_id"] == "SPEAKER_00"


def test_merge_conflict_drops_both_names():
    mic = SpeakerAttribution(
        speaker_id="SPEAKER_00",
        attributed_name="Javier",
        confidence=0.8,
        source="local_microphone",
        evidence={},
    )
    meet = {
        "SPEAKER_00": SpeakerAttribution(
            speaker_id="SPEAKER_00",
            attributed_name="Nacho",
            confidence=0.8,
            source="meet_active_speaker",
            evidence={"meet_event_refs": []},
        )
    }
    assert merge_speaker_attributions(mic, meet) == {}
