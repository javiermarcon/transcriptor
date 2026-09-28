
from pathlib import Path

from meetings_transcriber.config import (
    _existing_executable,
    detect_cuda_available,
    load_settings,
    resolve_device_and_compute_type,
)


def test_existing_executable_none_when_missing():
    assert _existing_executable(None) is None
    assert _existing_executable("") is None


def test_existing_executable_none_when_not_executable(tmp_path):
    executable = tmp_path / "whisperx"
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o644)
    assert _existing_executable(str(executable)) is None


def test_existing_executable_none_when_path_does_not_exist(tmp_path):
    assert _existing_executable(str(tmp_path / "missing")) is None


def test_existing_executable_returns_executable_path(tmp_path):
    executable = tmp_path / "whisperx"
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)
    assert _existing_executable(str(executable)) == executable


def test_resolve_device_auto_uses_cuda_when_available():
    device, compute = resolve_device_and_compute_type("auto", None, cuda_available=lambda: True)
    assert device == "cuda"
    assert compute == "float16"


def test_resolve_device_auto_uses_cpu_when_cuda_unavailable():
    device, compute = resolve_device_and_compute_type("auto", None, cuda_available=lambda: False)
    assert device == "cpu"
    assert compute == "int8"


def test_resolve_device_respects_explicit_compute_type():
    device, compute = resolve_device_and_compute_type("auto", "int8", cuda_available=lambda: True)
    assert device == "cuda"
    assert compute == "int8"


def test_resolve_device_explicit_cpu_and_cuda():
    assert resolve_device_and_compute_type("cpu", None, cuda_available=lambda: True) == ("cpu", "int8")
    assert resolve_device_and_compute_type("cuda", None, cuda_available=lambda: False) == ("cuda", "float16")


def test_resolve_device_rejects_invalid_device():
    import pytest

    with pytest.raises(ValueError, match="DEVICE inválido"):
        resolve_device_and_compute_type("metal", None, cuda_available=lambda: False)


def test_load_settings_reads_environment(tmp_path, monkeypatch):
    executable = tmp_path / "whisperx"
    executable.write_text("", encoding="utf-8")
    executable.chmod(0o755)

    monkeypatch.setenv("WHISPERX_BIN", str(executable))
    monkeypatch.delenv("WHISPER_CTRANSLATE2_BIN", raising=False)
    monkeypatch.setenv("BASE_DIR", str(tmp_path / "textos"))
    monkeypatch.setenv("HF_TOKEN", "secret-token")
    monkeypatch.setenv("MODELO", "medium")
    monkeypatch.setenv("BATCH_SIZE", "7")
    monkeypatch.setenv("THREADS", "8")
    monkeypatch.setenv("DEVICE", "cuda")
    monkeypatch.setenv("COMPUTE_TYPE", "float16")
    monkeypatch.setenv("VOLUMEN_SISTEMA", "0.90")
    monkeypatch.setenv("VOLUMEN_MICROFONO", "1.20")
    monkeypatch.setenv("VAD_METHOD", "energy")
    monkeypatch.setenv("VAD_ONSET", "0.25")
    monkeypatch.setenv("VAD_OFFSET", "0.40")
    monkeypatch.setenv("CHUNK_SIZE", "45")
    monkeypatch.setenv("SINK", "monitor")
    monkeypatch.setenv("MIC", "source")
    monkeypatch.setenv("RECORD_VIDEO", "false")
    monkeypatch.setenv("VIDEO_MONITOR", "DP-1")
    monkeypatch.setenv("VIDEO_FPS", "12")

    settings = load_settings(tmp_path)

    assert settings.whisperx_bin == executable
    assert settings.whisper_ctranslate2_bin is None
    assert settings.hf_token == "secret-token"
    assert settings.model == "medium"
    assert settings.batch_size == 7
    assert settings.threads == 8
    assert settings.device == "cuda"
    assert settings.compute_type == "float16"
    assert settings.volume_system == 0.9
    assert settings.volume_microphone == 1.2
    assert settings.vad_method == "energy"
    assert settings.vad_onset == 0.25
    assert settings.vad_offset == 0.4
    assert settings.chunk_size == 45
    assert settings.sink == "monitor"
    assert settings.microphone == "source"
    assert settings.record_video is False
    assert settings.video_monitor == "DP-1"
    assert settings.video_fps == 12
    assert settings.base_dir == (tmp_path / "textos").expanduser()


def test_load_settings_defaults_to_auto_device(tmp_path, monkeypatch):
    monkeypatch.delenv("DEVICE", raising=False)
    monkeypatch.delenv("COMPUTE_TYPE", raising=False)
    monkeypatch.delenv("WHISPERX_BIN", raising=False)
    monkeypatch.delenv("WHISPER_CTRANSLATE2_BIN", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("BASE_DIR", raising=False)
    monkeypatch.delenv("SINK", raising=False)
    monkeypatch.delenv("MIC", raising=False)

    settings = load_settings(tmp_path, cuda_available=lambda: False)

    assert settings.device == "cpu"
    assert settings.compute_type == "int8"
    assert settings.record_video is True
    assert settings.video_monitor == "primary"
    assert settings.video_fps == 10


def test_load_settings_rejects_non_positive_video_fps(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setenv("VIDEO_FPS", "0")
    with pytest.raises(ValueError, match="VIDEO_FPS debe ser mayor que cero"):
        load_settings(tmp_path, cuda_available=lambda: False)


def test_load_settings_auto_selects_cuda(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE", "auto")
    monkeypatch.delenv("COMPUTE_TYPE", raising=False)

    settings = load_settings(tmp_path, cuda_available=lambda: True)

    assert settings.device == "cuda"
    assert settings.compute_type == "float16"


def test_load_settings_reads_quality_knobs(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE", "cuda")
    monkeypatch.setenv("COMPUTE_TYPE", "float16")
    monkeypatch.setenv("TEMPERATURE", "0")
    monkeypatch.setenv("BEST_OF", "5")
    monkeypatch.setenv("BEAM_SIZE", "8")
    monkeypatch.setenv("PATIENCE", "1.2")
    monkeypatch.setenv("LENGTH_PENALTY", "1.0")
    monkeypatch.setenv("SUPPRESS_TOKENS", "-1")
    monkeypatch.setenv("SUPPRESS_NUMERALS", "1")
    monkeypatch.setenv("TEMPERATURE_INCREMENT_ON_FALLBACK", "0.2")
    monkeypatch.setenv("COMPRESSION_RATIO_THRESHOLD", "2.2")
    monkeypatch.setenv("LOGPROB_THRESHOLD", "-0.8")
    monkeypatch.setenv("NO_SPEECH_THRESHOLD", "0.7")
    monkeypatch.setenv("MIN_SPEAKERS", "2")
    monkeypatch.setenv("MAX_SPEAKERS", "5")
    monkeypatch.setenv("CONDITION_ON_PREVIOUS_TEXT", "false")
    monkeypatch.setenv("FILTER_HALLUCINATIONS", "1")
    monkeypatch.setenv(
        "EXTRA_HALLUCINATION_PHRASES",
        "frase inventada, otra basura",
    )

    settings = load_settings(tmp_path, cuda_available=lambda: True)

    assert settings.beam_size == 8
    assert settings.patience == 1.2
    assert settings.length_penalty == 1.0
    assert settings.suppress_numerals is True
    assert settings.no_speech_threshold == 0.7
    assert settings.logprob_threshold == -0.8
    assert settings.compression_ratio_threshold == 2.2
    assert settings.min_speakers == 2
    assert settings.max_speakers == 5
    assert settings.condition_on_previous_text is False
    assert settings.filter_hallucinations is True
    assert settings.extra_hallucination_phrases == ("frase inventada", "otra basura")


def test_parse_phrase_list_splits_commas_and_strips():
    from meetings_transcriber.config import parse_phrase_list

    assert parse_phrase_list("  a, b ,,c  ") == ("a", "b", "c")
    assert parse_phrase_list(None) == ()
    assert parse_phrase_list("") == ()


def test_hallucination_phrases_for_merges_defaults_and_extras():
    from meetings_transcriber.config import Settings, hallucination_phrases_for

    settings = Settings(
        base_dir=Path("/tmp"),
        whisperx_bin=None,
        whisper_ctranslate2_bin=None,
        hf_token=None,
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
        filter_hallucinations=True,
        extra_hallucination_phrases=("frase inventada", "gracias por ver el video"),
    )
    phrases = hallucination_phrases_for(settings, ("gracias por ver el video", "otra"))
    assert phrases == ("gracias por ver el video", "otra", "frase inventada")


def test_hallucination_phrases_for_empty_when_filter_disabled():
    from meetings_transcriber.config import Settings, hallucination_phrases_for

    settings = Settings(
        base_dir=Path("/tmp"),
        whisperx_bin=None,
        whisper_ctranslate2_bin=None,
        hf_token=None,
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
        filter_hallucinations=False,
        extra_hallucination_phrases=("frase inventada",),
    )
    assert hallucination_phrases_for(settings, ("gracias por ver el video",)) == ()


def test_detect_cuda_available_false_when_torch_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise ImportError("no torch")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert detect_cuda_available() is False


def test_detect_cuda_available_uses_torch(monkeypatch):
    import sys
    import types

    fake_torch = types.ModuleType("torch")
    fake_cuda = types.SimpleNamespace(is_available=lambda: True)
    fake_torch.cuda = fake_cuda
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    assert detect_cuda_available() is True


def test_detect_cuda_available_false_when_torch_raises(monkeypatch):
    import sys
    import types

    def boom():
        raise RuntimeError("cuda init failed")

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=boom)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    assert detect_cuda_available() is False
