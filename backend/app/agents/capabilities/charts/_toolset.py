"""The tool the charts capability exposes.

The public method below is the tool, and its docstring is the only description
of it the model ever reads. Anything else here is a private helper.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from pydantic_ai import ModelRetry
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities.charts._spec import (
    ChartSeries,
    ChartSpec,
    ChartStyle,
    ChartType,
)


def _infer_series(data: list[dict[str, Any]], x_key: str) -> list[ChartSeries]:
    """Derive series from the first row: every numeric field except the x-axis key."""
    if not data:
        return []
    inferred: list[ChartSeries] = []
    for key, value in data[0].items():
        if key == x_key or isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            inferred.append(ChartSeries(key=key))
    return inferred


def _explain(exc: ValidationError) -> str:
    """Render a validation failure as something the model can act on."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'chart'}: {error['msg']}"
        for error in exc.errors(include_url=False)
    )


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
        chart_type: ChartType,
        title: str,
        data: list[dict[str, Any]],
        series: list[ChartSeries] | None = None,
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

        For a scatter chart, give every row a numeric x and y. To colour points
        by group, add a field naming the group and define one series per group
        whose key is the group's value:
        `data=[{"x": 2.0, "y": 4.1, "group": "A"}, {"x": 3.5, "y": 2.8, "group": "B"}]`,
        `series=[{"key": "A", "label": "Group A"}, {"key": "B", "label": "Group B"}]`.

        Args:
            chart_type: `line` for a trend over time, `bar` to compare
                categories, `area` for a running total, `pie` for shares of a
                whole, `scatter` for the relationship between two numbers.
            title: What the chart shows, in a few words. Displayed above it.
            data: One dict per row, e.g.
                `[{"x": "Jan", "revenue": 120, "cost": 80}]`. A pie chart takes
                one value per slice: `[{"x": "Chrome", "value": 64}]`.
            series: Which row fields to plot, with an optional legend `label`
                and hex `color`. Omit to plot every numeric field except `x_key`.
            x_key: The row field holding the x-axis value, or the pie slice
                label. Defaults to `x`.
            style: `palette`, `grid`, `legend`, `x_label`, `y_label`, `stacked`.
                Omit for the interface's own defaults.

        Returns:
            The chart specification, already on its way to the user.
        """
        try:
            spec = ChartSpec(
                chart_type=chart_type,
                title=title,
                data=data,
                x_key=x_key,
                series=series or _infer_series(data, x_key),
                style=style or ChartStyle(),
            )
        except ValidationError as exc:
            raise ModelRetry(
                f"That chart could not be built ({_explain(exc)}). "
                "Correct the arguments and call the tool again."
            ) from exc

        if not spec.series:
            raise ModelRetry(
                f"No numeric field to plot was found in the data besides {x_key!r}. "
                "Either name the fields to plot in `series`, or send rows whose "
                "values are numbers rather than text."
            )

        return spec.model_dump_json()
