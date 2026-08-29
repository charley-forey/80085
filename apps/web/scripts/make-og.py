"""Draw the Open Graph card: public/og.png, 1200x630.

Run by hand, and the result is committed. The card carries no metrics by rule
(WEDSITE_DESIGN.md section 11.3), so it never needs regenerating unless the
wordmark itself changes:

    python apps/web/scripts/make-og.py

The digits use the same seven-segment polygons as seg.js and the site icon, so
the card cannot drift away from the readout it depicts. Drawn directly rather
than rasterised from og.svg, which would need an SVG toolchain to say the same
thing.
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

# Segments a-g, in the icon's own 80x80 coordinate space.
POLY = [
    [(24.5, 0), (55.5, 0), (60, 4.5), (55.5, 9), (24.5, 9), (20, 4.5)],
    [(51, 4.5), (55.5, 0), (60, 4.5), (60, 33.5), (55.5, 38), (51, 33.5)],
    [(51, 46.5), (55.5, 42), (60, 46.5), (60, 75.5), (55.5, 80), (51, 75.5)],
    [(24.5, 71), (55.5, 71), (60, 75.5), (55.5, 80), (24.5, 80), (20, 75.5)],
    [(20, 46.5), (24.5, 42), (29, 46.5), (29, 75.5), (24.5, 80), (20, 75.5)],
    [(20, 4.5), (24.5, 0), (29, 4.5), (29, 33.5), (24.5, 38), (20, 33.5)],
    [(24.5, 35.5), (55.5, 35.5), (60, 40), (55.5, 44.5), (24.5, 44.5), (20, 40)],
]

SEG = {"0": 0b1111110, "5": 0b1011011, "8": 0b1111111}

W, H = 1200, 630
INK = (255, 255, 255)
GHOST = (41, 41, 41)  # white at ~16% on black, flattened
PAPER = (0, 0, 0)

SCALE = 2.5
GAP = 30
WORD = "80085"

FONTS = [
    r"C:\Windows\Fonts\consola.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONTS:
        if pathlib.Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def digit(draw: ImageDraw.ImageDraw, char: str, ox: float, oy: float) -> None:
    """One glyph. Unlit segments are drawn too — that is what makes it an LCD."""
    mask = SEG[char]
    for i, points in enumerate(POLY):
        lit = mask & (1 << (6 - i))
        draw.polygon(
            [(ox + x * SCALE, oy + y * SCALE) for x, y in points],
            fill=INK if lit else GHOST,
        )


def main() -> None:
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)

    glyph_w = 40 * SCALE
    total = len(WORD) * glyph_w + (len(WORD) - 1) * GAP
    x = (W - total) / 2 - 20 * SCALE  # the glyph box starts at x=20 in its own space
    y = 120

    for char in WORD:
        digit(draw, char, x, y)
        x += glyph_w + GAP

    for text, size, colour, baseline in [
        ("Your agent stops guessing about your data.", 42, INK, 430),
        ("Someone already figured it out.", 32, (150, 150, 150), 495),
        ("80085.ai", 26, (110, 110, 110), 565),
    ]:
        f = font(size)
        width = draw.textlength(text, font=f)
        draw.text(((W - width) / 2, baseline), text, font=f, fill=colour)

    out = pathlib.Path(__file__).resolve().parents[1] / "public" / "og.png"
    img.save(out, optimize=True)
    print(f"{out} {out.stat().st_size / 1024:.1f}KB")


if __name__ == "__main__":
    main()
