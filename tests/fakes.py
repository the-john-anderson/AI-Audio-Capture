"""Dublês (*fakes*) determinísticos de dispositivos ``soundcard``.

Reutilizados por :mod:`conftest` e pelos testes do gravador, permitem
exercitar todo o pipeline sem hardware de áudio.
"""

from __future__ import annotations

import numpy as np


class FakeStream:
    """Dublê de um *stream* de gravação do ``soundcard``.

    Suporta tanto ``with mic.recorder(...) as s`` quanto chamadas manuais a
    ``__enter__``/``__exit__`` (como faz o worker de loopback).
    """

    def __init__(self, amplitude: float = 0.2, frequency: float = 440.0) -> None:
        self.amplitude = amplitude
        self.frequency = frequency
        self.sample_rate = 16_000
        self.calls = 0
        self.closed = False

    def __enter__(self) -> FakeStream:
        return self

    def __exit__(self, *exc: object) -> bool:
        self.closed = True
        return False

    def record(self, numframes: int) -> np.ndarray:
        self.calls += 1
        samples = np.arange(numframes) / self.sample_rate
        wave = self.amplitude * np.sin(2 * np.pi * self.frequency * samples)
        return wave.reshape(-1, 1).astype(np.float32)


class FakeMic:
    """Dublê de um microfone/loopback do ``soundcard``."""

    def __init__(self, name: str = "FakeMic", id: str = "fake-id") -> None:
        self.name = name
        self.id = id

    def recorder(self, samplerate: int, channels: int = 1, **_: object) -> FakeStream:
        return FakeStream()
