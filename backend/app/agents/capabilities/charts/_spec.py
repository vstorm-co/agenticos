"""The chart wire format: what the tool emits and every surface renders.

One payload serves four consumers, which is why it is a validated model rather
than an ad-hoc dict:

- the tool returns it as a JSON string, so every framework captures it as an
  ordinary tool result,
- it is persisted verbatim in `tool_calls.result` - no schema, no migration,
- the web chat parses it and renders it interactively with Recharts,
- the channel adapters render it server-side to a PNG for Slack and Telegram.

This module holds the format and nothing else. It deliberately imports no agent
machinery, so the delivery layers - which only ever parse a result someone else
produced - can read the format without pulling a toolset in behind it.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

ChartType = Literal["line", "bar", "pie", "area", "scatter"]

# Cap payload size so a runaway model can't emit a multi-megabyte tool result.
MAX_DATA_POINTS = 500
MAX_SERIES = 12


class ChartSeries(BaseModel):
    """One plotted series - maps a key in each data row to a labelled line/bar."""

    key: str = Field(description="Field name in each data row to plot.")
    label: str | None = Field(default=None, description="Legend label (defaults to key).")
    color: str | None = Field(default=None, description="Hex color override, e.g. '#6366f1'.")


class ChartStyle(BaseModel):
    """Agent-controlled styling overrides on top of the frontend defaults."""

    palette: list[str] | None = Field(
        default=None, description="Custom color palette (hex), applied series-by-series."
    )
    grid: bool = Field(default=True, description="Show background grid.")
    legend: bool = Field(default=True, description="Show the legend.")
    x_label: str | None = Field(default=None, description="X-axis title.")
    y_label: str | None = Field(default=None, description="Y-axis title.")
    stacked: bool = Field(default=False, description="Stack bar/area series.")


class ChartSpec(BaseModel):
    """Canonical chart payload produced by the tool and consumed by every surface."""

    kind: Literal["chart"] = "chart"
    chart_type: ChartType
    title: str = Field(max_length=200)
    data: list[dict[str, Any]] = Field(description="Rows, e.g. [{'x': 'Q1', 'revenue': 120}].")
    x_key: str = Field(default="x", description="Row field used for the x-axis / pie label.")
    series: list[ChartSeries] = Field(default_factory=list)
    style: ChartStyle = Field(default_factory=ChartStyle)

    @field_validator("data")
    @classmethod
    def _validate_data(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not v:
            raise ValueError("data must contain at least one row")
        if len(v) > MAX_DATA_POINTS:
            raise ValueError(f"data has too many rows (max {MAX_DATA_POINTS})")
        return v

    @field_validator("series")
    @classmethod
    def _validate_series(cls, v: list[ChartSeries]) -> list[ChartSeries]:
        if len(v) > MAX_SERIES:
            raise ValueError(f"too many series (max {MAX_SERIES})")
        return v


def parse_chart_spec(result: str) -> ChartSpec | None:
    """Parse a chart tool result back into a :class:`ChartSpec`.

    Returns None when the result is anything else - the delivery layers inspect
    every tool result in a turn, so a plain string is the normal case, not an
    error worth raising on.
    """
    try:
        payload = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("kind") != "chart":
        return None
    try:
        return ChartSpec.model_validate(payload)
    except ValidationError:
        return None
