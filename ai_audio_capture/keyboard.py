"""Leitura de teclas não-bloqueante no terminal (Windows).

Encapsula :mod:`msvcrt` para que o restante do código não dependa de uma
API específica de plataforma e para que a leitura de teclas possa ser
simulada em testes. Trata corretamente os prefixos de teclas especiais
(setas/funções), que o código original ignorava silenciosamente.
"""

from __future__ import annotations

try:
    import msvcrt
except ImportError:  # plataformas não-Windows
    msvcrt = None  # type: ignore[assignment]

#: Bytes de prefixo que precedem teclas especiais (setas, F1–F12, etc.).
_SPECIAL_PREFIXES: frozenset[bytes] = frozenset({b"\x00", b"\xe0"})


def keyboard_available() -> bool:
    """``True`` se a leitura de teclas é suportada nesta plataforma."""
    return msvcrt is not None


def read_key() -> str | None:
    """Lê uma tecla pressionada sem bloquear.

    Returns
    -------
    str | None
        A tecla em minúsculo (ex.: ``"p"``), ou ``None`` se nenhuma tecla
        foi pressionada ou se foi uma tecla especial (seta/função), cujo
        segundo byte é consumido e descartado.
    """
    if msvcrt is None or not msvcrt.kbhit():
        return None

    char = msvcrt.getch()
    if char in _SPECIAL_PREFIXES:
        msvcrt.getch()  # descarta o segundo byte da sequência especial
        return None

    return char.decode("utf-8", "replace").lower()
