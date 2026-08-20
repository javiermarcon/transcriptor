
from meetings_transcriber.config import _existing_executable, load_settings


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
    assert settings.base_dir == (tmp_path / "textos").expanduser()
