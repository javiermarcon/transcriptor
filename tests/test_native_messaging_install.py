import json
import os
from pathlib import Path

from meetings_transcriber.native_messaging_install import (
    install,
    uninstall,
    verify,
)
from meetings_transcriber.native_protocol import ALLOWED_EXTENSION_ID, NATIVE_HOST_NAME


def test_install_verify_uninstall_roundtrip(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    venv_python = project / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
    venv_python.chmod(0o755)

    state_dir = tmp_path / "state"
    manifest_dir = tmp_path / "manifests"

    result = install(project=project, state_dir=state_dir, manifest_dir=manifest_dir)
    assert Path(result["wrapper"]).is_file()
    assert os.access(result["wrapper"], os.X_OK)
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["name"] == NATIVE_HOST_NAME
    assert manifest["allowed_extensions"] == [ALLOWED_EXTENSION_ID]
    assert manifest["path"] == result["wrapper"]

    checked = verify(state_dir=state_dir, manifest_dir=manifest_dir)
    assert checked["ok"] is True

    removed = uninstall(state_dir=state_dir, manifest_dir=manifest_dir)
    assert "com.meetings.transcriptor.json" in removed["removed"]
    assert verify(state_dir=state_dir, manifest_dir=manifest_dir)["ok"] is False


def test_verify_detects_wrong_extension(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    python = project / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)
    state_dir = tmp_path / "state"
    manifest_dir = tmp_path / "manifests"
    install(project=project, state_dir=state_dir, manifest_dir=manifest_dir)
    manifest_path = manifest_dir / f"{NATIVE_HOST_NAME}.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["allowed_extensions"] = ["other@example.org"]
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    result = verify(state_dir=state_dir, manifest_dir=manifest_dir)
    assert result["ok"] is False
    assert any("allowed_extensions" in problem for problem in result["problems"])
