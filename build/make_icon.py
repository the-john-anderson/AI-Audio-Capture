"""Gera o ícone do aplicativo (``build/icon.ico``).

Desenha um microfone estilizado sobre um fundo arredondado e salva um ``.ico``
multi-resolução (usado pelo PyInstaller). Requer Pillow::

    pip install pillow
    python build/make_icon.py

Se Pillow não estiver instalado, o build prossegue sem ícone (o PyInstaller
usa o ícone padrão).
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow não instalado. Instale com: pip install pillow", file=sys.stderr)
    raise SystemExit(1) from None

#: Resolução de desenho (alta, reamostrada para baixo no .ico).
_CANVAS = 256
_OUTPUT = Path(__file__).with_name("icon.ico")
_ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

_BG_TOP = (14, 165, 184)  # ciano
_BG_BOTTOM = (8, 47, 73)  # azul escuro
_MIC = (240, 249, 255)  # branco levemente azulado


def _gradient_background(size: int) -> Image.Image:
    """Cria um fundo com gradiente vertical e cantos arredondados."""
    base = Image.new("RGB", (size, size), _BG_TOP)
    for y in range(size):
        ratio = y / size
        color = tuple(
            int(top + (bottom - top) * ratio)
            for top, bottom in zip(_BG_TOP, _BG_BOTTOM, strict=True)
        )
        for x in range(size):
            base.putpixel((x, y), color)

    rounded = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=255)
    rounded.paste(base, (0, 0), mask)
    return rounded


def _draw_microphone(image: Image.Image) -> None:
    """Desenha a cápsula, o arco e a haste do microfone."""
    size = image.width
    draw = ImageDraw.Draw(image)
    cx = size // 2

    # Cápsula (corpo do microfone).
    cap_w = size * 0.26
    cap_top = size * 0.20
    cap_bottom = size * 0.58
    draw.rounded_rectangle(
        (cx - cap_w / 2, cap_top, cx + cap_w / 2, cap_bottom),
        radius=cap_w / 2,
        fill=_MIC,
    )

    # Arco de suporte (semicírculo aberto para baixo).
    arc_pad = size * 0.16
    draw.arc(
        (arc_pad, size * 0.30, size - arc_pad, size * 0.72),
        start=20,
        end=160,
        fill=_MIC,
        width=max(2, size // 28),
    )

    # Haste vertical e base.
    stem_w = max(2, size // 28)
    draw.rectangle((cx - stem_w / 2, size * 0.66, cx + stem_w / 2, size * 0.82), fill=_MIC)
    draw.rounded_rectangle(
        (cx - size * 0.12, size * 0.82, cx + size * 0.12, size * 0.86),
        radius=size // 40,
        fill=_MIC,
    )


def main() -> None:
    """Renderiza e salva o ícone multi-resolução."""
    image = _gradient_background(_CANVAS)
    _draw_microphone(image)
    image.save(_OUTPUT, format="ICO", sizes=_ICO_SIZES)
    print(f"Ícone gerado: {_OUTPUT}")


if __name__ == "__main__":
    main()
