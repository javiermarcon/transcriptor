from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from .native_protocol import ALLOWED_EXTENSION_ID, NATIVE_HOST_NAME

HOST_WRAPPER_NAME = "meetings-transcriptor-native-host"
MANIFEST_FILENAME = f"{NATIVE_HOST_NAME}.json"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_python(project: Path) -> Path:
    env_override = os.environ.get("NATIVE_HOST_PYTHON", "").strip()
    if env_override:
        candidate = Path(env_override).expanduser()
        # absolute() no sigue symlinks: hay que conservar .venv/bin/python.
        candidate = candidate.absolute()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
        raise FileNotFoundError(
            f"NATIVE_HOST_PYTHON no es un ejecutable válido: {candidate}"
        )

    venv_python = (project / ".venv" / "bin" / "python").absolute()
    if venv_python.is_file() and os.access(venv_python, os.X_OK):
        # No usar resolve(): en venvs el binario es symlink a /usr/bin/pythonX
        # y resolve() saltaría el site-packages del entorno virtual.
        return venv_python

    current = Path(sys.executable).absolute()
    if current.is_file() and os.access(current, os.X_OK):
        return current
    raise FileNotFoundError(
        "No se encontró un intérprete Python usable. "
        "Creá .venv en el proyecto o definí NATIVE_HOST_PYTHON."
    )


def default_state_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return Path(xdg).expanduser() / "meetings-transcriptor"
    return Path.home() / ".local" / "share" / "meetings-transcriptor"


def default_manifest_dir() -> Path:
    return Path.home() / ".mozilla" / "native-messaging-hosts"


def wrapper_path(state_dir: Path) -> Path:
    return state_dir / HOST_WRAPPER_NAME


def manifest_path(manifest_dir: Path) -> Path:
    return manifest_dir / MANIFEST_FILENAME


def write_wrapper(path: Path, python: Path, project: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    venv_dir = project / ".venv"
    content = (
        "#!/bin/sh\n"
        "set -eu\n"
        f'export VIRTUAL_ENV="{venv_dir}"\n'
        f'export PYTHONPATH="{project / "src"}:${{PYTHONPATH:-}}"\n'
        f'exec "{python}" -m meetings_transcriber.native_host "$@"\n'
    )
    path.write_text(content, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_manifest(host_path: Path) -> dict[str, object]:
    return {
        "name": NATIVE_HOST_NAME,
        "description": "Host local del transcriptor de reuniones para Firefox",
        "path": str(host_path.resolve()),
        "type": "stdio",
        "allowed_extensions": [ALLOWED_EXTENSION_ID],
    }


def write_manifest(path: Path, host_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_manifest(host_path), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def install(
    *,
    project: Path | None = None,
    state_dir: Path | None = None,
    manifest_dir: Path | None = None,
) -> dict[str, str]:
    root = (project or project_root()).resolve()
    python = resolve_python(root)
    state = (state_dir or default_state_dir()).resolve()
    manifests = (manifest_dir or default_manifest_dir()).resolve()
    host = wrapper_path(state)
    manifest = manifest_path(manifests)

    write_wrapper(host, python, root)
    write_manifest(manifest, host)
    return {
        "project": str(root),
        "python": str(python),
        "wrapper": str(host),
        "manifest": str(manifest),
        "extension_id": ALLOWED_EXTENSION_ID,
        "host_name": NATIVE_HOST_NAME,
    }


def uninstall(
    *,
    state_dir: Path | None = None,
    manifest_dir: Path | None = None,
) -> dict[str, str]:
    state = (state_dir or default_state_dir()).resolve()
    manifests = (manifest_dir or default_manifest_dir()).resolve()
    host = wrapper_path(state)
    manifest = manifest_path(manifests)
    removed: list[str] = []
    for path in (manifest, host):
        if path.is_file():
            path.unlink()
            removed.append(str(path))
    return {
        "removed": ", ".join(removed) if removed else "(nada que borrar)",
        "note": "No se borraron grabaciones ni ~/.config/meetings-transcriptor.env",
    }


def verify(
    *,
    state_dir: Path | None = None,
    manifest_dir: Path | None = None,
) -> dict[str, object]:
    state = (state_dir or default_state_dir()).resolve()
    manifests = (manifest_dir or default_manifest_dir()).resolve()
    host = wrapper_path(state)
    manifest = manifest_path(manifests)
    problems: list[str] = []

    if not host.is_file():
        problems.append(f"Falta el wrapper del host: {host}")
    elif not os.access(host, os.X_OK):
        problems.append(f"El wrapper no es ejecutable: {host}")

    if not manifest.is_file():
        problems.append(f"Falta el manifiesto: {manifest}")
        data: dict[str, object] | None = None
    else:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("name") != NATIVE_HOST_NAME:
            problems.append("name del manifiesto incorrecto")
        if data.get("type") != "stdio":
            problems.append("type del manifiesto debe ser stdio")
        allowed = data.get("allowed_extensions")
        if allowed != [ALLOWED_EXTENSION_ID]:
            problems.append(
                f"allowed_extensions debe ser exactamente [{ALLOWED_EXTENSION_ID!r}]"
            )
        path_value = data.get("path")
        if path_value != str(host):
            problems.append(
                f"path del manifiesto ({path_value!r}) no coincide con el wrapper ({host})"
            )

    return {
        "ok": not problems,
        "wrapper": str(host),
        "manifest": str(manifest),
        "problems": problems,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Instala, verifica o desinstala el registro Native Messaging de Firefox "
            f"para {NATIVE_HOST_NAME}."
        )
    )
    parser.add_argument(
        "command",
        choices=("install", "uninstall", "verify"),
        help="Acción a realizar",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Directorio para el wrapper del host (default: XDG_DATA_HOME/meetings-transcriptor)",
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=None,
        help="Directorio de manifiestos Firefox (default: ~/.mozilla/native-messaging-hosts)",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Raíz del proyecto transcriptor (default: detectada)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            installed = install(
                project=args.project_dir,
                state_dir=args.state_dir,
                manifest_dir=args.manifest_dir,
            )
            print("Host Native Messaging instalado.")
            for key, value in installed.items():
                print(f"  {key}: {value}")
            print()
            print("No se modificó el perfil de Firefox más allá del manifiesto nativo.")
            print("Recargá la extensión temporal o reiniciá Firefox para detectarlo.")
            return 0
        if args.command == "uninstall":
            removed = uninstall(state_dir=args.state_dir, manifest_dir=args.manifest_dir)
            print("Registro Native Messaging eliminado.")
            for key, value in removed.items():
                print(f"  {key}: {value}")
            return 0
        checked = verify(state_dir=args.state_dir, manifest_dir=args.manifest_dir)
        if checked["ok"]:
            print("Verificación OK.")
            print(f"  wrapper: {checked['wrapper']}")
            print(f"  manifest: {checked['manifest']}")
            return 0
        print("Verificación FALLIDA.", file=sys.stderr)
        problems = checked["problems"]
        assert isinstance(problems, list)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    except (OSError, ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
