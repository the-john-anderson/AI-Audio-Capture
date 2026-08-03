"""Fixtures compartilhadas: dublês de ``soundcard`` e logging silencioso.

Permitem exercitar o pipeline multi-thread sem hardware de áudio real,
substituindo os dispositivos por objetos determinísticos.
"""

from __future__ import annotations

import logging

import pytest

from ai_audio_capture import devices
from ai_audio_capture.logging_setup import LOGGER_NAME
from tests.fakes import FakeMic


@pytest.fixture
def fake_mic() -> FakeMic:
    """Retorna um microfone falso."""
    return FakeMic()


@pytest.fixture
def patch_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Substitui a descoberta de *loopback* por dublês determinísticos."""
    monkeypatch.setattr(devices, "default_speaker_id", lambda: "speaker-id")
    monkeypatch.setattr(devices, "loopback_for_speaker", lambda speaker_id: FakeMic(id=speaker_id))


@pytest.fixture(autouse=True)
def quiet_logging():
    """Anexa um ``NullHandler`` para não poluir a saída dos testes."""
    logger = logging.getLogger(LOGGER_NAME)
    handler = logging.NullHandler()
    logger.addHandler(handler)
    logger.propagate = False
    yield
    logger.removeHandler(handler)
