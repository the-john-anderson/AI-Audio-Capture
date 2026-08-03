"""Enumeração e seleção de dispositivos de áudio.

Encapsula toda a interação com a biblioteca :mod:`soundcard` por trás de
funções simples. Isso cumpre dois objetivos:

* **Isolamento**: o restante do pacote não importa ``soundcard`` diretamente,
  o que torna o :mod:`recorder` testável apenas com *monkeypatch* destas
  funções (sem hardware real).
* **Erros claros**: se a biblioteca ou o *backend* de áudio do sistema não
  estiverem disponíveis, levanta-se :class:`DeviceError` com mensagem útil.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .logging_setup import get_logger

logger = get_logger(__name__)

try:
    import soundcard as _sc
except (ImportError, OSError) as exc:  # backend ausente também levanta OSError
    _sc = None
    _IMPORT_ERROR: Exception | None = exc
else:
    _IMPORT_ERROR = None


@runtime_checkable
class Microphone(Protocol):
    """Interface mínima de um dispositivo de captura (mic ou *loopback*).

    Reflete o subconjunto da API de ``soundcard`` efetivamente usado, o que
    permite substituir por dublês em testes.
    """

    name: str
    id: Any

    def recorder(
        self,
        samplerate: int,
        channels: int,
        blocksize: int = ...,
    ) -> Any:
        """Retorna um gerenciador de contexto de gravação."""
        ...


class DeviceError(RuntimeError):
    """Erro relacionado a dispositivos de áudio ou ao *backend*."""


def _require_soundcard() -> Any:
    """Retorna o módulo ``soundcard`` ou levanta :class:`DeviceError`."""
    if _sc is None:
        raise DeviceError(
            "A biblioteca 'soundcard' não pôde ser carregada "
            f"({_IMPORT_ERROR}). Instale-a com 'pip install soundcard'."
        )
    return _sc


def list_microphones() -> list[Microphone]:
    """Lista todos os microfones de entrada disponíveis no sistema."""
    return list(_require_soundcard().all_microphones())


def default_microphone() -> Microphone:
    """Retorna o microfone padrão do sistema."""
    return _require_soundcard().default_microphone()


def default_speaker_id() -> Any:
    """Retorna o ``id`` do alto-falante padrão atual (para *loopback*)."""
    return _require_soundcard().default_speaker().id


def loopback_for_speaker(speaker_id: Any) -> Microphone:
    """Obtém o microfone de *loopback* associado a um alto-falante.

    Parameters
    ----------
    speaker_id:
        Identificador do alto-falante (ver :func:`default_speaker_id`).
    """
    return _require_soundcard().get_microphone(id=speaker_id, include_loopback=True)
