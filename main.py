"""Ponto de entrada legado da aplicação AI-Audio-Capture.

Mantido para compatibilidade com ``python main.py`` e com o build do
executável (PyInstaller aponta para este arquivo). Toda a lógica foi
modularizada no pacote :mod:`ai_audio_capture`.
"""

from __future__ import annotations

import multiprocessing


def main() -> None:
    """Inicia a aplicação interativa."""
    # Deve ocorrer antes de importar a pilha de pós-processamento. No bundle
    # completo, processos-filhos importam este módulo novamente.
    multiprocessing.freeze_support()

    from ai_audio_capture.app import run

    run()


if __name__ == "__main__":
    main()
