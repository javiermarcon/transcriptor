from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from .attribution import write_attributed_transcript
from .audio import ffprobe_duration
from .config import Settings, hallucination_phrases_for
from .models import ProfilePaths, RunPaths
from .postprocess import DEFAULT_HALLUCINATION_PHRASES, process_whisperx_json
from .profiles import read_hotwords, read_initial_prompt
from .progress import Progress, parse_progress

OnProgress = Callable[[Progress], None]

_HF_TOKEN_RE = re.compile(r"hf_[A-Za-z0-9]+")


def redact_secrets(text: str) -> str:
    """Oculta tokens HF y flags --hf_token en mensajes de error."""
    redacted = _HF_TOKEN_RE.sub("hf_***", text)
    return re.sub(
        r"(--hf_token)(\s+)(\S+)",
        r"\1\2***",
        redacted,
    )


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
        "--condition_on_previous_text", "True" if settings.condition_on_previous_text else "False",
        "--temperature", str(settings.temperature),
        "--best_of", str(settings.best_of),
        "--beam_size", str(settings.beam_size),
        "--patience", str(settings.patience),
        "--suppress_tokens", settings.suppress_tokens,
        "--temperature_increment_on_fallback", str(settings.temperature_increment_on_fallback),
        "--compression_ratio_threshold", str(settings.compression_ratio_threshold),
        "--logprob_threshold", str(settings.logprob_threshold),
        "--no_speech_threshold", str(settings.no_speech_threshold),
        "--diarize",
        "--hf_token", settings.hf_token,
        "--print_progress", "True",
        "--output_dir", str(paths.directory),
        "--output_format", "json",
    ]
    if settings.length_penalty is not None:
        command.extend(["--length_penalty", str(settings.length_penalty)])
    if settings.suppress_numerals:
        command.append("--suppress_numerals")
    if settings.min_speakers is not None:
        command.extend(["--min_speakers", str(settings.min_speakers)])
    if settings.max_speakers is not None:
        command.extend(["--max_speakers", str(settings.max_speakers)])

    initial_prompt = read_initial_prompt(profile.initial_prompt)
    hotwords = read_hotwords(profile.hotwords)
    if initial_prompt:
        command.extend(["--initial_prompt", initial_prompt])
    if hotwords:
        command.extend(["--hotwords", hotwords])
    return command


def run_streaming(
    command: list[str],
    total_seconds: float,
    *,
    on_progress: OnProgress | None = None,
    echo_stdout: bool = True,
) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    last_progress = ""
    collected: list[str] = []
    for line in process.stdout:
        collected.append(line)
        if echo_stdout:
            print(line, end="")
        progress = parse_progress(line, total_seconds)
        if progress:
            rendered = progress.render()
            if rendered != last_progress:
                if echo_stdout:
                    print(f"Progreso de audio: {rendered}", flush=True)
                elif on_progress is None:
                    # Host NM: no ensuciar stdout (canal del protocolo).
                    print(f"Progreso de audio: {rendered}", file=sys.stderr, flush=True)
                if on_progress is not None:
                    on_progress(progress)
                last_progress = rendered
    return_code = process.wait()
    if return_code != 0:
        tail = "".join(collected[-40:]).strip() or "(sin salida de WhisperX)"
        detail = redact_secrets(tail)
        raise RuntimeError(f"WhisperX falló (código {return_code}).\n{detail}")


def find_generated_json(paths: RunPaths) -> Path:
    if paths.json_result.is_file() and paths.json_result.stat().st_size:
        return paths.json_result
    candidates = sorted(paths.directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError("WhisperX terminó sin generar un JSON")
    return candidates[0]


def transcribe_whisperx(
    settings: Settings,
    profile: ProfilePaths,
    paths: RunPaths,
    *,
    on_progress: OnProgress | None = None,
    echo_stdout: bool = True,
) -> None:
    duration = ffprobe_duration(paths.mixed_audio)
    run_streaming(
        build_whisperx_command(settings, profile, paths),
        duration,
        on_progress=on_progress,
        echo_stdout=echo_stdout,
    )
    generated = find_generated_json(paths)
    phrases = hallucination_phrases_for(settings, DEFAULT_HALLUCINATION_PHRASES)
    process_whisperx_json(
        generated,
        paths.plain_transcript,
        paths.speaker_transcript,
        hallucination_phrases=phrases,
    )
    write_attributed_transcript(
        generated,
        paths.attributed_transcript,
        paths,
        local_participant_name=settings.local_participant_name,
        hallucination_phrases=phrases,
    )


def import_existing_audio(sources: list[Path], paths: RunPaths) -> None:
    sources = [source.expanduser().resolve() for source in sources]
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(source)

    if len(sources) == 1:
        shutil.copy2(sources[0], paths.mixed_audio)
        return

    inputs: list[str] = []
    filter_parts: list[str] = []
    for index, source in enumerate(sources):
        inputs.extend(["-thread_queue_size", "1024", "-i", str(source)])
        filter_parts.append(
            f"[{index}:a]aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono[a{index}]"
        )
    concat_inputs = "".join(f"[a{index}]" for index in range(len(sources)))
    filter_complex = ";".join(filter_parts) + ";" + f"{concat_inputs}concat=n={len(sources)}:v=0:a=1[out]"

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-c:a",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(paths.mixed_audio),
    ]
    subprocess.run(command, check=True)
