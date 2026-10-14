#!/usr/bin/env bash
# Gestiona el registro Firefox Native Messaging del host com.meetings.transcriptor.
# No se ejecuta solo: hay que invocarlo explícitamente (install|uninstall|verify).
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${NATIVE_HOST_PYTHON:-$PROJECT_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "${PYTHON_BIN}" || ! -x "$PYTHON_BIN" ]]; then
    printf 'No se encontró un intérprete Python ejecutable.\n' >&2
    exit 1
fi

export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" -m meetings_transcriber.native_messaging_install "$@"
