#!/usr/bin/env python3
"""Draw the desert the social card is set in, one pixel at a time.

`docs/assets/social-preview-bg.png` is 160 by 80 - one pixel per eight on the
finished 1280x640 card - and it is dithered rather than blended. That is the
whole point: Amigo is a 16-pixel sprite, and a smooth gradient behind a sprite
always reads as a drawing pasted onto somebody else's artwork. An ordered dither
puts the background on the same grid the character is drawn on.

Usage::

    python3 scripts/gen_social_bg.py          # rewrite the background
    python3 scripts/gen_social_bg.py --check  # exit 1 if it is stale
"""

from __future__ import annotations

import argparse
import itertools
import math
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "docs/assets/social-preview-bg.png"

W, H = 160, 80
#: The 8x8 ordered-dither threshold matrix. A larger matrix would band less and
#: look less like a sprite; this one is meant to be visible.
BAYER = [
    [0, 32, 8, 40, 2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21],
]

Colour = tuple[int, int, int]


def rgb(value: str) -> Colour:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def between(stops: list[tuple[float, Colour]], t: float) -> tuple[Colour, Colour, float]:
    """The pair of stops `t` falls between, and how far across them it is."""
    for (p0, c0), (p1, c1) in itertools.pairwise(stops):
        if p0 <= t <= p1:
            return c0, c1, 0.0 if p1 == p0 else (t - p0) / (p1 - p0)
    return stops[-1][1], stops[-1][1], 0.0


def band(
    im: Image.Image, stops: list[tuple[float, Colour]], span: int, tilt: float = 0.0, y0: int = 0
) -> None:
    """Dither the ramp over `span` rows, but paint every row down to the bottom.

    Painting past the ramp is what keeps a ridge drawn afterwards from sitting
    over an unpainted band - which is exactly how the first draft of this had a
    black stripe under the sky.
    """
    px = im.load()
    for y in range(y0, H):
        for x in range(W):
            t = min(1.0, max(0.0, (y - y0) / span + tilt * (x / W - 0.5)))
            a, b, f = between(stops, t)
            px[x, y] = b if f > (BAYER[y % 8][x % 8] + 0.5) / 64 else a


def disc(im: Image.Image, cx: int, cy: int, r: int, colour: Colour) -> None:
    px = im.load()
    for y in range(max(0, cy - r), min(H, cy + r + 1)):
        for x in range(max(0, cx - r), min(W, cx + r + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                px[x, y] = colour


def ridge(
    im: Image.Image, base: int, amp: float, freq: float, phase: float, colour: Colour
) -> None:
    """A skyline: two sines out of phase, so it reads as rock rather than a wave."""
    px = im.load()
    for x in range(W):
        h = base - amp * (
            0.6 * math.sin(x * freq + phase) + 0.4 * math.sin(x * freq * 2.3 + phase * 1.7)
        )
        for y in range(max(0, int(h)), H):
            px[x, y] = colour


def cactus(im: Image.Image, x: int, ground: int, height: int, colour: Colour) -> None:
    px = im.load()
    for y in range(ground - height, ground):
        px[x, y] = colour
        px[x + 1, y] = colour
    for y in range(ground - height + 2, ground - height + 6):
        px[x - 2, y] = colour
        px[x + 3, y] = colour
    for d in range(3):
        px[x - 2, ground - height + 1 + d] = colour
    for d in range(2):
        px[x + 3, ground - height + 2 + d] = colour


def build() -> Image.Image:
    im = Image.new("RGB", (W, H))
    band(
        im,
        [
            (0.0, rgb("#1b1033")),
            (0.35, rgb("#4a2158")),
            (0.62, rgb("#a83a3a")),
            (0.82, rgb("#d9763b")),
            (1.0, rgb("#f2c14e")),
        ],
        span=52,
        tilt=0.10,
    )
    disc(im, 112, 44, 11, rgb("#f6d06a"))
    ridge(im, 54, 7, 0.055, 1.2, rgb("#5b2f4a"))
    ridge(im, 62, 5, 0.085, 3.4, rgb("#3a1e33"))
    band(im, [(0.0, rgb("#32192c")), (1.0, rgb("#1d1019"))], span=16, y0=64)
    for x, height in ((22, 11), (31, 7), (138, 9)):
        cactus(im, x, 64, height, rgb("#241320"))
    return im


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report staleness instead of writing")
    args = parser.parse_args()

    wanted = build()
    if args.check:
        if not TARGET.exists() or Image.open(TARGET).convert("RGB").tobytes() != wanted.tobytes():
            print(f"stale: {TARGET.relative_to(ROOT)}", file=sys.stderr)
            return 1
        return 0
    wanted.save(TARGET)
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
