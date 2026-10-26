from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .audio_energy import rms_for_interval
from .meet_events import load_meet_events, load_session_meta
from .models import RunPaths
from .postprocess import clean_segments, collapse_repeated_sentences, segment_speaker

SCHEMA_VERSION = 1

AttributionSource = Literal[
    "local_microphone",
    "local_microphone_adjacent",
    "meet_active_speaker",
    "combined",
]

# Desfase esperado: polling Meet ~2s + alineación WhisperX.
DEFAULT_SYNC_UNCERTAINTY_S = 1.5
DEFAULT_ACTIVE_HOLD_S = 2.0
# Mic: el hablante local debe dominar claramente frente al resto.
MIC_DOMINANCE_MIN = 0.62
MIC_MIN_SPEECH_S = 1.5
# Diarización a veces parte la misma voz local en otro SPEAKER_* breve
# intercalado; se promueve si queda a ≤ este hueco de un ancla mic.
LOCAL_ADJACENCY_GAP_S = 2.0
LOCAL_ADJACENCY_RUN_GAP_S = 5.0
LOCAL_ADJACENCY_CONFIDENCE = 0.62
# Meet: votos suficientes y margen frente al segundo nombre.
# ~2 solapes fuertes con confidence≈0.7; un solo blink visual no alcanza.
MEET_MIN_WEIGHTED_VOTES = 1.2
MEET_VOTE_MARGIN = 1.25
MEET_MIN_EVENT_CONFIDENCE = 0.35

# Solapamiento mínimo del segmento con la ventana del evento (tras incertidumbre).
MEET_MIN_OVERLAP_FRACTION = 0.35
SEGMENT_ATTR_CONFIDENCE_FLOOR = 0.55


@dataclass(frozen=True)
class SpeakerAttribution:
    speaker_id: str
    attributed_name: str | None
    confidence: float
    source: AttributionSource | None
    evidence: dict[str, Any]


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _mic_dominance_scores(
    segments: Sequence[dict[str, Any]],
    microphone_audio: Path,
    system_audio: Path,
) -> dict[str, dict[str, float]]:
    """Por speaker_id: duración y media ponderada de mic/(mic+sys)."""
    totals: dict[str, float] = defaultdict(float)
    weighted: dict[str, float] = defaultdict(float)
    for segment in segments:
        speaker = segment_speaker(segment)
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or start)
        duration = max(0.0, end - start)
        if duration <= 0:
            continue
        mic = rms_for_interval(microphone_audio, start, end)
        sys = rms_for_interval(system_audio, start, end)
        if mic is None or sys is None:
            continue
        denom = mic + sys
        if denom <= 1e-9:
            continue
        dominance = mic / denom
        totals[speaker] += duration
        weighted[speaker] += dominance * duration
    scores: dict[str, dict[str, float]] = {}
    for speaker, duration in totals.items():
        scores[speaker] = {
            "speech_s": duration,
            "mic_dominance": weighted[speaker] / duration if duration else 0.0,
        }
    return scores


def resolve_local_microphone_attributions(
    mic_scores: dict[str, dict[str, float]],
    local_name: str,
) -> dict[str, SpeakerAttribution]:
    """Atribuye al mic local todos los SPEAKER_* con dominio claro.

    WhisperX a veces parte la misma voz en varios IDs. Si cada cluster supera
    el umbral de micrófono, todos reciben el mismo nombre local.
    """
    name = local_name.strip()
    if not name:
        return {}
    eligible = [
        (speaker, data["mic_dominance"], data["speech_s"])
        for speaker, data in mic_scores.items()
        if data["speech_s"] >= MIC_MIN_SPEECH_S and data["mic_dominance"] >= MIC_DOMINANCE_MIN
    ]
    if not eligible:
        return {}
    best_dom = max(item[1] for item in eligible)
    result: dict[str, SpeakerAttribution] = {}
    for speaker_id, dom, speech in eligible:
        confidence = min(0.92, 0.55 + (dom - MIC_DOMINANCE_MIN) + max(0.0, best_dom - dom) * 0.5)
        result[speaker_id] = SpeakerAttribution(
            speaker_id=speaker_id,
            attributed_name=name,
            confidence=round(confidence, 3),
            source="local_microphone",
            evidence={
                "mic_dominance": round(dom, 3),
                "best_mic_dominance": round(best_dom, 3),
                "speech_s": round(speech, 3),
                "local_clusters": len(eligible),
            },
        )
    return result


def resolve_local_microphone_attribution(
    mic_scores: dict[str, dict[str, float]],
    local_name: str,
) -> SpeakerAttribution | None:
    """Compat: devuelve la mejor atribución local o None."""
    attrs = resolve_local_microphone_attributions(mic_scores, local_name)
    if not attrs:
        return None
    return max(attrs.values(), key=lambda item: item.confidence)


def _ambiguous_display_names(events: Sequence[dict[str, Any]]) -> set[str]:
    """Nombres con más de un participant_key distinto → no atribuibles con seguridad."""
    keys_by_name: dict[str, set[str]] = defaultdict(set)
    for event in events:
        display = event.get("display_name")
        key = event.get("participant_key")
        if not isinstance(display, str) or not display.strip():
            continue
        if not isinstance(key, str) or not key.strip():
            continue
        keys_by_name[_normalize_name(display)].add(key.strip())
    return {name for name, keys in keys_by_name.items() if len(keys) > 1}


def _active_speaker_windows(
    events: Sequence[dict[str, Any]],
    recording_started_at_epoch_ms: float,
    *,
    sync_uncertainty_s: float = DEFAULT_SYNC_UNCERTAINTY_S,
    hold_s: float = DEFAULT_ACTIVE_HOLD_S,
) -> list[dict[str, Any]]:
    """Ventanas relativas (segundos de audio) para active_speaker_changed con nombre."""
    timed: list[tuple[float, dict[str, Any]]] = []
    for event in events:
        if event.get("event_type") != "active_speaker_changed":
            continue
        display = event.get("display_name")
        if not isinstance(display, str) or not display.strip():
            continue
        ts = event.get("timestamp_epoch_ms")
        if not isinstance(ts, (int, float)):
            continue
        conf = event.get("confidence", 0.5)
        if not isinstance(conf, (int, float)):
            conf = 0.5
        if float(conf) < MEET_MIN_EVENT_CONFIDENCE:
            continue
        rel = (float(ts) - recording_started_at_epoch_ms) / 1000.0
        timed.append(
            (
                rel,
                {
                    "display_name": display.strip(),
                    "participant_key": event.get("participant_key"),
                    "confidence": float(conf),
                    "timestamp_epoch_ms": float(ts),
                    "rel_s": rel,
                    "source": event.get("source"),
                },
            )
        )
    timed.sort(key=lambda item: item[0])
    windows: list[dict[str, Any]] = []
    for index, (rel, payload) in enumerate(timed):
        next_rel = timed[index + 1][0] if index + 1 < len(timed) else rel + hold_s
        # No extender más allá del próximo cambio ni del hold.
        end = min(rel + hold_s, max(rel, next_rel))
        windows.append(
            {
                **payload,
                "window_start": rel - sync_uncertainty_s,
                "window_end": end + sync_uncertainty_s,
            }
        )
    return windows


def meet_votes_for_speakers(
    segments: Sequence[dict[str, Any]],
    events: Sequence[dict[str, Any]],
    recording_started_at_epoch_ms: float,
    *,
    sync_uncertainty_s: float = DEFAULT_SYNC_UNCERTAINTY_S,
) -> dict[str, dict[str, Any]]:
    """Agrega votos ponderados nombre→speaker a partir de active_speaker_changed."""
    ambiguous = _ambiguous_display_names(events)
    windows = _active_speaker_windows(
        events,
        recording_started_at_epoch_ms,
        sync_uncertainty_s=sync_uncertainty_s,
    )
    # speaker -> name_norm -> {weight, display_name, refs}
    votes: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(lambda: {"weight": 0.0, "display_name": "", "refs": []})
    )

    for segment in segments:
        speaker = segment_speaker(segment)
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or start)
        duration = max(1e-6, end - start)
        for window in windows:
            name_norm = _normalize_name(window["display_name"])
            if name_norm in ambiguous:
                continue
            overlap = _overlap(start, end, window["window_start"], window["window_end"])
            frac = overlap / duration
            if frac < MEET_MIN_OVERLAP_FRACTION:
                continue
            weight = frac * float(window["confidence"])
            bucket = votes[speaker][name_norm]
            bucket["weight"] += weight
            bucket["display_name"] = window["display_name"]
            ref = {
                "timestamp_epoch_ms": window["timestamp_epoch_ms"],
                "rel_s": round(window["rel_s"], 3),
                "display_name": window["display_name"],
                "confidence": window["confidence"],
                "overlap_fraction": round(frac, 3),
            }
            if window.get("participant_key"):
                ref["participant_key"] = window["participant_key"]
            if window.get("source"):
                ref["source"] = window["source"]
            if len(bucket["refs"]) < 12:
                bucket["refs"].append(ref)

    return {speaker: dict(names) for speaker, names in votes.items()}


def resolve_meet_attributions(
    meet_votes: dict[str, dict[str, Any]],
) -> dict[str, SpeakerAttribution]:
    resolved: dict[str, SpeakerAttribution] = {}
    # Evitar que dos speakers reclamen el mismo nombre con evidencia similar.
    claimed_names: dict[str, tuple[str, float]] = {}

    candidates: list[tuple[str, str, float, dict[str, Any]]] = []
    for speaker, names in meet_votes.items():
        ranked = sorted(names.items(), key=lambda item: item[1]["weight"], reverse=True)
        if not ranked:
            continue
        _best_norm, best = ranked[0]
        second_w = ranked[1][1]["weight"] if len(ranked) > 1 else 0.0
        if best["weight"] < MEET_MIN_WEIGHTED_VOTES:
            continue
        if second_w > 0 and best["weight"] / second_w < MEET_VOTE_MARGIN:
            continue
        confidence = min(0.88, 0.4 + 0.15 * best["weight"])
        candidates.append((speaker, best["display_name"], confidence, best))

    candidates.sort(key=lambda item: item[2], reverse=True)
    for speaker, display_name, confidence, best in candidates:
        name_norm = _normalize_name(display_name)
        previous = claimed_names.get(name_norm)
        if previous is not None:
            prev_speaker, prev_conf = previous
            # Conflicto de nombre entre speakers: no atribuir a ninguno si están cerca.
            if abs(prev_conf - confidence) < 0.12:
                resolved.pop(prev_speaker, None)
                continue
            if confidence <= prev_conf:
                continue
            resolved.pop(prev_speaker, None)
        claimed_names[name_norm] = (speaker, confidence)
        resolved[speaker] = SpeakerAttribution(
            speaker_id=speaker,
            attributed_name=display_name,
            confidence=round(confidence, 3),
            source="meet_active_speaker",
            evidence={
                "weighted_votes": round(best["weight"], 3),
                "meet_event_refs": list(best["refs"]),
            },
        )
    return resolved


def merge_speaker_attributions(
    mic_attrs: dict[str, SpeakerAttribution] | SpeakerAttribution | None,
    meet_attrs: dict[str, SpeakerAttribution],
) -> dict[str, SpeakerAttribution]:
    """Combina fuentes; ante conflicto de nombre distinto en el mismo speaker, descarta."""
    merged = dict(meet_attrs)
    if mic_attrs is None:
        return merged
    if isinstance(mic_attrs, SpeakerAttribution):
        mic_map = {mic_attrs.speaker_id: mic_attrs}
    else:
        mic_map = mic_attrs
    for speaker_id, mic_attr in mic_map.items():
        existing = merged.get(speaker_id)
        if existing is None:
            merged[speaker_id] = mic_attr
            continue
        if _normalize_name(existing.attributed_name or "") == _normalize_name(
            mic_attr.attributed_name or ""
        ):
            merged[speaker_id] = SpeakerAttribution(
                speaker_id=speaker_id,
                attributed_name=mic_attr.attributed_name,
                confidence=round(
                    min(0.95, (existing.confidence + mic_attr.confidence) / 2 + 0.08),
                    3,
                ),
                source="combined",
                evidence={
                    "local_microphone": mic_attr.evidence,
                    "meet_active_speaker": existing.evidence,
                },
            )
            continue
        # Conflicto mic vs Meet sobre el mismo SPEAKER_*: no inventar.
        merged.pop(speaker_id, None)
    return merged


def _interval_gap(a0: float, a1: float, b0: float, b1: float) -> float:
    if a1 < b0:
        return b0 - a1
    if b1 < a0:
        return a0 - b1
    return 0.0


def _contiguous_speaker_runs(
    out_segments: Sequence[dict[str, Any]],
) -> list[list[int]]:
    """Índices de tramos consecutivos del mismo speaker_id (huecos cortos)."""
    runs: list[list[int]] = []
    current: list[int] = []
    prev_id: str | None = None
    prev_end: float | None = None
    for index, segment in enumerate(out_segments):
        speaker_id = str(segment["speaker_id"])
        start = float(segment["start"])
        end = float(segment["end"])
        if (
            current
            and prev_id == speaker_id
            and prev_end is not None
            and start - prev_end <= LOCAL_ADJACENCY_RUN_GAP_S
        ):
            current.append(index)
        else:
            if current:
                runs.append(current)
            current = [index]
            prev_id = speaker_id
        prev_end = end
    if current:
        runs.append(current)
    return runs


def promote_local_adjacent_segments(
    document: dict[str, Any],
    *,
    local_participant_name: str | None,
    speaker_map: dict[str, SpeakerAttribution],
) -> dict[str, Any]:
    """Nombra tramos SPEAKER_* huérfanos pegados a voz local atribuida por mic.

    WhisperX a veces parte la misma voz en otro ID entre dos frases locales.
    No encadena atribuciones adyacentes entre sí (evita arrastrar audio de
    pantalla/compartidos lejanos).
    """
    name = (local_participant_name or "").strip()
    if not name:
        return document
    local_norm = _normalize_name(name)
    foreign_ids = {
        speaker_id
        for speaker_id, attr in speaker_map.items()
        if attr.attributed_name
        and _normalize_name(attr.attributed_name) != local_norm
    }
    segments = document["segments"]
    anchors: list[tuple[float, float]] = []
    for segment in segments:
        attribution = segment.get("attribution") or {}
        if attribution.get("source") not in {"local_microphone", "combined"}:
            continue
        attributed = segment.get("attributed_name")
        if not isinstance(attributed, str) or _normalize_name(attributed) != local_norm:
            continue
        anchors.append((float(segment["start"]), float(segment["end"])))
    if not anchors:
        return document

    promoted = 0
    for run in _contiguous_speaker_runs(segments):
        speaker_id = str(segments[run[0]]["speaker_id"])
        if speaker_id in foreign_ids:
            continue
        if any(segments[index].get("attributed_name") for index in run):
            continue
        run_start = float(segments[run[0]]["start"])
        run_end = float(segments[run[-1]]["end"])
        if not any(
            _interval_gap(run_start, run_end, a0, a1) <= LOCAL_ADJACENCY_GAP_S
            for a0, a1 in anchors
        ):
            continue
        for index in run:
            segments[index]["attributed_name"] = name
            segments[index]["attribution"] = {
                "confidence": LOCAL_ADJACENCY_CONFIDENCE,
                "source": "local_microphone_adjacent",
                "meet_event_refs": [],
            }
        promoted += 1

    if promoted:
        notes = list(document.get("notes") or [])
        notes.append(
            f"Se atribuyeron {promoted} tramo(s) SPEAKER_* intercalados junto a "
            f"voz local (hueco ≤ {LOCAL_ADJACENCY_GAP_S:g}s); no implica el ID entero."
        )
        document["notes"] = notes
    return document


def render_attributed_speakers_txt(segments: Sequence[dict[str, Any]]) -> str:
    """Texto [Nombre] o [SPEAKER_XX] agrupando turnos consecutivos del mismo rótulo."""
    speaker_lines: list[str] = []
    current_label: str | None = None
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_label, current_parts
        text = " ".join(part for part in current_parts if part).strip()
        if text:
            text = collapse_repeated_sentences(text)
            speaker_lines.append(f"[{current_label or 'SPEAKER_UNKNOWN'}] {text}")
        current_label = None
        current_parts = []

    for segment in segments:
        speaker_id = str(segment.get("speaker_id") or "SPEAKER_UNKNOWN")
        attributed = segment.get("attributed_name")
        label = (
            str(attributed).strip()
            if isinstance(attributed, str) and attributed.strip()
            else speaker_id
        )
        text = str(segment.get("text") or "").strip()
        if current_label is None:
            current_label = label
        elif label != current_label:
            flush()
            current_label = label
        current_parts.append(text)
    flush()
    return "\n".join(speaker_lines).rstrip() + "\n"


def build_attributed_document(
    segments: Sequence[dict[str, Any]],
    speaker_map: dict[str, SpeakerAttribution],
    *,
    notes: Sequence[str] | None = None,
) -> dict[str, Any]:
    out_segments: list[dict[str, Any]] = []
    for segment in segments:
        speaker_id = segment_speaker(segment)
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or start)
        text = str(segment.get("text", "")).strip()
        attr = speaker_map.get(speaker_id)
        entry: dict[str, Any] = {
            "start": start,
            "end": end,
            "text": text,
            "speaker_id": speaker_id,
            "attributed_name": None,
            "attribution": {
                "confidence": None,
                "source": None,
                "meet_event_refs": [],
            },
        }
        if attr is not None and attr.attributed_name and attr.confidence >= SEGMENT_ATTR_CONFIDENCE_FLOOR:
            entry["attributed_name"] = attr.attributed_name
            refs = []
            evidence = attr.evidence
            if "meet_event_refs" in evidence:
                refs = list(evidence["meet_event_refs"])
            elif isinstance(evidence.get("meet_active_speaker"), dict):
                refs = list(evidence["meet_active_speaker"].get("meet_event_refs") or [])
            entry["attribution"] = {
                "confidence": attr.confidence,
                "source": attr.source,
                "meet_event_refs": refs,
            }
        out_segments.append(entry)

    speakers_out: dict[str, Any] = {}
    for speaker_id, attr in sorted(speaker_map.items()):
        speakers_out[speaker_id] = {
            "attributed_name": attr.attributed_name,
            "confidence": attr.confidence,
            "source": attr.source,
            "evidence": attr.evidence,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "notes": list(notes or []),
        "speakers": speakers_out,
        "segments": out_segments,
    }


def attribute_segments(
    segments: Sequence[dict[str, Any]],
    *,
    microphone_audio: Path | None = None,
    system_audio: Path | None = None,
    meet_events: Sequence[dict[str, Any]] | None = None,
    recording_started_at_epoch_ms: float | None = None,
    local_participant_name: str | None = None,
    sync_uncertainty_s: float = DEFAULT_SYNC_UNCERTAINTY_S,
) -> dict[str, Any]:
    notes: list[str] = [
        "Los speaker_id (SPEAKER_XX) son los de WhisperX/diarización y no se modifican.",
        "attributed_name solo se completa con evidencia suficiente; si no, queda null.",
        "Estar en el roster de Meet no basta para atribuir un segmento.",
        "transcripcion_speakers.txt usa el nombre atribuido cuando existe; si no, el SPEAKER_XX.",
    ]
    mic_attrs: dict[str, SpeakerAttribution] = {}
    if (
        local_participant_name
        and local_participant_name.strip()
        and microphone_audio is not None
        and system_audio is not None
        and microphone_audio.is_file()
        and system_audio.is_file()
    ):
        scores = _mic_dominance_scores(segments, microphone_audio, system_audio)
        mic_attrs = resolve_local_microphone_attributions(scores, local_participant_name)
        if not mic_attrs:
            notes.append(
                "No hubo un SPEAKER_* con dominio claro del micrófono local; "
                "no se atribuyó el participante local."
            )
    elif local_participant_name and local_participant_name.strip():
        notes.append(
            "LOCAL_PARTICIPANT_NAME está configurado pero faltan microfono.wav/sistema.wav; "
            "no se usó atribución por micrófono."
        )

    meet_attrs: dict[str, SpeakerAttribution] = {}
    if meet_events and recording_started_at_epoch_ms is not None:
        votes = meet_votes_for_speakers(
            segments,
            meet_events,
            recording_started_at_epoch_ms,
            sync_uncertainty_s=sync_uncertainty_s,
        )
        meet_attrs = resolve_meet_attributions(votes)
        if not meet_attrs:
            notes.append(
                "Hubo eventos Meet pero ninguna atribución superó umbrales "
                "(solapamiento, confianza, margen o nombres ambiguos)."
            )
    elif meet_events:
        notes.append(
            "Hay meet_events.jsonl pero falta recording_started_at_epoch_ms en session.json; "
            "no se alinearon eventos visuales."
        )

    speaker_map = merge_speaker_attributions(mic_attrs, meet_attrs)
    document = build_attributed_document(segments, speaker_map, notes=notes)
    return promote_local_adjacent_segments(
        document,
        local_participant_name=local_participant_name,
        speaker_map=speaker_map,
    )


def write_attributed_transcript(
    whisperx_json: Path,
    output_path: Path,
    paths: RunPaths,
    *,
    local_participant_name: str | None = None,
    hallucination_phrases: Sequence[str] | None = None,
    sync_uncertainty_s: float = DEFAULT_SYNC_UNCERTAINTY_S,
) -> dict[str, Any]:
    data = json.loads(whisperx_json.read_text(encoding="utf-8"))
    segments = clean_segments(
        list(data.get("segments") or []),
        hallucination_phrases=hallucination_phrases,
    )
    meta = load_session_meta(paths.session_meta) or {}
    started = meta.get("recording_started_at_epoch_ms")
    started_f = float(started) if isinstance(started, (int, float)) else None
    events = load_meet_events(paths.meet_events)
    # session.json puede traer el nombre local de la grabación NM.
    local_name = local_participant_name
    if not (local_name and str(local_name).strip()):
        meta_name = meta.get("local_participant_name")
        if isinstance(meta_name, str) and meta_name.strip():
            local_name = meta_name.strip()
    document = attribute_segments(
        segments,
        microphone_audio=paths.microphone_audio,
        system_audio=paths.system_audio,
        meet_events=events,
        recording_started_at_epoch_ms=started_f,
        local_participant_name=local_name,
        sync_uncertainty_s=sync_uncertainty_s,
    )
    output_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths.speaker_transcript.write_text(
        render_attributed_speakers_txt(document["segments"]),
        encoding="utf-8",
    )
    return document
