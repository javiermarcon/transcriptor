from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .audio import ffprobe_duration
from .meet_events import load_session_meta
from .models import RunPaths
from .spatial_cues import (
    DEFAULT_SPATIAL_CUE_PATTERNS,
    compile_patterns,
    find_spatial_cues,
    parse_extra_patterns,
    segment_as_cue_input,
)

SCHEMA_VERSION = 1
REVIEW_STATUSES = frozenset({"pending", "useful", "insufficient", "incorrect"})
ReviewStatus = Literal["pending", "useful", "insufficient", "incorrect"]

Runner = Callable[..., subprocess.CompletedProcess[str]]

# Documentado en docs/VISUAL_EVIDENCE.md: WhisperX ≈ audio mezclado; MP4 paralelo.
DEFAULT_CONTEXT_BEFORE_S = 1.5
DEFAULT_CONTEXT_AFTER_S = 2.5
DEFAULT_FRAME_INTERVAL_S = 1.0
DEFAULT_MAX_FRAMES_PER_CANDIDATE = 4
# Redondeo para deduplicar fotogramas cercanos (evita un JPG por cada 0.05 s).
FRAME_DEDUP_QUANTUM_S = 0.25


@dataclass(frozen=True)
class VisualEvidenceSettings:
    context_before_s: float = DEFAULT_CONTEXT_BEFORE_S
    context_after_s: float = DEFAULT_CONTEXT_AFTER_S
    frame_interval_s: float = DEFAULT_FRAME_INTERVAL_S
    max_frames_per_candidate: int = DEFAULT_MAX_FRAMES_PER_CANDIDATE
    extra_patterns: tuple[tuple[str, str], ...] = ()
    jpeg_quality: int = 3  # FFmpeg -q:v (2-5 típico)


def load_visual_evidence_settings_from_env(
    environ: dict[str, str] | None = None,
) -> VisualEvidenceSettings:
    import os

    env = environ if environ is not None else os.environ

    def _float(name: str, default: float) -> float:
        raw = env.get(name, "").strip()
        if not raw:
            return default
        value = float(raw)
        if value < 0:
            raise ValueError(f"{name} no puede ser negativo")
        return value

    def _int(name: str, default: int) -> int:
        raw = env.get(name, "").strip()
        if not raw:
            return default
        value = int(raw)
        if value < 1:
            raise ValueError(f"{name} debe ser >= 1")
        return value

    return VisualEvidenceSettings(
        context_before_s=_float("VISUAL_EVIDENCE_CONTEXT_BEFORE_S", DEFAULT_CONTEXT_BEFORE_S),
        context_after_s=_float("VISUAL_EVIDENCE_CONTEXT_AFTER_S", DEFAULT_CONTEXT_AFTER_S),
        frame_interval_s=_float("VISUAL_EVIDENCE_FRAME_INTERVAL_S", DEFAULT_FRAME_INTERVAL_S),
        max_frames_per_candidate=_int(
            "VISUAL_EVIDENCE_MAX_FRAMES_PER_CANDIDATE", DEFAULT_MAX_FRAMES_PER_CANDIDATE
        ),
        extra_patterns=parse_extra_patterns(env.get("VISUAL_EVIDENCE_EXTRA_PATTERNS")),
        jpeg_quality=_int("VISUAL_EVIDENCE_JPEG_QUALITY", 3),
    )


def _quantize_timestamp(ts: float, quantum: float = FRAME_DEDUP_QUANTUM_S) -> float:
    if quantum <= 0:
        return ts
    return round(ts / quantum) * quantum


def plan_frame_timestamps(
    window_start: float,
    window_end: float,
    *,
    phrase_start: float,
    phrase_end: float,
    interval_s: float,
    max_frames: int,
) -> list[float]:
    """Elige instantes discretos en la ventana; evita un frame por cada segundo ciego."""
    if window_end <= window_start:
        return []
    mid = (phrase_start + phrase_end) / 2.0
    candidates = [window_start, mid, window_end]
    if interval_s > 0:
        t = window_start
        while t <= window_end + 1e-9:
            candidates.append(t)
            t += interval_s
    unique: list[float] = []
    seen: set[float] = set()
    for raw in sorted(candidates):
        q = _quantize_timestamp(max(window_start, min(window_end, raw)))
        if q in seen:
            continue
        seen.add(q)
        unique.append(q)
    if len(unique) <= max_frames:
        return unique
    # Conservar extremos y centro; muestrear el resto.
    mid_q = _quantize_timestamp(max(window_start, min(window_end, mid)))
    kept = {unique[0], unique[-1], mid_q}
    for ts in unique:
        if len(kept) >= max_frames:
            break
        kept.add(ts)
    return sorted(kept)[:max_frames]


def load_transcript_segments(paths: RunPaths) -> list[dict[str, Any]]:
    """Preferí transcripcion_atribuida.json; si no, reunion_mezclada.json (WhisperX)."""
    if paths.attributed_transcript.is_file():
        data = json.loads(paths.attributed_transcript.read_text(encoding="utf-8"))
        segments = data.get("segments")
        if isinstance(segments, list) and segments:
            return [dict(item) for item in segments if isinstance(item, dict)]
    if paths.json_result.is_file():
        data = json.loads(paths.json_result.read_text(encoding="utf-8"))
        segments = data.get("segments")
        if isinstance(segments, list) and segments:
            out: list[dict[str, Any]] = []
            for item in segments:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                speaker = item.get("speaker") or "SPEAKER_UNKNOWN"
                out.append(
                    {
                        "start": float(item.get("start") or 0.0),
                        "end": float(item.get("end") or item.get("start") or 0.0),
                        "text": text,
                        "speaker_id": str(speaker),
                        "attributed_name": None,
                    }
                )
            return out
    raise FileNotFoundError(
        f"No hay transcripción usable en {paths.directory} "
        f"(faltan {paths.attributed_transcript.name} y {paths.json_result.name})"
    )


def detect_candidates(
    segments: Sequence[dict[str, Any]],
    *,
    settings: VisualEvidenceSettings,
) -> list[dict[str, Any]]:
    patterns = compile_patterns(DEFAULT_SPATIAL_CUE_PATTERNS + settings.extra_patterns)
    candidates: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        text = segment_as_cue_input(segment)
        if not text:
            continue
        cues = find_spatial_cues(text, patterns)
        if not cues:
            continue
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or start)
        if end < start:
            end = start
        window_start = max(0.0, start - settings.context_before_s)
        window_end = end + settings.context_after_s
        candidates.append(
            {
                "id": f"ve-{index:04d}",
                "text": text,
                "speaker_id": segment.get("speaker_id") or segment.get("speaker") or "SPEAKER_UNKNOWN",
                "attributed_name": segment.get("attributed_name"),
                "start": start,
                "end": end,
                "selection_reasons": [
                    f"pattern:{cue.pattern_id}:{cue.matched_text}" for cue in cues
                ],
                "window_start": window_start,
                "window_end": window_end,
            }
        )
    return candidates


def extract_frame(
    video: Path,
    timestamp_s: float,
    output: Path,
    *,
    jpeg_quality: int = 3,
    runner: Runner = subprocess.run,
) -> None:
    """Extrae un JPG del stream de video.

    `reunion.mp4` suele traer audio AAC muxeado (misma mezcla). Acá se ignora
    el audio del contenedor (`-map 0:v:0 -an`); solo importa el fotograma.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    # -ss después de -i es más preciso (más lento); para evidencia local preferimos precisión.
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-ss",
        f"{timestamp_s:.3f}",
        "-map",
        "0:v:0",
        "-an",
        "-frames:v",
        "1",
        "-q:v",
        str(jpeg_quality),
        str(output),
    ]
    result = runner(command, check=False, text=True, capture_output=True)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
        detail = (result.stderr or result.stdout or "").strip() or f"code={result.returncode}"
        raise RuntimeError(f"FFmpeg no pudo extraer fotograma en t={timestamp_s:.3f}s: {detail}")


def _relative_to_meeting(path: Path, meeting_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(meeting_dir.resolve()))
    except ValueError:
        return str(path)


def probe_mp4_stream_durations(
    video: Path,
    runner: Runner = subprocess.run,
) -> dict[str, float | None]:
    """Duraciones de streams dentro del MP4 (video vs audio embebido)."""
    result = runner(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,duration",
            "-of",
            "json",
            str(video),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return {"mp4_video_stream_s": None, "mp4_audio_stream_s": None}
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {"mp4_video_stream_s": None, "mp4_audio_stream_s": None}
    video_s: float | None = None
    audio_s: float | None = None
    for stream in payload.get("streams") or []:
        if not isinstance(stream, dict):
            continue
        raw = stream.get("duration")
        try:
            duration = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            duration = None
        if stream.get("codec_type") == "video" and duration is not None:
            video_s = duration
        elif stream.get("codec_type") == "audio" and duration is not None:
            audio_s = duration
    return {"mp4_video_stream_s": video_s, "mp4_audio_stream_s": audio_s}


def build_sync_notes(
    *,
    video_duration: float | None,
    audio_duration: float | None,
    mp4_video_stream_s: float | None = None,
    mp4_audio_stream_s: float | None = None,
) -> dict[str, Any]:
    delta = None
    if video_duration is not None and audio_duration is not None:
        delta = round(video_duration - audio_duration, 3)
    mp4_av_delta = None
    if mp4_video_stream_s is not None and mp4_audio_stream_s is not None:
        mp4_av_delta = round(mp4_video_stream_s - mp4_audio_stream_s, 3)
    return {
        "assumption": (
            "Los timestamps de WhisperX están en segundos relativos al inicio de "
            "reunion_mezclada.wav. El MP4 se graba en el mismo proceso FFmpeg (video + "
            "audio AAC de la mezcla muxeados) y se asume alineado desde t≈0, con "
            "posible desfase A/V de décimas a ~1s. La extracción de evidencia usa "
            "solo el stream de video del MP4."
        ),
        "how_to_measure": (
            "1) ffprobe format duration de reunion.mp4 vs reunion_mezclada.wav. "
            "2) ffprobe stream duration video vs audio dentro del MP4. "
            "3) Reproducí el MP4 (tiene audio) en t=frase.start y contrastá el JPG."
        ),
        "video_duration_s": video_duration,
        "mixed_audio_duration_s": audio_duration,
        "video_minus_audio_s": delta,
        "mp4_video_stream_s": mp4_video_stream_s,
        "mp4_audio_stream_s": mp4_audio_stream_s,
        "mp4_video_minus_audio_stream_s": mp4_av_delta,
        "mp4_contains_mixed_audio": True,
        "does_not_identify_ui": (
            "Un fotograma cercano a «acá» no implica conocer el botón o componente señalado."
        ),
    }


def extract_visual_evidence(
    paths: RunPaths,
    *,
    settings: VisualEvidenceSettings | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    cfg = settings or load_visual_evidence_settings_from_env()
    meeting_dir = paths.directory
    meta = load_session_meta(paths.session_meta) or {}
    session_id = meta.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        session_id = meeting_dir.name

    if not paths.video.is_file() or paths.video.stat().st_size <= 0:
        raise FileNotFoundError(f"Video ausente o vacío: {paths.video}")

    try:
        video_duration = ffprobe_duration(paths.video, runner)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise RuntimeError(f"No se pudo leer duración del video: {exc}") from exc

    audio_duration: float | None = None
    if paths.mixed_audio.is_file():
        try:
            audio_duration = ffprobe_duration(paths.mixed_audio, runner)
        except (OSError, subprocess.CalledProcessError, ValueError):
            audio_duration = None

    stream_durations = probe_mp4_stream_durations(paths.video, runner)

    segments = load_transcript_segments(paths)
    raw_candidates = detect_candidates(segments, settings=cfg)

    frames_dir = paths.visual_evidence_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Deduplicación global de extracciones.
    extracted: dict[float, Path] = {}
    out_candidates: list[dict[str, Any]] = []

    for candidate in raw_candidates:
        errors: list[str] = []
        window_start = float(candidate["window_start"])
        window_end = float(candidate["window_end"])
        # Recortar a duración del video.
        if window_start >= video_duration:
            errors.append(
                f"Ventana fuera de rango del video "
                f"(window_start={window_start:.3f} >= duration={video_duration:.3f})"
            )
            out_candidates.append(
                {
                    **candidate,
                    "window_start": window_start,
                    "window_end": window_end,
                    "frames": [],
                    "review": {"status": "pending", "updated_at": None, "note": None},
                    "errors": errors,
                }
            )
            continue

        clipped_end = min(window_end, max(0.0, video_duration - 0.05))
        clipped_start = min(window_start, clipped_end)
        if clipped_end < window_end:
            errors.append(
                f"Ventana recortada al final del video "
                f"({window_end:.3f}s → {clipped_end:.3f}s)"
            )

        timestamps = plan_frame_timestamps(
            clipped_start,
            clipped_end,
            phrase_start=float(candidate["start"]),
            phrase_end=float(candidate["end"]),
            interval_s=cfg.frame_interval_s,
            max_frames=cfg.max_frames_per_candidate,
        )

        frames: list[dict[str, Any]] = []
        for ts in timestamps:
            q = _quantize_timestamp(ts)
            if q in extracted:
                frame_path = extracted[q]
                frames.append(
                    {
                        "path": _relative_to_meeting(frame_path, meeting_dir),
                        "timestamp_s": q,
                        "status": "reused",
                    }
                )
                continue
            filename = f"{candidate['id']}_t{int(q * 100):07d}.jpg"
            frame_path = frames_dir / filename
            try:
                extract_frame(
                    paths.video,
                    q,
                    frame_path,
                    jpeg_quality=cfg.jpeg_quality,
                    runner=runner,
                )
                extracted[q] = frame_path
                frames.append(
                    {
                        "path": _relative_to_meeting(frame_path, meeting_dir),
                        "timestamp_s": q,
                        "status": "ok",
                    }
                )
            except (OSError, RuntimeError) as exc:
                errors.append(str(exc))
                frames.append(
                    {
                        "path": _relative_to_meeting(frame_path, meeting_dir),
                        "timestamp_s": q,
                        "status": "error",
                    }
                )

        out_candidates.append(
            {
                **candidate,
                "window_start": clipped_start,
                "window_end": clipped_end,
                "frames": frames,
                "review": {"status": "pending", "updated_at": None, "note": None},
                "errors": errors,
            }
        )

    index: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "meeting_dir": str(meeting_dir),
        "video": _relative_to_meeting(paths.video, meeting_dir),
        "generated_at": datetime.now(UTC).isoformat(),
        "settings": {
            "context_before_s": cfg.context_before_s,
            "context_after_s": cfg.context_after_s,
            "frame_interval_s": cfg.frame_interval_s,
            "max_frames_per_candidate": cfg.max_frames_per_candidate,
            "frame_dedup_quantum_s": FRAME_DEDUP_QUANTUM_S,
            "extra_pattern_ids": [item[0] for item in cfg.extra_patterns],
        },
        "sync": build_sync_notes(
            video_duration=video_duration,
            audio_duration=audio_duration,
            mp4_video_stream_s=stream_durations.get("mp4_video_stream_s"),
            mp4_audio_stream_s=stream_durations.get("mp4_audio_stream_s"),
        ),
        "candidates": out_candidates,
    }

    # Preservar revisiones previas si el índice ya existía.
    if paths.visual_evidence_index.is_file():
        try:
            previous = json.loads(paths.visual_evidence_index.read_text(encoding="utf-8"))
            prev_by_id = {
                item["id"]: item.get("review")
                for item in previous.get("candidates", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            for item in out_candidates:
                prior = prev_by_id.get(item["id"])
                if isinstance(prior, dict) and prior.get("status") in REVIEW_STATUSES:
                    item["review"] = {
                        "status": prior["status"],
                        "updated_at": prior.get("updated_at"),
                        "note": prior.get("note"),
                    }
        except (OSError, json.JSONDecodeError, TypeError, KeyError):
            pass

    paths.visual_evidence_dir.mkdir(parents=True, exist_ok=True)
    paths.visual_evidence_index.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return index


def set_review_status(
    paths: RunPaths,
    candidate_id: str,
    status: str,
    *,
    note: str | None = None,
) -> dict[str, Any]:
    if status not in REVIEW_STATUSES:
        raise ValueError(
            f"Estado de revisión inválido: {status!r}. "
            f"Usá uno de: {', '.join(sorted(REVIEW_STATUSES))}"
        )
    if not paths.visual_evidence_index.is_file():
        raise FileNotFoundError(
            f"No existe {paths.visual_evidence_index}. "
            "Ejecutá primero la extracción de evidencia visual."
        )
    index = json.loads(paths.visual_evidence_index.read_text(encoding="utf-8"))
    found = False
    for item in index.get("candidates", []):
        if not isinstance(item, dict):
            continue
        if item.get("id") != candidate_id:
            continue
        item["review"] = {
            "status": status,
            "updated_at": datetime.now(UTC).isoformat(),
            "note": note,
        }
        found = True
        break
    if not found:
        raise KeyError(f"No hay candidato {candidate_id!r} en el índice de evidencia visual")
    paths.visual_evidence_index.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return index
