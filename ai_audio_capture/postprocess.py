"""Pós-processamento opcional dos arquivos gravados.

Implementa duas etapas, ambas aplicadas *após* a gravação (offline), sobre
os arquivos WAV gerados:

* **Redução de eco (*ducking*)** — atenua o microfone quando o áudio do PC
  está alto, usando um envelope de energia filtrado (``scipy``).
* **Redução de ruído de fundo** — remove ruído estacionário do canal do
  microfone (``noisereduce``).

As dependências de DSP (:mod:`scipy` e :mod:`noisereduce`) são importadas sob
demanda via :func:`functools.cache` (*lazy loading*), de modo que a
inicialização permanece rápida e o núcleo funciona sem os extras instalados.
"""

from __future__ import annotations

import functools
import importlib.util
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import soundfile as sf

from .config import DuckingConfig, NoiseReductionConfig, PostProcessConfig
from .logging_setup import get_logger

logger = get_logger(__name__)


@functools.cache
def _scipy_signal() -> Any:
    """Importa ``scipy.signal`` sob demanda (resultado cacheado)."""
    from scipy import signal

    return signal


@functools.cache
def _noisereduce() -> Any:
    """Importa ``noisereduce`` sob demanda (resultado cacheado)."""
    import noisereduce

    return noisereduce


def is_ducking_available() -> bool:
    """Indica se ``scipy`` está disponível para a redução de eco.

    Usa :func:`importlib.util.find_spec` para *não* importar a biblioteca
    apenas para verificar sua presença, preservando o *lazy loading*.
    """
    return importlib.util.find_spec("scipy") is not None


def is_noise_reduction_available() -> bool:
    """Indica se ``noisereduce`` está disponível para a limpeza de ruído.

    Verifica a presença sem importar a pilha de DSP, mantendo a inicialização
    da aplicação rápida.
    """
    return importlib.util.find_spec("noisereduce") is not None


def apply_ducking(
    stereo: npt.NDArray[np.floating],
    rate: int,
    config: DuckingConfig,
) -> npt.NDArray[np.floating]:
    """Aplica *ducking* ao canal do microfone com base na energia do PC.

    Cria um envelope da energia do canal do PC com um filtro passa-baixa de
    fase zero (``filtfilt``, que dá *lookahead*) e usa esse envelope para
    reduzir o ganho do microfone quando o PC está acima do limiar.

    Parameters
    ----------
    stereo:
        Áudio com shape ``(n, 2)`` — coluna 0 = mic, coluna 1 = PC.
    rate:
        Taxa de amostragem em Hz.
    config:
        Parâmetros do *ducking*.

    Returns
    -------
    numpy.ndarray
        Cópia do áudio com o microfone atenuado nos trechos com áudio do PC.
    """
    signal = _scipy_signal()

    mic_data = stereo[:, 0]
    pc_data = stereo[:, 1]

    nyquist = 0.5 * rate
    coeff_b, coeff_a = signal.butter(2, config.cutoff_hz / nyquist, btype="low")
    pc_envelope = signal.filtfilt(coeff_b, coeff_a, np.abs(pc_data))

    # Transição suave de ganho entre 1.0 (sem PC) e duck_factor (PC alto).
    mask = np.clip((pc_envelope - config.threshold) * config.transition_gain, 0.0, 1.0)
    gain = 1.0 - mask * (1.0 - config.duck_factor)

    result = stereo.copy()
    result[:, 0] = mic_data * gain
    return result


def apply_noise_reduction(
    data: npt.NDArray[np.floating],
    rate: int,
    config: NoiseReductionConfig,
) -> npt.NDArray[np.floating]:
    """Reduz ruído de fundo (apenas no canal do microfone se for estéreo).

    Parameters
    ----------
    data:
        Áudio mono ``(n,)`` ou estéreo ``(n, 2)`` (mic, pc).
    rate:
        Taxa de amostragem em Hz.
    config:
        Parâmetros da redução de ruído.

    Returns
    -------
    numpy.ndarray
        Áudio com o microfone limpo; o canal do PC é preservado.
    """
    noisereduce = _noisereduce()

    if data.ndim > 1:
        mic_reduced = noisereduce.reduce_noise(
            y=data[:, 0], sr=rate, prop_decrease=config.prop_decrease
        )
        return np.column_stack((mic_reduced, data[:, 1]))

    return noisereduce.reduce_noise(y=data, sr=rate, prop_decrease=config.prop_decrease)


def process_file(
    path: Path,
    config: PostProcessConfig,
    *,
    status_cb: Callable[[str], None] | None = None,
) -> None:
    """Aplica as etapas habilitadas a um arquivo, sobrescrevendo-o.

    Parameters
    ----------
    path:
        Caminho do arquivo WAV a processar.
    config:
        Quais etapas aplicar e seus parâmetros.
    status_cb:
        *Callback* opcional para reportar progresso textual à UI.

    Raises
    ------
    FileNotFoundError
        Se ``path`` não existir.
    """
    if not path.exists():
        raise FileNotFoundError(path)

    def _notify(message: str) -> None:
        logger.info(message)
        if status_cb is not None:
            status_cb(message)

    source_info = sf.info(str(path))
    data, rate = sf.read(str(path), dtype="float32")

    if config.apply_ducking and data.ndim > 1:
        _notify(f"Aplicando redução de eco em {path.name}")
        data = apply_ducking(data, rate, config.ducking)

    if config.apply_noise_reduction:
        _notify(f"Limpando ruído de fundo em {path.name}")
        data = apply_noise_reduction(data, rate, config.noise_reduction)

    _write_atomic(path, np.asarray(data, dtype=np.float32), rate, source_info.subtype)
    _notify(f"Pós-processamento concluído: {path.name}")


def _write_atomic(
    path: Path,
    data: npt.NDArray[np.floating],
    rate: int,
    subtype: str,
) -> None:
    """Grava em arquivo temporário e substitui ``path`` somente após sucesso."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.stem}-",
            suffix=path.suffix,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        sf.write(str(temporary_path), data, rate, subtype=subtype)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
