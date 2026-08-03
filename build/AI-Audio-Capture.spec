# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — build LEVE (padrão, sem noisereduce).

Gera um executável pequeno e de inicialização rápida com:
    soundcard + soundfile + numpy + scipy + rich + pydantic

A redução de ruído (``noisereduce``) é omitida para reduzir o pacote. O app
detecta a ausência em tempo de execução e desativa a etapa graciosamente. A
redução de eco (SciPy) continua funcionando.

Notas de empacotamento (verificadas no ambiente):
  * soundcard 0.4.6 traz seu PRÓPRIO hook (collect_data_files) que inclui
    'mediafoundation.py.h', aberto por cffi no import. NÃO desabilite hooks.
  * soundfile traz hook para 'libsndfile_x64.dll'.
  * scipy: hook em _pyinstaller_hooks_contrib cobre os submódulos usados.
  * Requer PyInstaller >= 6.17 para Python 3.14.

Uso:
    pyinstaller build/AI-Audio-Capture.spec --noconfirm
"""

import os

PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
ENTRY = os.path.join(PROJECT_ROOT, "main.py")
ICON = os.path.join(SPECPATH, "icon.ico")

# "Belt-and-suspenders": só necessários se aparecerem avisos de hidden import.
hiddenimports = [
    "_cffi_backend",
    "scipy._lib.messagestream",
    "scipy.special._cdflib",
    "scipy.special._ufuncs",
]

excludes = [
    "noisereduce",
    "scipy.spatial",
    "matplotlib",
    "IPython",
    "tkinter",
    "pandas",
]

a = Analysis(
    [ENTRY],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI-Audio-Capture",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # app interativo (msvcrt + prompts)
    icon=ICON if os.path.exists(ICON) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AI-Audio-Capture",
)
