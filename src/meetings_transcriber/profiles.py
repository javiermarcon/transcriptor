from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .models import ProfilePaths, RunPaths

PROFILE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
DEFAULT_INITIAL_PROMPT = "Conversación informal de trabajo en español rioplatense de Argentina.\n"
DEFAULT_HOTWORDS = """\
# Una palabra o frase técnica por línea.
# Ejemplo: Shipii
"""


def validate_profile_name(name: str) -> str:
    if name in {".", ".."} or not PROFILE_RE.fullmatch(name):
        raise ValueError("Nombre de perfil inválido. Usá letras, números, punto, guion o guion bajo.")
    return name


def ensure_profile(base_dir: Path, name: str) -> ProfilePaths:
    validate_profile_name(name)
    directory = base_dir / name
    directory.mkdir(parents=True, exist_ok=True)
    initial_prompt = directory / "initial_prompt.txt"
    hotwords = directory / "hotwords.txt"
    if not initial_prompt.exists():
        initial_prompt.write_text(DEFAULT_INITIAL_PROMPT, encoding="utf-8")
    if not hotwords.exists():
        hotwords.write_text(DEFAULT_HOTWORDS, encoding="utf-8")
    return ProfilePaths(name, directory, initial_prompt, hotwords)


def run_paths_for_directory(directory: Path) -> RunPaths:
    return RunPaths(
        directory=directory,
        system_audio=directory / "sistema.wav",
        microphone_audio=directory / "microfono.wav",
        mixed_audio=directory / "reunion_mezclada.wav",
        json_result=directory / "reunion_mezclada.json",
        plain_transcript=directory / "transcripcion.txt",
        speaker_transcript=directory / "transcripcion_speakers.txt",
    )


def create_run_paths(profile: ProfilePaths, now: datetime | None = None) -> RunPaths:
    now = now or datetime.now()
    directory = profile.directory / f"Reunion_{now:%Y-%m-%d_%H-%M-%S}"
    directory.mkdir(parents=True, exist_ok=False)
    return run_paths_for_directory(directory)


def resolve_meeting_directory(meeting: Path, profile: ProfilePaths) -> Path:
    expanded = meeting.expanduser()
    candidates: list[Path] = []
    if expanded.is_absolute():
        candidates.append(expanded)
    else:
        candidates.append(Path.cwd() / expanded)
        candidates.append(profile.directory / expanded)
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir():
            return resolved
    tried = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(
        f"Carpeta de reunión inexistente o no es un directorio: {meeting}. "
        f"Rutas probadas: {tried}"
    )


def load_existing_run_paths(meeting: Path, profile: ProfilePaths) -> RunPaths:
    directory = resolve_meeting_directory(meeting, profile)
    paths = run_paths_for_directory(directory)
    mixed = paths.mixed_audio
    if not mixed.is_file() or mixed.stat().st_size <= 0:
        raise FileNotFoundError(
            f"No se encontró {mixed.name} válido en {directory}. "
            "La carpeta debe contener el WAV mezclado de la grabación."
        )
    return paths


def read_initial_prompt(path: Path, max_chars: int = 180) -> str:
    text = " ".join(path.read_text(encoding="utf-8").split())
    if len(text) > max_chars:
        raise ValueError(
            f"{path} tiene {len(text)} caracteres; el máximo es {max_chars}. "
            "Usá hotwords.txt para nombres y vocabulario."
        )
    return text


def read_hotwords(path: Path) -> str:
    values: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        values.append(line)
    return ", ".join(dict.fromkeys(values))
