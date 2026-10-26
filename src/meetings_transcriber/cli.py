from __future__ import annotations

import argparse
import os
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from subprocess import CalledProcessError

from .audio import record_meeting
from .config import load_settings
from .profiles import create_run_paths, ensure_profile, list_meetings, load_existing_run_paths
from .transcription import import_existing_audio, transcribe_whisperx
from .visual_evidence import (
    extract_visual_evidence,
    load_visual_evidence_settings_from_env,
    set_review_status,
)


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
    parser.add_argument(
        "--audio",
        "-a",
        type=Path,
        nargs="+",
        action="append",
        help="Procesar uno o más audios existentes",
    )
    parser.add_argument(
        "--meeting",
        type=Path,
        help="Transcribir una reunión ya grabada usando los audios de esa carpeta",
    )
    parser.add_argument("--list-profiles", action="store_true")
    parser.add_argument(
        "--list-meetings",
        action="store_true",
        help="Listar reuniones del perfil indicando si tienen transcripción",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".config/meetings-transcriptor.env",
    )
    parser.add_argument(
        "--extract-visual-evidence",
        action="store_true",
        help=(
            "Extrae fotogramas para frases con referencias espaciales "
            "(requiere --meeting con video y transcripción)"
        ),
    )
    parser.add_argument(
        "--review-visual-evidence",
        nargs=2,
        metavar=("CANDIDATE_ID", "STATUS"),
        help=(
            "Marca revisión de un candidato: useful|insufficient|incorrect|pending "
            "(requiere --meeting)"
        ),
    )
    parser.add_argument(
        "--review-note",
        default=None,
        help="Nota opcional al usar --review-visual-evidence",
    )
    return parser


def format_meeting_status_line(name: str, has_transcription: bool) -> str:
    status = "con transcripción" if has_transcription else "sin transcripción"
    return f"{name}\t{status}"


def ask_transcribe_now(
    reader: Callable[[str], str] | None = None,
    is_interactive: Callable[[], bool] | None = None,
) -> bool:
    if is_interactive is None:
        is_interactive = sys.stdin.isatty
    if not is_interactive():
        print("Entrada no interactiva: se transcribe automáticamente.")
        return True
    if reader is None:
        reader = input
    while True:
        try:
            answer = reader("¿Transcribir ahora? [S/n] ").strip().lower()
        except EOFError:
            return False
        if answer in {"", "s", "si", "sí", "y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Respondé s para transcribir o n para terminar.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
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

        audio_sources = [audio for group in args.audio for audio in group] if args.audio else []
        if args.meeting is not None and audio_sources:
            parser.error("--audio y --meeting son mutuamente excluyentes")
        if args.list_meetings and (args.meeting is not None or audio_sources):
            parser.error("--list-meetings no se combina con --audio ni --meeting")
        if args.extract_visual_evidence and args.meeting is None:
            parser.error("--extract-visual-evidence requiere --meeting")
        if args.review_visual_evidence is not None and args.meeting is None:
            parser.error("--review-visual-evidence requiere --meeting")
        if args.extract_visual_evidence and args.review_visual_evidence is not None:
            parser.error(
                "--extract-visual-evidence y --review-visual-evidence son mutuamente excluyentes"
            )
        if (
            (args.extract_visual_evidence or args.review_visual_evidence is not None)
            and audio_sources
        ):
            parser.error("La evidencia visual no se combina con --audio")

        profile = ensure_profile(settings.base_dir, args.profile)
        if args.list_meetings:
            meetings = list_meetings(profile)
            if not meetings:
                print(f"No hay reuniones en el perfil {profile.name}.")
                return 0
            for meeting in meetings:
                print(format_meeting_status_line(meeting.name, meeting.has_transcription))
            return 0

        if args.meeting is not None:
            paths = load_existing_run_paths(args.meeting, profile)
        else:
            paths = create_run_paths(profile)
        print(f"Perfil: {profile.name}")
        print(f"Directorio: {paths.directory}")

        if args.review_visual_evidence is not None:
            candidate_id, status = args.review_visual_evidence
            index = set_review_status(
                paths,
                candidate_id,
                status,
                note=args.review_note,
            )
            print(f"Revisión actualizada: {candidate_id} → {status}")
            print(f"Índice: {paths.visual_evidence_index}")
            pending = sum(
                1
                for item in index.get("candidates", [])
                if isinstance(item, dict)
                and (item.get("review") or {}).get("status") == "pending"
            )
            print(f"Candidatos pendientes: {pending}")
            return 0

        if args.extract_visual_evidence:
            ve_settings = load_visual_evidence_settings_from_env()
            index = extract_visual_evidence(paths, settings=ve_settings)
            print(f"Candidatos: {len(index.get('candidates', []))}")
            print(f"Índice: {paths.visual_evidence_index}")
            print(f"Frames: {paths.visual_evidence_dir / 'frames'}")
            sync = index.get("sync") or {}
            if sync.get("video_minus_audio_s") is not None:
                print(
                    f"Desfase video-audio (ffprobe): {sync['video_minus_audio_s']} s "
                    "(ver sync en el índice; no implica conocer el UI señalado)"
                )
            return 0

        print(f"Dispositivo: {settings.device} ({settings.compute_type})")
        print(f"Prompt breve: {profile.initial_prompt}")
        print(f"Hotwords: {profile.hotwords}")

        if audio_sources:
            import_existing_audio(audio_sources, paths)
        elif args.meeting is None:
            print("Grabando. Presioná Ctrl+C al terminar.")
            code = record_meeting(settings, paths)
            if code == 255:
                print("FFmpeg recibió Ctrl+C y cerró correctamente los archivos de grabación.")
            if not ask_transcribe_now():
                print(f"Grabación guardada en: {paths.directory}")
                print("No se transcribió. Para transcribir más tarde:")
                print(f"  --profile {profile.name} --meeting {paths.directory}")
                return 0

        transcribe_whisperx(settings, profile, paths)
        print(f"Transcripción: {paths.plain_transcript}")
        print(f"Con hablantes: {paths.speaker_transcript}")
        return 0

    except KeyboardInterrupt:
        print("Interrumpido por el usuario.", file=sys.stderr)
        return 130

    except (
        FileNotFoundError,
        ValueError,
        RuntimeError,
        OSError,
        CalledProcessError,
        ImportError,
        TypeError,
        AttributeError,
        KeyError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if os.environ.get("DEBUG", "0") in ("1", "true", "True"):
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
