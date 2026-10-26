from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from meetings_transcriber.profiles import run_paths_for_directory
from meetings_transcriber.visual_evidence import (
    VisualEvidenceSettings,
    detect_candidates,
    extract_visual_evidence,
    plan_frame_timestamps,
    set_review_status,
)


def _write_meeting(
    directory: Path,
    *,
    segments: list[dict],
    with_video: bool = True,
    video_bytes: bytes = b"fake-mp4",
    attributed: bool = True,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    paths = run_paths_for_directory(directory)
    if attributed:
        paths.attributed_transcript.write_text(
            json.dumps({"schema_version": 1, "segments": segments}),
            encoding="utf-8",
        )
    else:
        paths.json_result.write_text(
            json.dumps(
                {
                    "segments": [
                        {
                            "start": s["start"],
                            "end": s["end"],
                            "text": s["text"],
                            "speaker": s.get("speaker_id", "SPEAKER_00"),
                        }
                        for s in segments
                    ]
                }
            ),
            encoding="utf-8",
        )
    paths.mixed_audio.write_bytes(b"RIFF....")
    if with_video:
        paths.video.write_bytes(video_bytes)
    (directory / "session.json").write_text(
        json.dumps({"session_id": "sess-test-ve", "recording_started_at_epoch_ms": 0}),
        encoding="utf-8",
    )
    return directory


def _ffprobe_runner_factory(video_duration: float = 30.0, audio_duration: float = 29.5):
    def runner(command, check=False, text=True, capture_output=True):
        cmd = list(command)
        if cmd and cmd[0] == "ffprobe":
            if "json" in cmd:
                # Probe de streams del MP4 (video + audio embebido).
                payload = {
                    "streams": [
                        {"codec_type": "video", "duration": str(video_duration)},
                        {
                            "codec_type": "audio",
                            "duration": str(max(0.0, video_duration - 0.5)),
                        },
                    ]
                }
                return Mock(returncode=0, stdout=json.dumps(payload), stderr="")
            target = cmd[-1]
            duration = video_duration if str(target).endswith(".mp4") else audio_duration
            return Mock(returncode=0, stdout=f"{duration}\n", stderr="")
        if cmd and cmd[0] == "ffmpeg":
            # Debe mapear solo video e ignorar audio del contenedor.
            assert "-map" in cmd and "0:v:0" in cmd and "-an" in cmd
            out = Path(cmd[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"\xff\xd8\xfffakejpeg")
            return Mock(returncode=0, stdout="", stderr="")
        return Mock(returncode=1, stdout="", stderr="unexpected")

    return runner


def test_plan_frame_timestamps_caps_and_dedups():
    stamps = plan_frame_timestamps(
        10.0,
        14.0,
        phrase_start=11.0,
        phrase_end=12.0,
        interval_s=1.0,
        max_frames=3,
    )
    assert len(stamps) <= 3
    assert stamps[0] == 10.0
    assert stamps[-1] == 14.0


def test_detect_candidates_keeps_reasons_and_speaker():
    segments = [
        {
            "start": 5.0,
            "end": 7.0,
            "text": "Fijate acá en este botón.",
            "speaker_id": "SPEAKER_00",
            "attributed_name": "Javier",
        },
        {
            "start": 8.0,
            "end": 9.0,
            "text": "Seguimos con otra cosa.",
            "speaker_id": "SPEAKER_01",
            "attributed_name": None,
        },
    ]
    settings = VisualEvidenceSettings(context_before_s=1.0, context_after_s=2.0)
    candidates = detect_candidates(segments, settings=settings)
    assert len(candidates) == 1
    assert candidates[0]["attributed_name"] == "Javier"
    assert candidates[0]["window_start"] == 4.0
    assert candidates[0]["window_end"] == 9.0
    assert any(r.startswith("pattern:") for r in candidates[0]["selection_reasons"])


def test_extract_visual_evidence_writes_index_and_frames(tmp_path):
    meeting = _write_meeting(
        tmp_path / "Reunion_test",
        segments=[
            {
                "start": 10.0,
                "end": 12.0,
                "text": "Mirá lo que pasa acá.",
                "speaker_id": "SPEAKER_00",
                "attributed_name": "Javier",
            }
        ],
    )
    paths = run_paths_for_directory(meeting)
    index = extract_visual_evidence(
        paths,
        settings=VisualEvidenceSettings(
            context_before_s=1.0,
            context_after_s=1.0,
            frame_interval_s=1.0,
            max_frames_per_candidate=3,
        ),
        runner=_ffprobe_runner_factory(30.0, 29.4),
    )
    assert paths.visual_evidence_index.is_file()
    assert index["session_id"] == "sess-test-ve"
    assert index["sync"]["video_minus_audio_s"] == pytest.approx(0.6)
    assert len(index["candidates"]) == 1
    cand = index["candidates"][0]
    assert cand["text"].startswith("Mirá")
    assert cand["review"]["status"] == "pending"
    assert cand["frames"]
    assert all(Path(meeting, f["path"]).is_file() for f in cand["frames"] if f["status"] != "error")
    # No modifica originales.
    assert paths.video.read_bytes() == b"fake-mp4"
    assert paths.attributed_transcript.is_file()


def test_missing_video_raises(tmp_path):
    meeting = _write_meeting(
        tmp_path / "Reunion_novideo",
        segments=[
            {
                "start": 1.0,
                "end": 2.0,
                "text": "Fijate acá.",
                "speaker_id": "SPEAKER_00",
            }
        ],
        with_video=False,
    )
    paths = run_paths_for_directory(meeting)
    with pytest.raises(FileNotFoundError, match="Video ausente"):
        extract_visual_evidence(paths, runner=_ffprobe_runner_factory())


def test_segment_outside_video_range_records_error(tmp_path):
    meeting = _write_meeting(
        tmp_path / "Reunion_oor",
        segments=[
            {
                "start": 50.0,
                "end": 52.0,
                "text": "Fijate acá después del corte.",
                "speaker_id": "SPEAKER_00",
            }
        ],
    )
    paths = run_paths_for_directory(meeting)
    index = extract_visual_evidence(
        paths,
        settings=VisualEvidenceSettings(context_before_s=0.5, context_after_s=0.5),
        runner=_ffprobe_runner_factory(video_duration=20.0),
    )
    cand = index["candidates"][0]
    assert cand["frames"] == []
    assert any("fuera de rango" in err for err in cand["errors"])


def test_duplicate_frame_timestamps_are_reused(tmp_path):
    # Misma ventana temporal → mismos timestamps cuantizados → reuse.
    meeting = _write_meeting(
        tmp_path / "Reunion_dup",
        segments=[
            {
                "start": 10.0,
                "end": 11.0,
                "text": "Fijate acá.",
                "speaker_id": "SPEAKER_00",
            },
            {
                "start": 10.0,
                "end": 11.0,
                "text": "Mirá acá también.",
                "speaker_id": "SPEAKER_00",
            },
        ],
    )
    paths = run_paths_for_directory(meeting)
    index = extract_visual_evidence(
        paths,
        settings=VisualEvidenceSettings(
            context_before_s=0.0,
            context_after_s=0.0,
            frame_interval_s=5.0,
            max_frames_per_candidate=2,
        ),
        runner=_ffprobe_runner_factory(30.0),
    )
    statuses = [
        frame["status"]
        for cand in index["candidates"]
        for frame in cand["frames"]
    ]
    assert "ok" in statuses
    assert "reused" in statuses


def test_ffmpeg_failure_records_frame_error(tmp_path):
    meeting = _write_meeting(
        tmp_path / "Reunion_fferr",
        segments=[
            {
                "start": 5.0,
                "end": 6.0,
                "text": "Este botón falla.",
                "speaker_id": "SPEAKER_01",
            }
        ],
    )
    paths = run_paths_for_directory(meeting)

    def runner(command, check=False, text=True, capture_output=True):
        cmd = list(command)
        if cmd[0] == "ffprobe":
            if "json" in cmd:
                return Mock(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "streams": [
                                {"codec_type": "video", "duration": "20.0"},
                                {"codec_type": "audio", "duration": "19.5"},
                            ]
                        }
                    ),
                    stderr="",
                )
            return Mock(returncode=0, stdout="20.0\n", stderr="")
        return Mock(returncode=1, stdout="", stderr="boom")

    index = extract_visual_evidence(
        paths,
        settings=VisualEvidenceSettings(max_frames_per_candidate=1),
        runner=runner,
    )
    cand = index["candidates"][0]
    assert cand["errors"]
    assert any(f["status"] == "error" for f in cand["frames"])


def test_review_status_roundtrip(tmp_path):
    meeting = _write_meeting(
        tmp_path / "Reunion_rev",
        segments=[
            {
                "start": 3.0,
                "end": 4.0,
                "text": "Fijate acá.",
                "speaker_id": "SPEAKER_00",
            }
        ],
    )
    paths = run_paths_for_directory(meeting)
    index = extract_visual_evidence(
        paths,
        settings=VisualEvidenceSettings(max_frames_per_candidate=1),
        runner=_ffprobe_runner_factory(),
    )
    cid = index["candidates"][0]["id"]
    updated = set_review_status(paths, cid, "useful", note="se ve el modal")
    assert updated["candidates"][0]["review"]["status"] == "useful"
    assert updated["candidates"][0]["review"]["note"] == "se ve el modal"

    # Re-extracción preserva la revisión.
    again = extract_visual_evidence(
        paths,
        settings=VisualEvidenceSettings(max_frames_per_candidate=1),
        runner=_ffprobe_runner_factory(),
    )
    assert again["candidates"][0]["review"]["status"] == "useful"


def test_review_rejects_unknown_status(tmp_path):
    meeting = _write_meeting(
        tmp_path / "Reunion_badrev",
        segments=[
            {
                "start": 1.0,
                "end": 2.0,
                "text": "Fijate acá.",
                "speaker_id": "SPEAKER_00",
            }
        ],
    )
    paths = run_paths_for_directory(meeting)
    extract_visual_evidence(
        paths,
        settings=VisualEvidenceSettings(max_frames_per_candidate=1),
        runner=_ffprobe_runner_factory(),
    )
    with pytest.raises(ValueError, match="inválido"):
        set_review_status(paths, "ve-0000", "awesome")


def test_falls_back_to_whisperx_json_without_attributed(tmp_path):
    meeting = _write_meeting(
        tmp_path / "Reunion_legacy",
        segments=[
            {
                "start": 2.0,
                "end": 3.0,
                "text": "Cuando hago clic acá.",
                "speaker_id": "SPEAKER_02",
            }
        ],
        attributed=False,
    )
    paths = run_paths_for_directory(meeting)
    assert not paths.attributed_transcript.exists()
    index = extract_visual_evidence(
        paths,
        settings=VisualEvidenceSettings(max_frames_per_candidate=1),
        runner=_ffprobe_runner_factory(),
    )
    assert index["candidates"][0]["speaker_id"] == "SPEAKER_02"
    assert index["sync"]["mp4_contains_mixed_audio"] is True
    assert index["sync"]["mp4_audio_stream_s"] is not None


def test_env_settings_validation_and_defaults(monkeypatch):
    from meetings_transcriber.visual_evidence import load_visual_evidence_settings_from_env

    monkeypatch.delenv("VISUAL_EVIDENCE_CONTEXT_BEFORE_S", raising=False)
    cfg = load_visual_evidence_settings_from_env({})
    assert cfg.context_before_s == 1.5

    with pytest.raises(ValueError, match="negativo"):
        load_visual_evidence_settings_from_env({"VISUAL_EVIDENCE_CONTEXT_BEFORE_S": "-1"})
    with pytest.raises(ValueError, match=">= 1"):
        load_visual_evidence_settings_from_env({"VISUAL_EVIDENCE_MAX_FRAMES_PER_CANDIDATE": "0"})

    cfg = load_visual_evidence_settings_from_env(
        {
            "VISUAL_EVIDENCE_CONTEXT_BEFORE_S": "2",
            "VISUAL_EVIDENCE_CONTEXT_AFTER_S": "3",
            "VISUAL_EVIDENCE_FRAME_INTERVAL_S": "0.5",
            "VISUAL_EVIDENCE_MAX_FRAMES_PER_CANDIDATE": "2",
            "VISUAL_EVIDENCE_JPEG_QUALITY": "4",
            "VISUAL_EVIDENCE_EXTRA_PATTERNS": r"custom:\bfoo\b",
        }
    )
    assert cfg.context_before_s == 2.0
    assert cfg.max_frames_per_candidate == 2
    assert cfg.extra_patterns[0][0] == "custom"


def test_plan_edge_cases():
    from meetings_transcriber.visual_evidence import _quantize_timestamp

    assert plan_frame_timestamps(5.0, 5.0, phrase_start=5.0, phrase_end=5.0, interval_s=1.0, max_frames=3) == []
    assert _quantize_timestamp(1.3, quantum=0) == 1.3
    # unique <= max_frames → return temprano
    few = plan_frame_timestamps(
        10.0,
        11.0,
        phrase_start=10.2,
        phrase_end=10.8,
        interval_s=5.0,
        max_frames=10,
    )
    assert 1 <= len(few) <= 10
    # unique > max_frames y hay que agregar al set kept
    stamps = plan_frame_timestamps(
        0.0,
        10.0,
        phrase_start=4.0,
        phrase_end=6.0,
        interval_s=1.0,
        max_frames=4,
    )
    assert len(stamps) == 4


def test_load_transcript_errors_and_skips(tmp_path):
    from meetings_transcriber.visual_evidence import load_transcript_segments

    meeting = tmp_path / "empty"
    meeting.mkdir()
    paths = run_paths_for_directory(meeting)
    with pytest.raises(FileNotFoundError, match="transcripción usable"):
        load_transcript_segments(paths)

    paths.json_result.write_text(
        json.dumps(
            {
                "segments": [
                    "bad",
                    {"start": 1, "end": 0.5, "text": "Fijate acá.", "speaker": "SPEAKER_00"},
                    {"start": 2, "end": 3, "text": "   ", "speaker": "SPEAKER_01"},
                ]
            }
        ),
        encoding="utf-8",
    )
    segments = load_transcript_segments(paths)
    assert len(segments) == 2
    candidates = detect_candidates(
        segments,
        settings=VisualEvidenceSettings(context_before_s=0, context_after_s=0),
    )
    # end < start se corrige; texto vacío se ignora en detect
    assert len(candidates) == 1
    assert candidates[0]["end"] >= candidates[0]["start"]


def test_session_id_fallback_and_window_clip_and_corrupt_index(tmp_path):
    meeting = _write_meeting(
        tmp_path / "Reunion_clip",
        segments=[
            {
                "start": 18.0,
                "end": 19.0,
                "text": "Fijate acá al final.",
                "speaker_id": "SPEAKER_00",
            }
        ],
    )
    paths = run_paths_for_directory(meeting)
    paths.session_meta.write_text("{}", encoding="utf-8")  # sin session_id
    paths.visual_evidence_dir.mkdir(parents=True, exist_ok=True)
    paths.visual_evidence_index.write_text("{not-json", encoding="utf-8")
    index = extract_visual_evidence(
        paths,
        settings=VisualEvidenceSettings(
            context_before_s=0.0,
            context_after_s=5.0,
            max_frames_per_candidate=2,
        ),
        runner=_ffprobe_runner_factory(video_duration=20.0),
    )
    assert index["session_id"] == "Reunion_clip"
    assert any("recortada" in err for err in index["candidates"][0]["errors"])


def test_ffprobe_failures_are_handled(tmp_path):
    meeting = _write_meeting(
        tmp_path / "Reunion_probe",
        segments=[
            {
                "start": 1.0,
                "end": 2.0,
                "text": "Fijate acá.",
                "speaker_id": "SPEAKER_00",
            }
        ],
    )
    paths = run_paths_for_directory(meeting)

    def runner(command, check=False, text=True, capture_output=True):
        cmd = list(command)
        if cmd[0] == "ffprobe" and "json" not in cmd and str(cmd[-1]).endswith(".mp4"):
            return Mock(returncode=1, stdout="", stderr="bad video")
        if cmd[0] == "ffprobe":
            return Mock(returncode=1, stdout="", stderr="bad")
        return Mock(returncode=1, stdout="", stderr="no")

    with pytest.raises(RuntimeError, match="duración del video"):
        extract_visual_evidence(paths, runner=runner)

    def runner_audio_fail(command, check=False, text=True, capture_output=True):
        cmd = list(command)
        if cmd[0] == "ffprobe" and "json" in cmd:
            return Mock(returncode=0, stdout="{bad", stderr="")
        if cmd[0] == "ffprobe" and str(cmd[-1]).endswith(".mp4"):
            return Mock(returncode=0, stdout="10.0\n", stderr="")
        if cmd[0] == "ffprobe":
            raise OSError("wav missing tool")
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\xff\xd8\xff")
        return Mock(returncode=0, stdout="", stderr="")

    index = extract_visual_evidence(
        paths,
        settings=VisualEvidenceSettings(max_frames_per_candidate=1),
        runner=runner_audio_fail,
    )
    assert index["sync"]["mixed_audio_duration_s"] is None


def test_review_missing_index_and_unknown_candidate(tmp_path):
    meeting = _write_meeting(
        tmp_path / "Reunion_rev2",
        segments=[
            {
                "start": 1.0,
                "end": 2.0,
                "text": "Fijate acá.",
                "speaker_id": "SPEAKER_00",
            }
        ],
    )
    paths = run_paths_for_directory(meeting)
    with pytest.raises(FileNotFoundError, match="No existe"):
        set_review_status(paths, "ve-0000", "useful")
    extract_visual_evidence(
        paths,
        settings=VisualEvidenceSettings(max_frames_per_candidate=1),
        runner=_ffprobe_runner_factory(),
    )
    # candidato inexistente + entrada basura en lista
    data = json.loads(paths.visual_evidence_index.read_text(encoding="utf-8"))
    data["candidates"].insert(0, "nope")
    paths.visual_evidence_index.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(KeyError, match="No hay candidato"):
        set_review_status(paths, "ve-missing", "insufficient")


def test_relative_path_outside_meeting(tmp_path):
    from meetings_transcriber.visual_evidence import _relative_to_meeting

    meeting = tmp_path / "meet"
    meeting.mkdir()
    outside = tmp_path / "other" / "frame.jpg"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    assert str(outside.resolve()) == _relative_to_meeting(outside, meeting)


def test_probe_mp4_stream_edge_cases(tmp_path):
    from meetings_transcriber.visual_evidence import probe_mp4_stream_durations

    video = tmp_path / "x.mp4"
    video.write_bytes(b"x")

    def bad_code(command, check=False, text=True, capture_output=True):
        return Mock(returncode=1, stdout="", stderr="x")

    assert probe_mp4_stream_durations(video, runner=bad_code) == {
        "mp4_video_stream_s": None,
        "mp4_audio_stream_s": None,
    }

    def weird_streams(command, check=False, text=True, capture_output=True):
        return Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "streams": [
                        "nope",
                        {"codec_type": "video", "duration": {"bad": True}},
                        {"codec_type": "audio", "duration": None},
                    ]
                }
            ),
            stderr="",
        )

    probed = probe_mp4_stream_durations(video, runner=weird_streams)
    assert probed["mp4_video_stream_s"] is None
    assert probed["mp4_audio_stream_s"] is None


def test_real_ffmpeg_extracts_frame_from_mp4_with_audio(tmp_path):
    """El MP4 de producción trae AAC; FFmpeg real debe extraer JPG ignorando audio."""
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe no disponibles")

    video = tmp_path / "with_audio.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x240:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(video),
        ],
        check=True,
    )
    # Confirmar que el contenedor tiene audio.
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(video),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "audio" in probe.stdout
    assert "video" in probe.stdout

    meeting = tmp_path / "Reunion_realff"
    meeting.mkdir()
    paths = run_paths_for_directory(meeting)
    import shutil as _shutil

    _shutil.copy(video, paths.video)
    paths.mixed_audio.write_bytes(b"RIFF")
    # WAV falso: mockeamos solo ffprobe del wav vía runner parcial… mejor generar wav corto.
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=200:duration=2",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(paths.mixed_audio),
        ],
        check=True,
    )
    paths.attributed_transcript.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "start": 0.5,
                        "end": 1.0,
                        "text": "Fijate acá.",
                        "speaker_id": "SPEAKER_00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    index = extract_visual_evidence(
        paths,
        settings=VisualEvidenceSettings(
            context_before_s=0.2,
            context_after_s=0.2,
            max_frames_per_candidate=1,
        ),
    )
    assert index["candidates"]
    frame = index["candidates"][0]["frames"][0]
    assert frame["status"] == "ok"
    assert (meeting / frame["path"]).stat().st_size > 0
    assert index["sync"]["mp4_audio_stream_s"] is not None
