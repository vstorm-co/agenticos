#!/usr/bin/env python3
"""Derive the walking Amigo from the one drawing, so the two can never disagree.

`docs/assets/amigo.svg` is the desktop pet; the walk is the whole character on a
canvas wide enough to cross, with the legs replaced by two poses that alternate
under him. Only the legs differ between the poses, so the rest is the drawing
itself rather than a copy of it - a second hand-kept sprite is how a pet ends up
with two faces. The product's mark is not Amigo; `frontend/scripts/gen-logo.ts`
writes that.

`backend/tests/test_amigo_assets.py` fails when a re-run would change the walk.

Usage::

    python3 scripts/gen_amigo_assets.py          # rewrite the derived files
    python3 scripts/gen_amigo_assets.py --check  # exit 1 if they are stale
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MASCOT = ROOT / "docs/assets/amigo.svg"
WALK_SVG = ROOT / "docs/assets/amigo-walk.svg"

#: The last row of the body. Everything below it is legs, which the walk redraws.
BODY_ROWS = 16
#: How far he walks, in sprite pixels, and the canvas that leaves room for it.
STRIDE = 32
WALK_W = 16 + STRIDE
#: The two leg poses, apart and together. `(x, width)` per leg, both rows 17-18.
LEGS_APART = ((3, 3), (10, 3))
LEGS_TOGETHER = ((4, 3), (9, 3))
#: The outline brown the legs are drawn in, taken from the drawing rather than
#: named twice.
LEG_FILL = "#4a2c17"

#: A plain pixel. The eyelids the idle animation blinks carry a `class` and are
#: deliberately not matched - they are animation, not drawing.
RECT = re.compile(r'<rect x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)" fill="(#[0-9a-f]{6})"/>')


def read_pixels() -> list[tuple[int, int, int, int, str]]:
    """The mascot's pixels, in paint order."""
    return [
        (int(x), int(y), int(w), int(h), fill)
        for x, y, w, h, fill in RECT.findall(MASCOT.read_text())
    ]


def build_walk() -> str:
    """The character crossing a canvas, on legs that alternate under him."""
    body = "\n".join(
        f'      <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>'
        for x, y, w, h, fill in read_pixels()
        if y <= BODY_ROWS
    )

    def legs(pose: tuple[tuple[int, int], ...]) -> str:
        return "".join(
            f'<rect x="{x}" y="17" width="{w}" height="2" fill="{LEG_FILL}"/>' for x, w in pose
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -1 {WALK_W} 20" width="{WALK_W * 6}" height="120" shape-rendering="crispEdges" role="img" aria-label="Amigo, the AgenticOS pet, walking">
  <title>Amigo</title>
  <style>
    /* A walk, in whole pixels. `steps()` everywhere, because a sprite drawn on a
       16-pixel grid and moved a third of a pixel is a sprite with soft edges -
       the animation has to land on the same grid the drawing does.

       Everything here is additive, and the hidden parts are hidden with an
       `opacity` attribute rather than a rule: where the CSS in an image does not
       run, the frame left behind is Amigo standing at the left of the canvas
       with his eyes open and one pair of legs, rather than a blind sprite with
       four of them. */
    .amigo-walk {{ animation: amigo-cross 7s steps({STRIDE}, end) infinite; }}
    .amigo-bob {{ animation: amigo-bob 0.44s steps(1, end) infinite; }}
    .amigo-step-a {{ animation: amigo-step-a 0.44s steps(1, end) infinite; }}
    .amigo-step-b {{ animation: amigo-step-b 0.44s steps(1, end) infinite; }}
    .amigo-eyelid {{ animation: amigo-blink 4.9s steps(1, end) infinite; }}
    @keyframes amigo-cross {{
      0% {{ transform: translateX(0); }}
      50% {{ transform: translateX({STRIDE}px); }}
      100% {{ transform: translateX(0); }}
    }}
    @keyframes amigo-bob {{
      0%, 49% {{ transform: translateY(0); }}
      50%, 100% {{ transform: translateY(-1px); }}
    }}
    @keyframes amigo-step-a {{
      0%, 49% {{ opacity: 1; }}
      50%, 100% {{ opacity: 0; }}
    }}
    @keyframes amigo-step-b {{
      0%, 49% {{ opacity: 0; }}
      50%, 100% {{ opacity: 1; }}
    }}
    @keyframes amigo-blink {{
      0%, 96% {{ opacity: 0; }}
      97%, 99% {{ opacity: 1; }}
      100% {{ opacity: 0; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .amigo-walk, .amigo-bob, .amigo-step-a, .amigo-step-b, .amigo-eyelid {{
        animation: none;
      }}
    }}
  </style>
  <g class="amigo-walk">
    <g class="amigo-bob">
{body}
      <rect class="amigo-eyelid" opacity="0" x="5" y="6" width="2" height="2" fill="#f1c27d"/>
      <rect class="amigo-eyelid" opacity="0" x="9" y="6" width="2" height="2" fill="#f1c27d"/>
      <g class="amigo-step-a">{legs(LEGS_APART)}</g>
      <g class="amigo-step-b" opacity="0">{legs(LEGS_TOGETHER)}</g>
    </g>
  </g>
</svg>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report staleness instead of writing")
    args = parser.parse_args()

    wanted = {WALK_SVG: build_walk()}
    stale = [path for path, want in wanted.items() if not path.exists() or path.read_text() != want]
    if args.check:
        for path in stale:
            print(f"stale: {path.relative_to(ROOT)}", file=sys.stderr)
        return 1 if stale else 0
    for path, want in wanted.items():
        path.write_text(want)
    for path in stale:
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
