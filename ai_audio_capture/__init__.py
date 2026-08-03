"""AI-Audio-Capture — gravador de áudio CLI otimizado para IA (16 kHz).

Pacote modular que captura microfone e/ou áudio do sistema (loopback), aplica
processamento DSP em tempo real (dither + soft limiter) e oferece
pós-processamento opcional (redução de eco e de ruído).

Módulos principais
------------------
``config``
    Modelos Pydantic validados (áudio, gravação, pós-processamento).
``processing``
    DSP em tempo real aplicado a cada *chunk*.
``devices``
    Enumeração e seleção de microfones / *loopback*.
``recorder``
    Orquestrador multi-thread de captura e escrita.
``postprocess``
    Etapas opcionais (``scipy``/``noisereduce``) com *lazy loading*.
``ui``
    Interface de terminal elegante baseada em ``rich``.
``app``
    Fluxo principal da aplicação (ponto de entrada ``run``).
"""

from __future__ import annotations

__all__ = ["__version__", "run"]

__version__: str = "2.0.0"


def run() -> None:
    """Ponto de entrada da aplicação (importa ``app`` sob demanda)."""
    from .app import run as _run

    _run()
