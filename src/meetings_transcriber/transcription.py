from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .audio import ffprobe_duration
from .config import Settings
from .models import ProfilePaths, RunPaths
from .postprocess import process_whisperx_json
from .profiles import read_hotwords, read_initial_prompt
from .progress import parse_progress


def build_whisperx_command(settings: Settings, profile: ProfilePaths, paths: RunPaths) -> list[str]:
    if settings.whisperx_bin is None:
        raise RuntimeError("WhisperX no está disponible")
    if not settings.hf_token:
        raise RuntimeError("HF_TOKEN no está configurado")

    command = [
        str(settings.whisperx_bin), str(paths.mixed_audio),
        "--model", settings.model,
        "--language", "es",
        "--device", settings.device,
        "--compute_type", settings.compute_type,
        "--batch_size", str(settings.batch_size),
        "--threads", str(settings.threads),
        "--vad_method", settings.vad_method,
        "--vad_onset", str(settings.vad_onset),
        "--vad_offset", str(settings.vad_offset),
        "--chunk_size", str(settings.chunk_size),
        "--condition_on_previous_text", "False",
        "--diarize",
        "--hf_token", settings.hf_token,
        "--print_progress", "True",
        "--output_dir", str(paths.directory),
        "--output_format", "json",
    ]
    initial_prompt = read_initial_prompt(profile.initial_prompt)
    hotwords = read_hotwords(profile.hotwords)
    if initial_prompt:
        command.extend(["--initial_prompt", initial_prompt])
    if hotwords:
        command.extend(["--hotwords", hotwords])
    return command


def run_streaming(command: list[str], total_seconds: float) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    last_progress = ""
    for line in process.stdout:
        print(line, end="")
        progress = parse_progress(line, total_seconds)
        if progress:
            rendered = progress.render()
            if rendered != last_progress:
                print(f"Progreso de audio: {rendered}", flush=True)
                last_progress = rendered
    return_code = process.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)


def find_generated_json(paths: RunPaths) -> Path:
    if paths.json_result.is_file() and paths.json_result.stat().st_size:
        return paths.json_result
    candidates = sorted(paths.directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError("WhisperX terminó sin generar un JSON")
    return candidates[0]


def transcribe_whisperx(settings: Settings, profile: ProfilePaths, paths: RunPaths) -> None:
    duration = ffprobe_duration(paths.mixed_audio)
    run_streaming(build_whisperx_command(settings, profile, paths), duration)
    generated = find_generated_json(paths)
    process_whisperx_json(generated, paths.plain_transcript, paths.speaker_transcript)


def import_existing_audio(source: Path, paths: RunPaths) -> None:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    shutil.copy2(source, paths.mixed_audio)
