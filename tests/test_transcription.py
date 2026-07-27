from meetings_transcriber.config import Settings
from meetings_transcriber.models import ProfilePaths, RunPaths
from meetings_transcriber.transcription import build_whisperx_command


def make_settings(tmp_path):
    executable = tmp_path / "whisperx"
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)
    return Settings(
        base_dir=tmp_path,
        whisperx_bin=executable,
        whisper_ctranslate2_bin=None,
        hf_token="secret",
        model="large-v3",
        batch_size=2,
        threads=4,
        device="cpu",
        compute_type="int8",
        volume_system=0.7,
        volume_microphone=2.0,
        vad_method="pyannote",
        vad_onset=0.5,
        vad_offset=0.363,
        chunk_size=30,
        sink=None,
        microphone=None,
    )


def test_command_uses_short_prompt_and_hotwords(tmp_path):
    prompt = tmp_path / "initial_prompt.txt"
    prompt.write_text("Conversación en español rioplatense de Argentina.", encoding="utf-8")
    hotwords = tmp_path / "hotwords.txt"
    hotwords.write_text("Shipii\nFulfillment\nTienda Nube\n", encoding="utf-8")
    profile = ProfilePaths("Shipii", tmp_path, prompt, hotwords)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    paths = RunPaths(
        run_dir,
        run_dir / "sistema.wav",
        run_dir / "microfono.wav",
        run_dir / "reunion_mezclada.wav",
        run_dir / "reunion_mezclada.json",
        run_dir / "transcripcion.txt",
        run_dir / "transcripcion_speakers.txt",
    )
    command = build_whisperx_command(make_settings(tmp_path), profile, paths)
    assert command[command.index("--initial_prompt") + 1] == "Conversación en español rioplatense de Argentina."
    assert command[command.index("--hotwords") + 1] == "Shipii, Fulfillment, Tienda Nube"
    assert command[command.index("--condition_on_previous_text") + 1] == "False"
    assert command[command.index("--print_progress") + 1] == "True"
