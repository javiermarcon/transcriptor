from __future__ import annotations

import os
from collections.abc import Callable
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
    )
