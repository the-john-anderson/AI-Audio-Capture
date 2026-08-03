"""Cronometragem de tempo decorrido com suporte a pausa.

Substitui a lógica de timer (com cálculo de pausa invertido) do código
original por um :class:`ElapsedTimer` correto e testável, baseado em
:func:`time.monotonic` (imune a ajustes do relógio do sistema).
"""

from __future__ import annotations

import time
from collections.abc import Callable


class ElapsedTimer:
    """Mede o tempo decorrido, congelando-o durante as pausas.

    O tempo retornado por :meth:`elapsed` exclui todos os intervalos em que
    o timer esteve pausado, de modo que corresponde ao tempo *gravado*.

    Parameters
    ----------
    clock:
        Função que retorna um relógio monotônico em segundos. Injetável para
        testes determinísticos; o padrão é :func:`time.monotonic`.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._start = clock()
        self._paused_total = 0.0
        self._pause_started: float | None = None

    @property
    def is_paused(self) -> bool:
        """``True`` se o timer está atualmente pausado."""
        return self._pause_started is not None

    def pause(self) -> None:
        """Pausa o timer. Idempotente se já estiver pausado."""
        if self._pause_started is None:
            self._pause_started = self._clock()

    def resume(self) -> None:
        """Retoma o timer, acumulando o intervalo pausado. Idempotente."""
        if self._pause_started is not None:
            self._paused_total += self._clock() - self._pause_started
            self._pause_started = None

    def elapsed(self) -> float:
        """Retorna o tempo decorrido em segundos, excluindo as pausas."""
        now = self._clock()
        paused = self._paused_total
        if self._pause_started is not None:
            paused += now - self._pause_started
        return (now - self._start) - paused
