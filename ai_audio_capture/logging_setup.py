"""Configuração de *logging* estruturado da aplicação.

Centraliza a criação do logger raiz do pacote (``ai_audio_capture``), com
rotação de arquivo para evitar crescimento ilimitado do log de auditoria do
pipeline. A função :func:`configure_logging` é idempotente: chamá-la mais de
uma vez não duplica *handlers*.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

#: Nome do logger raiz do pacote. Submódulos usam ``getLogger(__name__)``.
LOGGER_NAME: str = "ai_audio_capture"

_LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(threadName)-16s | %(name)s | %(message)s"
_MAX_LOG_BYTES: int = 2_000_000
_LOG_BACKUPS: int = 3


def configure_logging(
    log_file: Path,
    level: str = "INFO",
) -> logging.Logger:
    """Configura e retorna o logger raiz do pacote.

    Parameters
    ----------
    log_file:
        Caminho do arquivo de log (criado/rotacionado automaticamente).
    level:
        Nível mínimo (``"DEBUG"``, ``"INFO"``, ``"WARNING"``, ...).

    Returns
    -------
    logging.Logger
        O logger configurado. Em chamadas subsequentes, retorna o mesmo
        logger sem adicionar *handlers* duplicados.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(level.upper())

    handler = RotatingFileHandler(
        log_file,
        maxBytes=_MAX_LOG_BYTES,
        backupCount=_LOG_BACKUPS,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(handler)
    logger.propagate = False

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Atalho para obter um logger filho do pacote.

    Parameters
    ----------
    name:
        Sufixo do logger (geralmente ``__name__``). Se ``None``, retorna o
        logger raiz.
    """
    if name is None:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(name)
