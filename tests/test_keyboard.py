"""Testes da leitura de teclas não-bloqueante (msvcrt simulado)."""

from __future__ import annotations

import pytest

from ai_audio_capture import keyboard


class FakeMsvcrt:
    """Dublê de :mod:`msvcrt` com uma fila de bytes a serem "digitados"."""

    def __init__(self, sequence: list[bytes]) -> None:
        self._sequence = list(sequence)

    def kbhit(self) -> bool:
        return bool(self._sequence)

    def getch(self) -> bytes:
        return self._sequence.pop(0)


def test_unavailable_when_no_msvcrt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keyboard, "msvcrt", None)
    assert keyboard.keyboard_available() is False
    assert keyboard.read_key() is None


def test_returns_lowercased_letter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keyboard, "msvcrt", FakeMsvcrt([b"P"]))
    assert keyboard.read_key() == "p"


def test_no_key_pressed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keyboard, "msvcrt", FakeMsvcrt([]))
    assert keyboard.read_key() is None


def test_special_key_prefix_is_discarded(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeMsvcrt([b"\xe0", b"H"])  # seta para cima
    monkeypatch.setattr(keyboard, "msvcrt", fake)
    assert keyboard.read_key() is None
    # Ambos os bytes foram consumidos.
    assert fake.kbhit() is False
