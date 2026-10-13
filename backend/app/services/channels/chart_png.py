"""A chart spec, drawn, for a surface that cannot run Recharts.

`create_chart` returns a `ChartSpec` and never a picture: the web chat renders it
interactively, and the same payload is persisted so a replay draws the same
chart. A chat platform has neither a renderer nor a canvas, so somebody has to
produce a PNG - and until this module existed, nobody did. Three docstrings and
the capability's README said the channel adapters rendered one; the adapters
could send an image, and nothing ever built one, so an agent asked for a chart on
Slack, Telegram or Mattermost answered "here is the chart" with no chart (#157).

Drawn with Pillow, which is already a dependency, rather than matplotlib, which
is thirty megabytes and a font stack for five chart types. The output is
deliberately plain: this is a picture of numbers in a chat window, read at phone
width, and every element that is not a value or its label is one more thing to
misread.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from functools import partial
from io import BytesIO
from typing import Any

from PIL import Image, ImageColor, ImageDraw, ImageFont

from app.agents.capabilities.charts._spec import ChartSpec, ChartType

WIDTH = 1000
HEIGHT = 600
_MARGIN = 64
_LEGEND_HEIGHT = 34
_TITLE_HEIGHT = 52

# Readable on a dark chat theme and on a light one, because a chat window is
# whichever the reader chose and an image cannot follow it.
_BACKGROUND = "#ffffff"
_INK = "#111827"
_MUTED = "#6b7280"
_GRID = "#e5e7eb"

_PALETTE = (
    "#6366f1",
    "#22c55e",
    "#f97316",
    "#06b6d4",
    "#ec4899",
    "#eab308",
    "#8b5cf6",
    "#14b8a6",
    "#f43f5e",
    "#0ea5e9",
    "#84cc16",
    "#a855f7",
)


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """A font that exists everywhere this runs.

    Pillow's bundled bitmap font is not pretty, but it is present in every
    container without a font package - and a chart that fails to render because
    DejaVu is missing is worse than one set in a plain face.
    """
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _numeric(value: Any) -> float | None:
    """The row value as a number, or None if it is not one.

    A gap in a series is legitimate - a month with no figure yet - so a
    non-number is skipped rather than treated as zero, which would draw a line
    dropping to the axis and read as "sales were nil". A non-finite value is a
    gap too: `json.loads` accepts the bare `NaN`/`Infinity` tokens, `dict[str,
    Any]` passes them through, and one reaching `_bounds` poisons min/max and
    `y_for` until PIL raises "cannot convert float NaN to integer" and no chart
    is sent.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _series_keys(spec: ChartSpec) -> list[tuple[str, str, str]]:
    """Every plotted series as (key, label, colour).

    Falls back to "every numeric field that is not the x axis" when the spec
    names none: a model that sends rows and no `series` has still described a
    chart, and refusing it would turn a small omission into no picture at all.
    """
    palette = spec.style.palette or list(_PALETTE)
    declared = [(s.key, s.label or s.key, s.color) for s in spec.series]
    if not declared:
        found: list[str] = []
        for row in spec.data:
            for key, value in row.items():
                if key != spec.x_key and _numeric(value) is not None and key not in found:
                    found.append(key)
        declared = [(key, key, None) for key in found]
    return [
        (key, label, color or palette[index % len(palette)])
        for index, (key, label, color) in enumerate(declared)
    ]


def _x_labels(spec: ChartSpec) -> list[str]:
    return [str(row.get(spec.x_key, "")) for row in spec.data]


def _bounds(spec: ChartSpec, keys: list[str]) -> tuple[float, float]:
    """The value range to draw, always including zero.

    A bar chart whose axis starts at the smallest bar exaggerates every
    difference on it, and this picture is going to be screenshotted into a
    conversation where nobody can check the axis.
    """
    if spec.style.stacked and spec.chart_type == "bar":
        return _stacked_bounds(spec, keys)
    values = [
        number
        for row in spec.data
        for key in keys
        if (number := _numeric(row.get(key))) is not None
    ]
    if not values:
        return 0.0, 1.0
    low, high = min(min(values), 0.0), max(max(values), 0.0)
    if math.isclose(low, high):
        return low, low + 1.0
    return low, high


def _stacked_bounds(spec: ChartSpec, keys: list[str]) -> tuple[float, float]:
    """The value range for a stacked bar, which reaches the *stack*, not one bar.

    A grouped bar's tallest bar is its largest single value, but a stacked bar's
    is the sum of the positive values in its row - and its lowest, the sum of the
    negatives. Taking the min/max of individual values let a two-series stack
    climb to `a + b` while the axis still read `max(a, b)`, so the bar drew past
    the top of the plot into the title. Positive and negative stack from zero
    separately, the same way `_draw_bars` stacks them.
    """
    highs = [0.0]
    lows = [0.0]
    for row in spec.data:
        numbers = [number for key in keys if (number := _numeric(row.get(key))) is not None]
        highs.append(sum(n for n in numbers if n > 0))
        lows.append(sum(n for n in numbers if n < 0))
    low, high = min(lows), max(highs)
    if math.isclose(low, high):
        return low, low + 1.0
    return low, high


class _Canvas:
    """The plot area, and how a value becomes a pixel."""

    def __init__(self, draw: ImageDraw.ImageDraw, top: int, bottom: int) -> None:
        self.draw = draw
        self.left = _MARGIN + 48
        self.right = WIDTH - _MARGIN
        self.top = top
        self.bottom = bottom

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def y_for(self, value: float, low: float, high: float) -> float:
        return self.bottom - (value - low) / (high - low) * self.height

    def x_for(self, index: int, count: int) -> float:
        """Where row `index` sits, for a chart drawn *on* the axis.

        A line joins points, so the first sits on the axis and the last on the
        right edge.
        """
        if count == 1:
            return self.left + self.width / 2
        return self.left + index * self.width / (count - 1)

    def x_band(self, index: int, count: int) -> float:
        """Where row `index` sits, for a chart drawn *between* gridlines.

        A bar occupies a band rather than a point, so its label belongs at the
        band's centre. Sharing `x_for` put every bar chart's labels a half-band
        to the left of the bars they name, which is the kind of wrong that reads
        as right until somebody compares two of them.
        """
        return self.left + (index + 0.5) * self.width / max(count, 1)


def _draw_axes(
    canvas: _Canvas,
    spec: ChartSpec,
    low: float,
    high: float,
    labels: list[str],
    *,
    banded: bool,
) -> None:
    """The frame, the horizontal rules and the two sets of labels."""
    small = _font(15)
    for step in range(5):
        value = low + (high - low) * step / 4
        y = canvas.y_for(value, low, high)
        if spec.style.grid:
            canvas.draw.line([(canvas.left, y), (canvas.right, y)], fill=_GRID, width=1)
        canvas.draw.text((canvas.left - 12, y), _tidy(value), font=small, fill=_MUTED, anchor="rm")

    canvas.draw.line(
        [(canvas.left, canvas.top), (canvas.left, canvas.bottom)], fill=_MUTED, width=1
    )
    canvas.draw.line(
        [(canvas.left, canvas.bottom), (canvas.right, canvas.bottom)], fill=_MUTED, width=1
    )

    # Every label if they fit, otherwise every nth: overlapping text is less
    # readable than a gap, and a chat window is often half a screen wide.
    stride = max(1, len(labels) // 12 + 1)
    for index, label in enumerate(labels):
        if index % stride:
            continue
        place = canvas.x_band if banded else canvas.x_for
        canvas.draw.text(
            (place(index, len(labels)), canvas.bottom + 10),
            label[:18],
            font=small,
            fill=_MUTED,
            anchor="ma",
        )


def _tidy(value: float) -> str:
    """A number as somebody would write it on an axis."""
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}k".replace(".0k", "k")
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _draw_legend(draw: ImageDraw.ImageDraw, series: list[tuple[str, str, str]], y: int) -> None:
    small = _font(15)
    x = _MARGIN + 48
    for _key, label, color in series:
        draw.rectangle([(x, y), (x + 12, y + 12)], fill=color)
        draw.text((x + 18, y + 6), label, font=small, fill=_INK, anchor="lm")
        x += 30 + int(draw.textlength(label, font=small))


def _draw_bars(canvas: _Canvas, spec: ChartSpec, series, low: float, high: float) -> None:
    rows = len(spec.data)
    group = canvas.width / max(rows, 1)
    zero = canvas.y_for(0.0, low, high)
    for row_index, row in enumerate(spec.data):
        if spec.style.stacked:
            # Positive and negative stack from zero on their own sides, so the
            # top of the stack is the sum of the positives and matches the axis
            # `_stacked_bounds` drew. A single running total mixing signs would
            # not.
            up = 0.0
            down = 0.0
            for key, _label, color in series:
                value = _numeric(row.get(key))
                if value is None:
                    continue
                if value >= 0:
                    base, up = up, up + value
                    top = up
                else:
                    base, down = down, down + value
                    top = down
                start = canvas.y_for(base, low, high)
                end = canvas.y_for(top, low, high)
                x0 = canvas.left + row_index * group + group * 0.2
                x1 = canvas.left + (row_index + 1) * group - group * 0.2
                canvas.draw.rectangle([(x0, min(start, end)), (x1, max(start, end))], fill=color)
            continue
        width = group * 0.7 / max(len(series), 1)
        for series_index, (key, _label, color) in enumerate(series):
            value = _numeric(row.get(key))
            if value is None:
                continue
            x0 = canvas.left + row_index * group + group * 0.15 + series_index * width
            y = canvas.y_for(value, low, high)
            canvas.draw.rectangle(
                [(x0, min(y, zero)), (x0 + width * 0.9, max(y, zero))], fill=color
            )


def _draw_lines(
    canvas: _Canvas, spec: ChartSpec, series, low: float, high: float, *, fill: bool
) -> None:
    count = len(spec.data)
    for key, _label, color in series:
        points = [
            (canvas.x_for(index, count), canvas.y_for(value, low, high))
            for index, row in enumerate(spec.data)
            if (value := _numeric(row.get(key))) is not None
        ]
        if not points:
            continue
        if fill and len(points) > 1:
            zero = canvas.y_for(0.0, low, high)
            canvas.draw.polygon(
                [(points[0][0], zero), *points, (points[-1][0], zero)],
                fill=_translucent(color),
            )
        if len(points) == 1:
            canvas.draw.ellipse(
                [
                    (points[0][0] - 4, points[0][1] - 4),
                    (points[0][0] + 4, points[0][1] + 4),
                ],
                fill=color,
            )
        else:
            canvas.draw.line(points, fill=color, width=3, joint="curve")


def _draw_scatter(canvas: _Canvas, spec: ChartSpec, series, low: float, high: float) -> None:
    count = len(spec.data)
    for key, _label, color in series:
        for index, row in enumerate(spec.data):
            value = _numeric(row.get(key))
            if value is None:
                continue
            x = canvas.x_for(index, count)
            y = canvas.y_for(value, low, high)
            canvas.draw.ellipse([(x - 5, y - 5), (x + 5, y + 5)], fill=color)


def _translucent(color: str) -> tuple[int, int, int]:
    """The series colour, lightened, for the band under an area chart.

    Parsed with the same reader Pillow uses for every `fill` in this module, so
    it accepts everything the rest of the renderer does. Slicing `color[1:3]` by
    hand assumed full 6-digit hex and crashed on anything else - `#f00`, or a
    named colour like `red`, both of which the spec allows and the model picks -
    which sent no chart at all: the #157 regression this module exists to kill.
    """
    red, green, blue = ImageColor.getrgb(color)[:3]
    return (
        red + (255 - red) * 3 // 4,
        green + (255 - green) * 3 // 4,
        blue + (255 - blue) * 3 // 4,
    )


def _draw_pie(draw: ImageDraw.ImageDraw, spec: ChartSpec, series, top: int, bottom: int) -> None:
    """One ring, from the first series - a pie of several series is two charts."""
    key = series[0][0] if series else None
    palette = spec.style.palette or list(_PALETTE)
    slices = [
        (str(row.get(spec.x_key, "")), value)
        for row in spec.data
        if (value := _numeric(row.get(key))) is not None and value > 0
    ]
    total = sum(value for _label, value in slices)
    if total <= 0:
        return

    size = min(bottom - top, WIDTH // 2)
    box = [
        (WIDTH // 2 - size // 2, top),
        (WIDTH // 2 + size // 2, top + size),
    ]
    small = _font(15)
    angle = -90.0
    for index, (label, value) in enumerate(slices):
        sweep = value / total * 360
        draw.pieslice(box, angle, angle + sweep, fill=palette[index % len(palette)])
        middle = math.radians(angle + sweep / 2)
        draw.text(
            (
                WIDTH // 2 + math.cos(middle) * (size * 0.62),
                top + size / 2 + math.sin(middle) * (size * 0.62),
            ),
            f"{label} {value / total * 100:.0f}%",
            font=small,
            fill=_INK,
            anchor="mm",
        )
        angle += sweep


Renderer = Callable[[ImageDraw.ImageDraw, ChartSpec, list[tuple[str, str, str]], int, int], None]
"""Draws one chart type onto `draw` between `top` and `bottom`, given the series."""


def _plotted(
    draw_series: Callable[[_Canvas, ChartSpec, list[tuple[str, str, str]], float, float], None],
    *,
    banded: bool = False,
) -> Renderer:
    """A renderer for a chart with axes: the frame, then `draw_series` inside it."""

    def render(
        draw: ImageDraw.ImageDraw,
        spec: ChartSpec,
        series: list[tuple[str, str, str]],
        top: int,
        bottom: int,
    ) -> None:
        canvas = _Canvas(draw, top + 16, bottom - 28)
        keys = [key for key, _label, _color in series]
        low, high = _bounds(spec, keys)
        _draw_axes(canvas, spec, low, high, _x_labels(spec), banded=banded)
        draw_series(canvas, spec, series, low, high)

    return render


RENDERERS: dict[ChartType, Renderer] = {
    "line": _plotted(partial(_draw_lines, fill=False)),
    "area": _plotted(partial(_draw_lines, fill=True)),
    "bar": _plotted(_draw_bars, banded=True),
    "scatter": _plotted(_draw_scatter),
    "pie": _draw_pie,
}
"""One renderer per `ChartType`, and nothing else decides.

The capability's type list and this table have to agree, and they are two lists
in two packages: a type the tool accepts and this table lacks used to fall into
an `else` and come out as a line chart, with no failure and no note - which is
the same pixels as an answer. `tests/test_channel_charts.py` holds the two lists
equal, so a sixth type fails there rather than in somebody's Slack.
"""


def render_chart_png(spec: ChartSpec) -> bytes:
    """Draw `spec` and return the PNG bytes."""
    image = Image.new("RGB", (WIDTH, HEIGHT), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((_MARGIN, 26), spec.title[:80], font=_font(26), fill=_INK, anchor="lm")

    series = _series_keys(spec)
    legend = spec.style.legend and len(series) > 1
    bottom = HEIGHT - _MARGIN - (_LEGEND_HEIGHT if legend else 0)

    RENDERERS[spec.chart_type](draw, spec, series, _TITLE_HEIGHT, bottom)

    if legend:
        _draw_legend(draw, series, HEIGHT - _MARGIN - 6)

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
