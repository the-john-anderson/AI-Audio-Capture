"""Testes do cronômetro com pausa (relógio injetado, determinístico)."""

from __future__ import annotations

from ai_audio_capture.timing import ElapsedTimer


class FakeClock:
    """Relógio controlável manualmente para testes."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_elapsed_increases() -> None:
    clock = FakeClock()
    timer = ElapsedTimer(clock=clock)
    clock.advance(5.0)
    assert timer.elapsed() == 5.0


def test_pause_freezes_elapsed() -> None:
    clock = FakeClock()
    timer = ElapsedTimer(clock=clock)
    clock.advance(3.0)
    timer.pause()
    clock.advance(10.0)  # tempo pausado não conta
    assert timer.elapsed() == 3.0
    assert timer.is_paused is True


def test_resume_accumulates_pause() -> None:
    clock = FakeClock()
    timer = ElapsedTimer(clock=clock)
    clock.advance(2.0)
    timer.pause()
    clock.advance(4.0)
    timer.resume()
    clock.advance(1.0)
    assert timer.elapsed() == 3.0  # 2 + 1, descontados os 4 pausados
    assert timer.is_paused is False


def test_pause_and_resume_are_idempotent() -> None:
    clock = FakeClock()
    timer = ElapsedTimer(clock=clock)
    timer.resume()  # sem efeito (não estava pausado)
    clock.advance(1.0)
    timer.pause()
    timer.pause()  # segunda pausa não reinicia o marcador
    clock.advance(5.0)
    timer.resume()
    assert timer.elapsed() == 1.0
