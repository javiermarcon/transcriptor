from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .audio import ffprobe_duration
from .config import Settings, hallucination_phrases_for
from .models import ProfilePaths, RunPaths
from .postprocess import DEFAULT_HALLUCINATION_PHRASES, process_whisperx_json
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
    phrases = hallucination_phrases_for(settings, DEFAULT_HALLUCINATION_PHRASES)
    process_whisperx_json(
        generated,
        paths.plain_transcript,
        paths.speaker_transcript,
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
