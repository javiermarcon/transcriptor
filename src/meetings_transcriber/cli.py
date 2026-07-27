from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .audio import record_meeting
from .config import load_settings
from .profiles import create_run_paths, ensure_profile
from .transcription import import_existing_audio, transcribe_whisperx


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        value = os.path.expandvars(os.path.expanduser(value))
        os.environ.setdefault(key, value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Graba y transcribe reuniones locales usando perfiles.")
    parser.add_argument("--profile", "-p", help="Perfil: Shipii, motonave, etc.")
    parser.add_argument("--audio", "-a", type=Path, help="Procesar un WAV existente")
    parser.add_argument("--list-profiles", action="store_true")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".config/meetings-transcriptor.env",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    load_env_file(args.config)
    project_dir = Path(__file__).resolve().parents[2]
    settings = load_settings(project_dir)

    if args.list_profiles:
        settings.base_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(settings.base_dir.iterdir()):
            if path.is_dir():
                print(path.name)
        return 0

    if not args.profile:
        parser.error("--profile es obligatorio salvo con --list-profiles")

    profile = ensure_profile(settings.base_dir, args.profile)
    paths = create_run_paths(profile)
    print(f"Perfil: {profile.name}")
    print(f"Directorio: {paths.directory}")
    print(f"Prompt breve: {profile.initial_prompt}")
    print(f"Hotwords: {profile.hotwords}")

    if args.audio:
        import_existing_audio(args.audio, paths)
    else:
        print("Grabando. Presioná Ctrl+C al terminar.")
        code = record_meeting(settings, paths)
        if code == 255:
            print("FFmpeg recibió Ctrl+C y cerró correctamente los WAV.")

    transcribe_whisperx(settings, profile, paths)
    print(f"Transcripción: {paths.plain_transcript}")
    print(f"Con hablantes: {paths.speaker_transcript}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
