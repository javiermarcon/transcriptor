from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    whisperx_bin: Path | None
    whisper_ctranslate2_bin: Path | None
    hf_token: str | None
    model: str
    batch_size: int
    threads: int
    device: str
    compute_type: str
    volume_system: float
    volume_microphone: float
    vad_method: str
    vad_onset: float
    vad_offset: float
    chunk_size: int
    sink: str | None
    microphone: str | None
    record_video: bool = False
    video_monitor: str = "primary"
    video_fps: int = 10
    temperature: float = 0.0
    best_of: int = 5
    beam_size: int = 5
    patience: float = 1.0
    length_penalty: float | None = None
    suppress_tokens: str = "-1"
    suppress_numerals: bool = False
    temperature_increment_on_fallback: float = 0.2
    compression_ratio_threshold: float = 2.4
    logprob_threshold: float = -1.0
    no_speech_threshold: float = 0.6
    min_speakers: int | None = None
    max_speakers: int | None = None
    condition_on_previous_text: bool = False
    filter_hallucinations: bool = True
    extra_hallucination_phrases: tuple[str, ...] = ()


def _existing_executable(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_file() and os.access(path, os.X_OK) else None


def detect_cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    try:
        return bool(torch.cuda.is_available())
    except (AttributeError, RuntimeError, OSError):
        return False


def resolve_device_and_compute_type(
    device: str,
    compute_type: str | None,
    *,
    cuda_available: Callable[[], bool] | None = None,
) -> tuple[str, str]:
    normalized = device.strip().lower()
    if normalized not in {"auto", "cpu", "cuda"}:
        raise ValueError(
            f"DEVICE inválido: {device!r}. Usá auto, cpu o cuda."
        )
    probe = cuda_available or detect_cuda_available
    if normalized == "auto":
        resolved_device = "cuda" if probe() else "cpu"
    else:
        resolved_device = normalized

    if compute_type is None or not compute_type.strip():
        resolved_compute = "float16" if resolved_device == "cuda" else "int8"
    else:
        resolved_compute = compute_type.strip()
    return resolved_device, resolved_compute


def parse_phrase_list(value: str | None) -> tuple[str, ...]:
    if value is None or not value.strip():
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "si", "sí", "on"}


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return int(raw)


def _optional_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return float(raw)


def load_settings(
    project_dir: Path | None = None,
    *,
    cuda_available: Callable[[], bool] | None = None,
) -> Settings:
    project_dir = (project_dir or Path.cwd()).resolve()
    default_venv = project_dir / ".venv"

    whisperx = _existing_executable(os.getenv("WHISPERX_BIN"))
    if whisperx is None:
        whisperx = _existing_executable(str(default_venv / "bin/whisperx"))

    ctranslate = _existing_executable(os.getenv("WHISPER_CTRANSLATE2_BIN"))
    if ctranslate is None:
        ctranslate = _existing_executable(str(default_venv / "bin/whisper-ctranslate2"))

    device, compute_type = resolve_device_and_compute_type(
        os.getenv("DEVICE", "auto"),
        os.getenv("COMPUTE_TYPE"),
        cuda_available=cuda_available,
    )

    video_fps = int(os.getenv("VIDEO_FPS", "10"))
    if video_fps <= 0:
        raise ValueError(f"VIDEO_FPS debe ser mayor que cero: {video_fps}")

    video_monitor = os.getenv("VIDEO_MONITOR", "primary").strip()
    if not video_monitor:
        raise ValueError("VIDEO_MONITOR no puede estar vacío")

    return Settings(
        base_dir=Path(os.getenv("BASE_DIR", str(Path.home() / "proyectos/meetings/textos_reuniones"))).expanduser(),
        whisperx_bin=whisperx,
        whisper_ctranslate2_bin=ctranslate,
        hf_token=os.getenv("HF_TOKEN") or None,
        model=os.getenv("MODELO", "large-v3"),
        batch_size=int(os.getenv("BATCH_SIZE", "2")),
        threads=int(os.getenv("THREADS", "4")),
        device=device,
        compute_type=compute_type,
        volume_system=float(os.getenv("VOLUMEN_SISTEMA", "0.70")),
        volume_microphone=float(os.getenv("VOLUMEN_MICROFONO", "2.00")),
        vad_method=os.getenv("VAD_METHOD", "pyannote"),
        vad_onset=float(os.getenv("VAD_ONSET", "0.500")),
        vad_offset=float(os.getenv("VAD_OFFSET", "0.363")),
        chunk_size=int(os.getenv("CHUNK_SIZE", "30")),
        sink=os.getenv("SINK") or None,
        microphone=os.getenv("MIC") or None,
        record_video=_env_bool("RECORD_VIDEO", True),
        video_monitor=video_monitor,
        video_fps=video_fps,
        temperature=float(os.getenv("TEMPERATURE", "0")),
        best_of=int(os.getenv("BEST_OF", "5")),
        beam_size=int(os.getenv("BEAM_SIZE", "5")),
        patience=float(os.getenv("PATIENCE", "1.0")),
        length_penalty=_optional_float("LENGTH_PENALTY"),
        suppress_tokens=os.getenv("SUPPRESS_TOKENS", "-1"),
        suppress_numerals=_env_bool("SUPPRESS_NUMERALS", False),
        temperature_increment_on_fallback=float(
            os.getenv("TEMPERATURE_INCREMENT_ON_FALLBACK", "0.2")
        ),
        compression_ratio_threshold=float(os.getenv("COMPRESSION_RATIO_THRESHOLD", "2.4")),
        logprob_threshold=float(os.getenv("LOGPROB_THRESHOLD", "-1.0")),
        no_speech_threshold=float(os.getenv("NO_SPEECH_THRESHOLD", "0.6")),
        min_speakers=_optional_int("MIN_SPEAKERS"),
        max_speakers=_optional_int("MAX_SPEAKERS"),
        condition_on_previous_text=_env_bool("CONDITION_ON_PREVIOUS_TEXT", False),
        filter_hallucinations=_env_bool("FILTER_HALLUCINATIONS", True),
        extra_hallucination_phrases=parse_phrase_list(os.getenv("EXTRA_HALLUCINATION_PHRASES")),
    )


def hallucination_phrases_for(settings: Settings, defaults: Sequence[str]) -> tuple[str, ...]:
    if not settings.filter_hallucinations:
        return ()
    merged: list[str] = []
    seen: set[str] = set()
    for phrase in (*defaults, *settings.extra_hallucination_phrases):
        key = phrase.casefold().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(phrase.strip())
    return tuple(merged)
