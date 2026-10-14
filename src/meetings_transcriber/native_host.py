from __future__ import annotations

import json
import logging
import struct
import sys
from typing import Any, BinaryIO

from .cli import load_env_file
from .native_controller import NativeHostController
from .native_protocol import MAX_MESSAGE_BYTES, error_response

LOG = logging.getLogger("meetings_transcriber.native_host")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def read_message(stdin: BinaryIO) -> dict[str, Any] | None:
    raw_len = stdin.read(4)
    if not raw_len:
        return None
    if len(raw_len) < 4:
        raise ValueError("Encabezado de Native Messaging incompleto")
    (length,) = struct.unpack("<I", raw_len)
    if length <= 0 or length > MAX_MESSAGE_BYTES:
        raise ValueError(f"Tamaño de mensaje inválido: {length}")
    payload = stdin.read(length)
    if len(payload) < length:
        raise ValueError("Mensaje Native Messaging truncado")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Mensaje Native Messaging no es UTF-8") from exc
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("El mensaje JSON debe ser un objeto")
    return data


def write_message(stdout: BinaryIO, message: dict[str, Any]) -> None:
    encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ValueError("Respuesta demasiado grande para Native Messaging")
    stdout.write(struct.pack("<I", len(encoded)))
    stdout.write(encoded)
    stdout.flush()


def serve(
    controller: NativeHostController,
    *,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> int:
    input_stream = stdin or sys.stdin.buffer
    output_stream = stdout or sys.stdout.buffer
    try:
        while True:
            try:
                message = read_message(input_stream)
            except ValueError as exc:
                LOG.error("Mensaje inválido: %s", exc)
                write_message(
                    output_stream,
                    error_response("", "INVALID_REQUEST", str(exc)),
                )
                continue
            if message is None:
                LOG.info("stdin cerrado; finalizando host Native Messaging")
                break
            response = controller.handle(message)
            write_message(output_stream, response)
    finally:
        controller.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    _ = argv  # Firefox no pasa argumentos útiles al host.
    configure_logging()
    from pathlib import Path

    load_env_file(Path.home() / ".config/meetings-transcriptor.env")
    controller = NativeHostController()
    try:
        return serve(controller)
    except BrokenPipeError:
        LOG.warning("Pipe roto con Firefox; cerrando sesión activa si existe")
        controller.shutdown()
        return 0
    except Exception:
        LOG.exception("Error fatal en el host Native Messaging")
        controller.shutdown()
        return 1


if __name__ == "__main__":
    sys.exit(main())
