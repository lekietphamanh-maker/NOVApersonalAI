"""Draws Nova's app icon (the rings of the phone icon, sharp at every size) into packaging/nova.ico and nova.png.

Run once after changing the design: python scripts/make_icon.py. The .ico holds 16 to 256 px, for the exe, the
installer, shortcuts and the tray.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE, SCALE = 256, 4  # drawn 4x larger, then shrunk: smooth edges
BACKGROUND = (8, 19, 26, 255)
RINGS = ((0.47, (29, 70, 88, 255), 0.022), (0.37, (34, 211, 238, 255), 0.03), (0.25, (94, 234, 212, 255), 0.012))
CORE = (0.11, (200, 248, 255, 255))
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
OUT = Path(__file__).resolve().parent.parent / "packaging"


def draw() -> Image.Image:
    big = SIZE * SCALE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pen.rounded_rectangle((0, 0, big - 1, big - 1), radius=big * 0.22, fill=BACKGROUND)
    middle = big / 2
    for radius, color, width in RINGS:
        r = radius * big
        pen.ellipse((middle - r, middle - r, middle + r, middle + r), outline=color, width=max(1, int(width * big)))
    r = CORE[0] * big
    pen.ellipse((middle - r, middle - r, middle + r, middle + r), fill=CORE[1])
    return image.resize((SIZE, SIZE), Image.LANCZOS)


if __name__ == "__main__":
    icon = draw()
    icon.save(OUT / "nova.png")
    icon.save(OUT / "nova.ico", sizes=SIZES)
    print("wrote", OUT / "nova.ico")
