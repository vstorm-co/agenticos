"""The tool the charts capability exposes.

The public method below is the tool, and its docstring is the only description
of it the model ever reads. Anything else here is a private helper.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError
from pydantic_ai.tools import AgentDepsT, RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer
from app.agents.capabilities.charts._spec import (
    ChartSeries,
    ChartSpec,
    ChartStyle,
    ChartType,
)


class ChartSeriesInput(BaseModel):
    """One line, one set of bars or one set of points - and its numbers.

    The numbers arrive here rather than in a free-form `data` argument because a
    free-form object is not something a JSON Schema can describe. `data:
    list[dict[str, Any]]` reached the model as an array of objects with **no
    declared properties**, so the only row it could be certain was valid was
    `{}` - and that is exactly what arrived, twice, from a model that had
    otherwise filled in the series labels, the hex colours, the axis titles and
    the x-axis key. Every check passed, because the list did have a row, and a
    chart frame was drawn around no data at all.

    A list of numbers is expressible, so this shape cannot be got wrong that
    way: there is no field here whose valid values the schema leaves unsaid.
    """

    key: str = Field(description="Row field name for this series, e.g. 'revenue'.")
    values: list[float] = Field(
        description="One number per x value, in the same order as `x_values`."
    )
    label: str | None = Field(default=None, description="Legend label (defaults to key).")
    color: str | None = Field(default=None, description="Hex color override, e.g. '#6366f1'.")
    x_values: list[str | float] | None = Field(
        default=None,
        description=(
            "Only for a scatter series whose points sit at different x values "
            "from the other series. Omit to use the chart's own `x_values`."
        ),
    )


def _explain(exc: ValidationError) -> str:
    """Render a validation failure as something the model can act on."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'chart'}: {error['msg']}"
        for error in exc.errors(include_url=False)
    )


def _rows(
    x_values: list[str | float], series: list[ChartSeriesInput], x_key: str
) -> list[dict[str, Any]]:
    """Turn columns into the row-per-x-value format every surface renders.

    Merged into one row per x value when the series share an x axis, which is
    what lets a line chart draw connected lines over a single dataset. A series
    carrying its own `x_values` cannot be merged with the others - its points
    are somewhere else on the axis - so that case emits one row per point
    instead. The renderer reads both: a row per point with one series key in it
    is the shape it already detects for a scatter chart.
    """
    if any(s.x_values is not None for s in series):
        rows: list[dict[str, Any]] = []
        for s in series:
            xs = s.x_values if s.x_values is not None else x_values
            rows.extend({x_key: x, s.key: value} for x, value in zip(xs, s.values, strict=True))
        return rows
    return [
        {x_key: x, **{s.key: s.values[index] for s in series}} for index, x in enumerate(x_values)
    ]


class ChartsToolset(FunctionToolset[AgentDepsT]):
    """Turns numbers the agent already has into a renderable chart specification.

    The tool does not draw anything: it validates the request into a
    :class:`ChartSpec`, which the web chat renders with Recharts and the channel
    adapters render to a PNG. Arguments the model gets wrong come back as
    `ModelRetry`, so a mistyped chart costs a retry rather than the turn.
    """

    def __init__(self) -> None:
        super().__init__()
        self.add_function(self.create_chart, name="create_chart")

    def create_chart(
        self,
        ctx: RunContext[AgentDepsT],
        chart_type: ChartType,
        title: str,
        x_values: list[str | float],
        series: list[ChartSeriesInput],
        x_key: str = "x",
        style: ChartStyle | None = None,
    ) -> str:
        """Draw a chart of numbers you already have, so the user can see them.

        Use this whenever the user asks to plot, chart, graph or compare
        figures, and whenever a trend, comparison or share of a whole would land
        better as a picture than as prose. The interface draws the chart itself
        - interactively in the web chat, as an image on Slack and Telegram - so
        say in one line what it shows and leave the returned JSON alone; the
        user is looking at the chart, not at the payload.

        A chart is one x axis and one or more series over it. Give the axis once
        in `x_values`, then one entry in `series` per line, bar set or set of
        points, each carrying one number per x value in the same order:

        `x_values=["Jan", "Feb", "Mar"]`,
        `series=[{"key": "revenue", "label": "Revenue", "values": [120, 140, 155]},
                 {"key": "cost", "label": "Cost", "values": [80, 85, 90]}]`

        A pie chart is the same shape with one series - `x_values` names the
        slices and the series holds their sizes:
        `x_values=["Chrome", "Safari"]`, `series=[{"key": "share", "values": [64, 19]}]`.

        A scatter chart puts numbers on both axes, so `x_values` are numbers
        too. When two groups of points sit at different x values, give each
        series its own `x_values`:
        `series=[{"key": "A", "values": [4.1, 2.8], "x_values": [2.0, 3.5]},
                 {"key": "B", "values": [1.2, 3.9], "x_values": [1.1, 4.7]}]`.

        Args:
            chart_type: `line` for a trend over time, `bar` to compare
                categories, `area` for a running total, `pie` for shares of a
                whole, `scatter` for the relationship between two numbers.
            title: What the chart shows, in a few words. Displayed above it.
            x_values: The x axis, one entry per point - category names for
                `line`, `bar` and `area`, slice names for `pie`, numbers for
                `scatter`. This is the chart's data as much as the series are:
                it must not be empty.
            series: One per line/bar set/point set. `key` names it, `values`
                holds one number per x value in the same order, `label` and
                `color` are optional. At least one is required.
            x_key: The row field the x axis is stored under in the emitted
                spec. Cosmetic - it shows in tooltips. Defaults to `x`.
            style: `palette`, `grid`, `legend`, `x_label`, `y_label`, `stacked`.
                Omit for the interface's own defaults.

        Returns:
            The chart specification, already on its way to the user.
        """
        if not x_values:
            return steer(
                ctx,
                "`x_values` was empty, so there is no axis to plot against and "
                "nothing would be drawn. Send one x value per point.",
            )
        if not series:
            return steer(
                ctx,
                "`series` was empty, so there are no numbers to plot. Send one "
                "series per line, bar set or set of points, each with its values.",
            )
        for s in series:
            expected = s.x_values if s.x_values is not None else x_values
            if len(s.values) != len(expected):
                return steer(
                    ctx,
                    f"Series {s.key!r} has {len(s.values)} value(s) for "
                    f"{len(expected)} x value(s). Send one number per x value, "
                    "in the same order.",
                )

        try:
            spec = ChartSpec(
                chart_type=chart_type,
                title=title,
                data=_rows(x_values, series, x_key),
                x_key=x_key,
                series=[ChartSeries(key=s.key, label=s.label, color=s.color) for s in series],
                style=style or ChartStyle(),
            )
        except ValidationError as exc:
            return steer(
                ctx,
                f"That chart could not be built ({_explain(exc)}). "
                "Correct the arguments and call the tool again.",
            )

        return spec.model_dump_json()
