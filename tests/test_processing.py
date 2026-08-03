"""Testes do processamento DSP em tempo real (puro NumPy, sem threads)."""

from __future__ import annotations

import numpy as np
import pytest

from ai_audio_capture.config import AudioConfig
from ai_audio_capture.processing import AudioProcessor, compute_rms


def _proc(**overrides: object) -> AudioProcessor:
    return AudioProcessor(AudioConfig(**overrides))


def test_stereo_shape_and_dtype() -> None:
    out = _proc().process_chunk(np.zeros((1024, 1), np.float32), np.zeros((1024, 1), np.float32))
    assert out.shape == (1024, 2)
    assert out.dtype == np.float32


def test_mic_only_is_mono() -> None:
    out = _proc().process_chunk(np.zeros((512, 1), np.float32), None)
    assert out.shape == (512, 1)


def test_pc_only_is_mono() -> None:
    pc = np.full((512, 1), 0.20, np.float32)

    out = _proc(dither_level=0.0).process_chunk(None, pc)

    assert out.shape == (512, 1)
    assert out.dtype == np.float32
    assert np.allclose(out[:, 0], 0.20, atol=1e-6)


def test_no_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="fonte|source|microfone|PC"):
        _proc().process_chunk(None, None)


def test_channel_order_mic_then_pc() -> None:
    mic = np.full((256, 1), 0.10, np.float32)
    pc = np.full((256, 1), 0.20, np.float32)
    out = _proc(dither_level=0.0).process_chunk(mic, pc)
    assert np.allclose(out[:, 0], 0.10, atol=1e-4)
    assert np.allclose(out[:, 1], 0.20, atol=1e-4)


def test_output_is_bounded() -> None:
    loud = np.full((1024, 1), 5.0, np.float32)
    out = _proc().process_chunk(loud, None)
    assert np.all(np.abs(out) <= 1.0)


def test_soft_limiter_compresses_loud_samples() -> None:
    mic = np.full((8, 1), 0.99, np.float32)
    out = _proc(dither_level=0.0).process_chunk(mic, None)
    assert np.all(out < 0.99)  # comprimido abaixo da entrada
    assert np.all(out <= 1.0)


def test_quiet_samples_pass_through_when_no_dither() -> None:
    mic = np.full((8, 1), 0.5, np.float32)
    out = _proc(dither_level=0.0).process_chunk(mic, None)
    assert np.allclose(out, 0.5, atol=1e-6)


def test_dither_adds_noise_floor() -> None:
    mic = np.zeros((4096, 1), np.float32)
    out = _proc(dither_level=3e-5).process_chunk(mic, None)
    assert np.any(out != 0.0)
    assert compute_rms(out) < 1e-3  # nível baixíssimo


def test_compute_rms() -> None:
    assert compute_rms(np.zeros(10)) == 0.0
    assert compute_rms(np.array([])) == 0.0
    # RMS de uma senoide de amplitude A é A / sqrt(2).
    sine = 0.5 * np.sin(np.linspace(0, 2 * np.pi, 10_000, endpoint=False))
    assert abs(compute_rms(sine) - 0.5 / np.sqrt(2)) < 1e-3
