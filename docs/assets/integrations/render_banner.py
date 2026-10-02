"""Render the README connection illustration. Requires Pillow and rsvg-convert."""

from pathlib import Path
import hashlib
import io
import json
import math
import re
import subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT = Path.cwd()
OUT = ROOT / "docs/assets/integrations"
W, H, SCALE, FRAMES = 960, 300, 2, 72
NODES = [
    ("slack", 100, 68),
    ("drive", 270, 55),
    ("gmail", 68, 164),
    ("notion", 190, 246),
    ("telegram", 332, 237),
    ("github", 683, 57),
    ("outlook", 860, 80),
    ("linear", 716, 243),
    ("mattermost", 892, 224),
]
FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT = ImageFont.truetype(next(p for p in FONT_PATHS if Path(p).exists()), 30 * SCALE)
icons = {}
for key, _, _ in NODES:
    folder = (
        "channels" if key in ("slack", "telegram", "mattermost") else "integrations"
    )
    text = (ROOT / f"docs/assets/{folder}/{key}.svg").read_text()
    inner = re.search(r'<svg x="68".*?</svg>', text, re.S).group()
    inner = re.sub(
        r"<svg[^>]*viewBox=",
        '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox=',
        inner,
        count=1,
    )
    png = subprocess.check_output(["rsvg-convert"], input=inner.encode())
    icons[key] = (
        Image.open(io.BytesIO(png))
        .convert("RGBA")
        .resize((36 * SCALE, 36 * SCALE), Image.Resampling.LANCZOS)
    )


def blend(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def frame(theme, phase):
    dark = theme == "dark"
    bg = (13, 17, 23) if dark else (248, 250, 252)
    line = (39, 49, 65) if dark else (217, 225, 236)
    accent = (117, 135, 249) if dark else (97, 109, 210)
    im = Image.new("RGB", (W * SCALE, H * SCALE), bg)
    d = ImageDraw.Draw(im)
    # Stationary, undirected links: this is a connection illustration, not a run trace.
    for index, (_, x, y) in enumerate(NODES):
        start = (400 if x < 480 else 560, 150)
        pts = []
        for i in range(101):
            t = i / 100
            u = 1 - t
            px = (
                u**3 * start[0]
                + 3 * u * u * t * (x + start[0]) / 2
                + 3 * u * t * t * (x + start[0]) / 2
                + t**3 * x
            )
            py = u**3 * 150 + 3 * u * u * t * 150 + 3 * u * t * t * y + t**3 * y
            pts.append((px * SCALE, py * SCALE))
        strength = (
            0.10 + 0.75 * (0.5 + 0.5 * math.cos(2 * math.pi * (phase - index / 9))) ** 6
        )
        d.line(pts, fill=blend(line, accent, strength), width=2 * SCALE)
    # A quiet central halo breathes; brand marks never move or distort.
    pulse = (1 - math.cos(phase * 2 * math.pi)) / 2
    for pad, amount in [(16, 0.06), (8, 0.12)]:
        d.rounded_rectangle(
            (
                (388 - pad) * SCALE,
                (116 - pad) * SCALE,
                (572 + pad) * SCALE,
                (184 + pad) * SCALE,
            ),
            radius=(22 + pad) * SCALE,
            fill=blend(bg, accent, amount * (0.6 + 0.4 * pulse)),
        )
    d.rounded_rectangle(
        (388 * SCALE, 116 * SCALE, 572 * SCALE, 184 * SCALE),
        radius=20 * SCALE,
        fill=(24, 30, 43) if dark else (255, 255, 255),
        outline=blend(line, accent, 0.4),
        width=SCALE,
    )
    d.text(
        (480 * SCALE, 150 * SCALE),
        "AgenticOS",
        font=FONT,
        anchor="mm",
        fill=(242, 245, 252) if dark else (31, 39, 58),
    )
    for key, x, y in NODES:
        d.ellipse(
            ((x - 30) * SCALE, (y - 28) * SCALE, (x + 30) * SCALE, (y + 32) * SCALE),
            fill=blend(bg, (0, 0, 0), 0.1),
        )
        d.ellipse(
            ((x - 30) * SCALE, (y - 30) * SCALE, (x + 30) * SCALE, (y + 30) * SCALE),
            fill=(255, 255, 255),
            outline=(225, 230, 240),
            width=SCALE,
        )
        im.paste(icons[key], ((x - 18) * SCALE, (y - 18) * SCALE), icons[key])
    return im.resize((W, H), Image.Resampling.LANCZOS)


outputs = {}
for theme in ["light", "dark"]:
    frames = [frame(theme, i / FRAMES) for i in range(FRAMES)]
    still = OUT / f"connections-{theme}.png"
    frames[0].save(still, optimize=True)
    # One shared palette avoids frame-to-frame quantization flicker.
    palette = frames[0].quantize(colors=256)
    indexed = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    gif = OUT / f"connections-{theme}.gif"
    indexed[0].save(
        gif,
        save_all=True,
        append_images=indexed[1:],
        duration=[80, 80, 90] * (FRAMES // 3),
        loop=0,
        optimize=True,
        disposal=1,
    )
    for p in [still, gif]:
        outputs[p.name] = {
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "bytes": p.stat().st_size,
        }
manifest = {
    "purpose": "Illustrative map of connection options, not a live execution or architecture diagram.",
    "placement": "README integration section after the product tour",
    "dimensions": [W, H],
    "duration_ms": 6000,
    "frames": FRAMES,
    "loop": True,
    "motion": "Stationary brand marks and undirected lines with a gentle connection emphasis and central halo.",
    "source": "render_banner.py; existing SVG tiles and their source manifest.json",
    "outputs": outputs,
}
(OUT / "connections-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(outputs, indent=2))
