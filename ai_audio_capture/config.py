"""Configuração estruturada e validada da aplicação.

Este módulo centraliza todos os parâmetros ajustáveis em modelos
:class:`pydantic.BaseModel` imutáveis (``frozen``). A validação acontece no
momento da construção, eliminando estados inválidos em tempo de execução
(por exemplo, ``sample_rate`` negativo ou ``duck_factor`` fora de ``[0, 1]``).

As configurações de ambiente (sobrescrevíveis via variáveis ``AAC_*`` ou um
arquivo ``.env``) são expostas por :func:`get_settings`, cujo resultado é
cacheado com :func:`functools.lru_cache` para evitar releitura de disco.

Examples
--------
>>> cfg = AudioConfig()
>>> cfg.sample_rate
16000
>>> RecordingConfig.bytes_from_megabytes(2.5)
2621440
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Taxa de amostragem padrão-ouro para modelos de fala (Whisper, etc.).
SAMPLE_RATE_IA: int = 16_000

#: Tamanho de bloco lido do hardware por iteração (frames).
DEFAULT_BLOCK_SIZE: int = 1024


class AudioConfig(BaseModel):
    """Parâmetros de captura e do processamento DSP em tempo real.

    Attributes
    ----------
    sample_rate:
        Taxa de amostragem em Hz. Padrão 16 kHz para IA.
    block_size:
        Número de frames lidos por chamada de ``record``.
    dither_level:
        Desvio-padrão do ruído gaussiano somado continuamente para
        estabilizar o *noise floor* (evita "estalos" de dither liga/desliga).
    limiter_threshold:
        Limiar acima do qual o *soft limiter* começa a comprimir.
    limiter_knee:
        Largura do joelho (``knee``) da curva ``tanh`` do limitador.
    """

    model_config = {"frozen": True}

    sample_rate: int = Field(default=SAMPLE_RATE_IA, gt=0)
    block_size: int = Field(default=DEFAULT_BLOCK_SIZE, gt=0)
    dither_level: float = Field(default=3e-5, ge=0.0)
    limiter_threshold: float = Field(default=0.9, gt=0.0, le=1.0)
    limiter_knee: float = Field(default=0.1, gt=0.0)


class DuckingConfig(BaseModel):
    """Parâmetros da redução de eco por *ducking* baseado em envelope."""

    model_config = {"frozen": True}

    cutoff_hz: float = Field(default=5.0, gt=0.0)
    threshold: float = Field(default=0.015, ge=0.0)
    duck_factor: float = Field(default=0.1, ge=0.0, le=1.0)
    transition_gain: float = Field(default=50.0, gt=0.0)


class NoiseReductionConfig(BaseModel):
    """Parâmetros da redução de ruído de fundo (``noisereduce``)."""

    model_config = {"frozen": True}

    prop_decrease: float = Field(default=0.9, ge=0.0, le=1.0)


class PostProcessConfig(BaseModel):
    """Controla quais etapas de pós-processamento são aplicadas."""

    model_config = {"frozen": True}

    apply_ducking: bool = False
    apply_noise_reduction: bool = False
    ducking: DuckingConfig = Field(default_factory=DuckingConfig)
    noise_reduction: NoiseReductionConfig = Field(default_factory=NoiseReductionConfig)

    @property
    def is_enabled(self) -> bool:
        """``True`` se ao menos uma etapa de pós-processamento está ativa."""
        return self.apply_ducking or self.apply_noise_reduction


class RecordingConfig(BaseModel):
    """Configuração das fontes, destino e divisão dos arquivos de saída."""

    model_config = {"frozen": True}

    capture_mic: bool = True
    capture_pc: bool = True
    output_dir: Path
    file_name: str
    max_bytes: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_capture_sources(self) -> RecordingConfig:
        """Exige ao menos uma fonte de áudio ativa."""
        if not self.capture_mic and not self.capture_pc:
            raise ValueError("Selecione pelo menos uma fonte de áudio.")
        return self

    @property
    def output_path(self) -> Path:
        """Caminho completo do arquivo-base (antes de eventual divisão)."""
        return self.output_dir / self.file_name

    @property
    def channels(self) -> int:
        """Número de canais do WAV conforme as fontes habilitadas."""
        return int(self.capture_mic) + int(self.capture_pc)

    @staticmethod
    def bytes_from_megabytes(megabytes: float) -> int:
        """Converte um limite em MB para bytes (``0`` = sem limite).

        Parameters
        ----------
        megabytes:
            Limite em mebibytes; valores ``<= 0`` desativam a divisão.

        Returns
        -------
        int
            Limite em bytes, nunca negativo.
        """
        if megabytes <= 0:
            return 0
        return int(megabytes * 1024 * 1024)


class AppSettings(BaseSettings):
    """Configurações de ambiente sobrescrevíveis (prefixo ``AAC_``)."""

    model_config = SettingsConfigDict(
        env_prefix="AAC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    sample_rate: int = SAMPLE_RATE_IA
    block_size: int = DEFAULT_BLOCK_SIZE
    log_file: Path = Path("ai_audio_capture.log")
    log_level: str = "INFO"
    default_output_dir: Path = Path.home() / "Documents" / "Gravações de som PY"

    def audio_config(self) -> AudioConfig:
        """Constrói um :class:`AudioConfig` a partir das configurações."""
        return AudioConfig(sample_rate=self.sample_rate, block_size=self.block_size)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Retorna as configurações de ambiente (cacheadas após a 1ª chamada)."""
    return AppSettings()
