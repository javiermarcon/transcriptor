#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
    printf 'No se encontró Python del entorno virtual: %s\n' "$PYTHON_BIN" >&2
    printf 'Creá .venv e instalá el proyecto con: pip install -e .\n' >&2
    exit 1
fi

exec "$PYTHON_BIN" -m meetings_transcriber.cli "$@"
