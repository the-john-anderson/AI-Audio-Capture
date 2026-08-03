# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — build COMPLETO (com redução de ruído).

Inclui ``noisereduce`` e suas dependências do caminho NumPy/SciPy. A variante
PyTorch é opcional no upstream e fica fora do bundle. O formato ``onedir``
evita extração a cada abertura e mantém a inicialização previsível.

Pré-requisito extra no código: ``main.py`` chama
``multiprocessing.freeze_support()`` antes de importar o aplicativo, evitando
que subprocessos reabram a sessão interativa.

Uso:
    pyinstaller build/AI-Audio-Capture-full.spec --noconfirm
"""

import os

PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
ENTRY = os.path.join(PROJECT_ROOT, "main.py")
ICON = os.path.join(SPECPATH, "icon.ico")

hiddenimports = [
    "_cffi_backend",
    "noisereduce.noisereduce",
    "noisereduce.spectralgate.base",
    "noisereduce.spectralgate.nonstationary",
    "noisereduce.spectralgate.stationary",
    "noisereduce.spectralgate.utils",
    "scipy._lib.messagestream",
    "scipy.special._ufuncs",
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
    excludes=[
        "noisereduce.spectralgate.streamed_torch_gate",
        "noisereduce.torchgate",
        "torch",
        "tkinter",
        "matplotlib",
        "IPython",
        "pandas",
        "scipy.spatial",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI-Audio-Capture-full",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=ICON if os.path.exists(ICON) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AI-Audio-Capture-full",
)
