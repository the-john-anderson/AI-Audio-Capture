"""Testes de validação das configurações Pydantic."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_audio_capture.config import (
    AudioConfig,
    DuckingConfig,
    PostProcessConfig,
    RecordingConfig,
)


def test_audio_defaults() -> None:
    cfg = AudioConfig()
    assert cfg.sample_rate == 16_000
    assert cfg.block_size == 1024


@pytest.mark.parametrize("field", ["sample_rate", "block_size"])
def test_audio_rejects_non_positive(field: str) -> None:
    with pytest.raises(ValidationError):
        AudioConfig(**{field: 0})


def test_audio_is_frozen() -> None:
    cfg = AudioConfig()
    with pytest.raises(ValidationError):
        cfg.sample_rate = 44_100  # type: ignore[misc]


def test_ducking_factor_bounds() -> None:
    with pytest.raises(ValidationError):
        DuckingConfig(duck_factor=1.5)
    with pytest.raises(ValidationError):
        DuckingConfig(duck_factor=-0.1)


def test_bytes_from_megabytes() -> None:
    assert RecordingConfig.bytes_from_megabytes(0) == 0
    assert RecordingConfig.bytes_from_megabytes(-3) == 0
    assert RecordingConfig.bytes_from_megabytes(2.5) == 2_621_440


@pytest.mark.parametrize(
    ("capture_mic", "capture_pc", "channels"),
    [
        (True, True, 2),
        (True, False, 1),
        (False, True, 1),
    ],
)
def test_recording_accepts_each_capture_mode(
    tmp_path: Path,
    capture_mic: bool,
    capture_pc: bool,
    channels: int,
) -> None:
    rec = RecordingConfig(
        capture_mic=capture_mic,
        capture_pc=capture_pc,
        output_dir=tmp_path,
        file_name="a.wav",
    )

    assert rec.capture_mic is capture_mic
    assert rec.capture_pc is capture_pc
    assert rec.channels == channels
    assert rec.output_path == tmp_path / "a.wav"


def test_recording_defaults_to_both_sources(tmp_path: Path) -> None:
    rec = RecordingConfig(output_dir=tmp_path, file_name="a.wav")

    assert rec.capture_mic is True
    assert rec.capture_pc is True
    assert rec.channels == 2


def test_recording_rejects_no_capture_source(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        RecordingConfig(
            capture_mic=False,
            capture_pc=False,
            output_dir=tmp_path,
            file_name="a.wav",
        )


def test_postprocess_is_enabled() -> None:
    assert PostProcessConfig().is_enabled is False
    assert PostProcessConfig(apply_ducking=True).is_enabled is True
    assert PostProcessConfig(apply_noise_reduction=True).is_enabled is True
