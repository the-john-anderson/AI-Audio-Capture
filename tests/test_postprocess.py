"""Testes do pós-processamento (ducking real; noisereduce simulado)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from ai_audio_capture import postprocess
from ai_audio_capture.config import (
    DuckingConfig,
    NoiseReductionConfig,
    PostProcessConfig,
)


def test_availability_flags_are_bool() -> None:
    assert isinstance(postprocess.is_ducking_available(), bool)
    assert isinstance(postprocess.is_noise_reduction_available(), bool)


@pytest.mark.skipif(not postprocess.is_ducking_available(), reason="scipy não instalado")
def test_ducking_attenuates_mic_when_pc_loud() -> None:
    n = 16_000
    mic = np.full(n, 0.5)
    pc = np.concatenate([np.zeros(n // 2), np.full(n // 2, 0.5)])
    stereo = np.column_stack((mic, pc))

    out = postprocess.apply_ducking(stereo, 16_000, DuckingConfig())

    quiet = out[: n // 2, 0].mean()  # PC em silêncio → mic preservado
    ducked = out[n // 2 + 4000 :, 0].mean()  # PC alto → mic atenuado
    assert quiet > 0.4
    assert ducked < 0.1
    # O canal do PC nunca é alterado.
    assert np.allclose(out[:, 1], pc)


def test_noise_reduction_preserves_pc_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    # Substitui o noisereduce por uma identidade (testa o roteamento de canais
    # sem invocar o numba/JIT).
    fake = type("NR", (), {"reduce_noise": staticmethod(lambda y, sr, prop_decrease: y)})
    monkeypatch.setattr(postprocess, "_noisereduce", lambda: fake)

    stereo = np.column_stack((np.full(100, 0.3), np.full(100, 0.7)))
    out = postprocess.apply_noise_reduction(stereo, 16_000, NoiseReductionConfig())

    assert out.shape == (100, 2)
    assert np.allclose(out[:, 0], 0.3)  # mic processado (identidade)
    assert np.allclose(out[:, 1], 0.7)  # pc preservado


def test_noise_reduction_mono(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = type("NR", (), {"reduce_noise": staticmethod(lambda y, sr, prop_decrease: y * 0)})
    monkeypatch.setattr(postprocess, "_noisereduce", lambda: fake)
    mono = np.full(50, 0.4)
    out = postprocess.apply_noise_reduction(mono, 16_000, NoiseReductionConfig())
    assert out.shape == (50,)
    assert np.allclose(out, 0.0)


@pytest.mark.skipif(not postprocess.is_ducking_available(), reason="scipy não instalado")
def test_process_file_ducking_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "rec.wav"
    n = 8_000
    mic = np.full(n, 0.5, np.float32)
    pc = np.concatenate([np.zeros(n // 2), np.full(n // 2, 0.5)]).astype(np.float32)
    sf.write(str(path), np.column_stack((mic, pc)), 16_000, subtype="PCM_16")

    config = PostProcessConfig(apply_ducking=True, apply_noise_reduction=False)
    messages: list[str] = []
    postprocess.process_file(path, config, status_cb=messages.append)

    data, _ = sf.read(str(path))
    assert data.shape == (n, 2)
    assert data[n // 2 + 2000 :, 0].mean() < data[: n // 2, 0].mean()
    assert any("eco" in m for m in messages)


def test_process_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        postprocess.process_file(tmp_path / "nope.wav", PostProcessConfig())


def test_process_file_uses_float32_and_preserves_wav_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "stereo.wav"
    original = np.column_stack(
        (
            np.linspace(-0.4, 0.4, 256, dtype=np.float32),
            np.linspace(0.4, -0.4, 256, dtype=np.float32),
        )
    )
    sf.write(str(path), original, 22_050, subtype="PCM_16")
    received_dtypes: list[np.dtype] = []

    def identity_noise_reduction(
        data: np.ndarray,
        _rate: int,
        _config: NoiseReductionConfig,
    ) -> np.ndarray:
        received_dtypes.append(data.dtype)
        return data

    monkeypatch.setattr(postprocess, "apply_noise_reduction", identity_noise_reduction)

    postprocess.process_file(
        path,
        PostProcessConfig(apply_noise_reduction=True),
    )

    info = sf.info(str(path))
    result, rate = sf.read(str(path), dtype="float32", always_2d=True)
    assert received_dtypes == [np.dtype(np.float32)]
    assert rate == 22_050
    assert info.channels == 2
    assert info.subtype == "PCM_16"
    assert result.shape == original.shape


def test_process_file_write_failure_preserves_original_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "original.wav"
    sf.write(str(path), np.full(128, 0.25, np.float32), 16_000, subtype="PCM_16")
    original_bytes = path.read_bytes()
    write_targets: list[Path] = []

    def fail_write(target: str, *_args: object, **_kwargs: object) -> None:
        write_targets.append(Path(target))
        raise OSError("disco indisponível")

    monkeypatch.setattr(postprocess.sf, "write", fail_write)

    with pytest.raises(OSError, match="disco indisponível"):
        postprocess.process_file(path, PostProcessConfig())

    assert write_targets
    assert write_targets[0] != path
    assert path.read_bytes() == original_bytes
    assert set(tmp_path.iterdir()) == {path}
