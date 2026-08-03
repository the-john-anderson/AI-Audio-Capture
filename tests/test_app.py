"""Testes do fluxo de configuração da aplicação."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_audio_capture import app
from ai_audio_capture.config import AppSettings, RecordingConfig


def test_pc_only_skips_microphone_discovery_and_mic_postprocessing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("recurso de microfone não deve ser consultado")

    def fake_recorder(
        mic: object,
        recording: RecordingConfig,
        _audio: object,
        *,
        logger: logging.Logger,
    ) -> SimpleNamespace:
        captured["mic"] = mic
        captured["recording"] = recording
        captured["logger"] = logger
        return SimpleNamespace(
            error=None,
            generated_files=[recording.output_path],
        )

    def capture_configuration(**kwargs: object) -> None:
        captured["configuration"] = kwargs

    monkeypatch.setattr(app.ui, "print_banner", lambda: None)
    monkeypatch.setattr(app.ui, "prompt_capture_sources", lambda: (False, True))
    monkeypatch.setattr(app.ui, "prompt_output_settings", lambda _default: ("pc", 0.0))
    monkeypatch.setattr(app.ui, "show_configuration", capture_configuration)
    monkeypatch.setattr(app.ui, "show_summary", lambda _files: None)
    monkeypatch.setattr(app.ui, "select_microphone", forbidden)
    monkeypatch.setattr(app.devices, "list_microphones", forbidden)
    monkeypatch.setattr(app.devices, "default_microphone", forbidden)
    monkeypatch.setattr(app.postprocess, "is_ducking_available", forbidden)
    monkeypatch.setattr(app.postprocess, "is_noise_reduction_available", forbidden)
    monkeypatch.setattr(app, "AudioRecorder", fake_recorder)
    monkeypatch.setattr(app, "_record_loop", lambda _recorder: None)
    monkeypatch.setattr(app, "_run_postprocessing", forbidden)

    settings = AppSettings(default_output_dir=tmp_path)
    app._run_session(settings, logging.getLogger("test-pc-only"))

    recording = captured["recording"]
    assert isinstance(recording, RecordingConfig)
    assert captured["mic"] is None
    assert recording.capture_mic is False
    assert recording.capture_pc is True
    assert recording.channels == 1
    assert captured["configuration"] == {
        "mic_name": None,
        "capture_mic": False,
        "capture_pc": True,
        "apply_ducking": False,
        "apply_noise_reduction": False,
        "output_path": str(tmp_path / "pc.wav"),
        "max_mb": 0.0,
    }
