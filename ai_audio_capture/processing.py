"""Processamento de áudio em tempo real para adequação a modelos de IA.

O :class:`AudioProcessor` é aplicado a cada *chunk* capturado, antes da
escrita em disco. Todas as operações são vetorizadas com NumPy e executadas
*in-place* sempre que possível, para minimizar alocações no caminho quente.

Etapas:

1. **Concatenação de canais** — ``[mic, pc]`` quando há *loopback*.
2. **Dither contínuo** — ruído gaussiano de nível constante que mantém o
   *noise floor* estável, evitando que a IA "alucine" em trechos de silêncio.
3. **Soft limiter** — compressão suave via ``tanh`` acima de um limiar, para
   evitar *clipping* abrupto.
4. **Clip de segurança** — garante o intervalo ``[-1, 1]``.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from .config import AudioConfig

#: Alias para arrays de áudio em ponto flutuante de 32 bits.
FloatArray = npt.NDArray[np.float32]


def compute_rms(samples: npt.NDArray[np.floating]) -> float:
    """Calcula o valor RMS (energia) de um bloco de amostras.

    Parameters
    ----------
    samples:
        Bloco de áudio (qualquer formato/canais).

    Returns
    -------
    float
        RMS no intervalo ``[0, 1]`` para áudio normalizado. ``0.0`` se vazio.
    """
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


class AudioProcessor:
    """Aplica *dithering* e *soft limiting* a blocos de áudio.

    Parameters
    ----------
    config:
        Parâmetros de DSP (nível de dither, limiar e joelho do limitador).
    """

    def __init__(self, config: AudioConfig) -> None:
        self._config = config
        # Gerador moderno (PEP-compatível) e mais rápido que a API legada.
        self._rng = np.random.default_rng()
        self._dither_buffer: FloatArray | None = None

    def process_chunk(
        self,
        audio_mic: FloatArray | None,
        audio_pc: FloatArray | None,
    ) -> FloatArray:
        """Processa um *chunk* e retorna o frame pronto para gravação.

        Parameters
        ----------
        audio_mic:
            Bloco do microfone com shape ``(n, 1)`` ou ``None``.
        audio_pc:
            Bloco do áudio do PC com shape ``(n, 1)`` ou ``None``.

        Returns
        -------
        FloatArray
            Frame ``float32`` com shape ``(n, 2)`` (mic+pc) ou ``(n, 1)``,
            já processado e limitado a ``[-1, 1]``.

        Raises
        ------
        ValueError
            Se nenhum bloco de áudio for fornecido.
        """
        if audio_mic is None and audio_pc is None:
            raise ValueError("É necessário fornecer ao menos uma fonte de áudio.")

        if audio_mic is not None and audio_pc is not None:
            frame = np.concatenate((audio_mic, audio_pc), axis=1)
        else:
            source = audio_mic if audio_mic is not None else audio_pc
            assert source is not None  # garantido pela validação acima
            frame = source.copy()

        if frame.dtype != np.float32:
            frame = frame.astype(np.float32)

        self._apply_dither(frame)
        self._apply_soft_limiter(frame)
        np.clip(frame, -1.0, 1.0, out=frame)
        return frame

    def _apply_dither(self, frame: FloatArray) -> None:
        """Soma ruído gaussiano de nível constante (*in-place*)."""
        level = self._config.dither_level
        if level <= 0.0:
            return

        if self._dither_buffer is None or self._dither_buffer.shape != frame.shape:
            self._dither_buffer = np.empty(frame.shape, dtype=np.float32)

        self._rng.standard_normal(dtype=np.float32, out=self._dither_buffer)
        self._dither_buffer *= level
        frame += self._dither_buffer

    def _apply_soft_limiter(self, frame: FloatArray) -> None:
        """Comprime suavemente amostras acima do limiar (*in-place*)."""
        threshold = self._config.limiter_threshold
        knee = self._config.limiter_knee

        over = np.abs(frame) > threshold
        if not over.any():
            return

        signs = np.sign(frame[over])
        excess = np.abs(frame[over]) - threshold
        frame[over] = signs * (threshold + knee * np.tanh(excess / knee))
