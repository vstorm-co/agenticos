"""Tests for the agent chart tool and the surfaces that render what it emits."""

import json

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities.charts import ChartsToolset
from app.agents.capabilities.charts._spec import (
    ChartSeries,
    ChartSpec,
    ChartStyle,
    parse_chart_spec,
)
from app.agents.capabilities.charts._toolset import ChartSeriesInput

# The toolset is stateless; one instance serves every case below.
_charts = ChartsToolset()


def _tool_ctx(*, retry: int = 0, max_retries: int = 1) -> RunContext[None]:
    """A context with a retry left, which is what a real call starts with."""
    return RunContext(
        deps=None, model=TestModel(), usage=RunUsage(), retry=retry, max_retries=max_retries
    )


class TestCreateChart:
    """The tool emits a valid JSON ChartSpec, or a retry the model can act on."""

    @pytest.mark.parametrize("chart_type", ["line", "bar", "pie", "area", "scatter"])
    def test_create_chart_each_type_returns_valid_spec(self, chart_type: str):
        result = _charts.create_chart(
            _tool_ctx(),
            chart_type=chart_type,
            title="Demo",
            x_values=["A", "B"],
            series=[ChartSeriesInput(key="y", values=[1, 2])],
        )
        payload = json.loads(result)
        assert payload["kind"] == "chart"
        assert payload["chart_type"] == chart_type
        assert payload["title"] == "Demo"

    def test_columns_become_one_row_per_x_value(self):
        """The wire format is rows, and every surface renders rows.

        Two series over a shared axis merge into one row each, which is what
        lets a line chart draw connected lines over a single dataset.
        """
        result = _charts.create_chart(
            _tool_ctx(),
            chart_type="line",
            title="Merged",
            x_values=["Jan", "Feb"],
            series=[
                ChartSeriesInput(key="revenue", values=[10, 20]),
                ChartSeriesInput(key="cost", values=[5, 8]),
            ],
        )
        payload = json.loads(result)
        assert payload["data"] == [
            {"x": "Jan", "revenue": 10.0, "cost": 5.0},
            {"x": "Feb", "revenue": 20.0, "cost": 8.0},
        ]
        assert {s["key"] for s in payload["series"]} == {"revenue", "cost"}

    def test_the_x_key_names_the_field_the_axis_is_stored_under(self):
        result = _charts.create_chart(
            _tool_ctx(),
            chart_type="bar",
            title="Named axis",
            x_values=["Sty"],
            series=[ChartSeriesInput(key="sprzedaz", values=[120])],
            x_key="miesiac",
        )
        payload = json.loads(result)
        assert payload["x_key"] == "miesiac"
        assert payload["data"] == [{"miesiac": "Sty", "sprzedaz": 120.0}]

    def test_explicit_label_colour_and_style_are_preserved(self):
        result = _charts.create_chart(
            _tool_ctx(),
            chart_type="bar",
            title="Styled",
            x_values=["A"],
            series=[ChartSeriesInput(key="v", values=[3], label="Value", color="#123456")],
            style=ChartStyle(grid=False, legend=False, stacked=True, palette=["#abcdef"]),
        )
        payload = json.loads(result)
        assert payload["series"][0]["label"] == "Value"
        assert payload["series"][0]["color"] == "#123456"
        assert payload["style"]["grid"] is False
        assert payload["style"]["stacked"] is True
        assert payload["style"]["palette"] == ["#abcdef"]

    def test_a_scatter_series_may_carry_its_own_x_values(self):
        """Two groups of points at different x positions cannot share an axis.

        They emit a row per point rather than a merged row, which is the shape
        the renderer already detects for a scatter chart.
        """
        result = _charts.create_chart(
            _tool_ctx(),
            chart_type="scatter",
            title="Grouped",
            x_values=[0.0],
            series=[
                ChartSeriesInput(key="A", values=[4.1, 2.8], x_values=[2.0, 3.5], label="Group A"),
                ChartSeriesInput(key="B", values=[1.2], x_values=[1.1], label="Group B"),
            ],
        )
        payload = json.loads(result)
        assert payload["data"] == [
            {"x": 2.0, "A": 4.1},
            {"x": 3.5, "A": 2.8},
            {"x": 1.1, "B": 1.2},
        ]

    def test_an_empty_axis_is_a_retry_naming_the_problem(self):
        with pytest.raises(ModelRetry, match="`x_values` was empty"):
            _charts.create_chart(
                _tool_ctx(),
                chart_type="line",
                title="Empty",
                x_values=[],
                series=[ChartSeriesInput(key="y", values=[])],
            )

    def test_no_series_is_a_retry_naming_the_problem(self):
        with pytest.raises(ModelRetry, match="`series` was empty"):
            _charts.create_chart(
                _tool_ctx(), chart_type="line", title="No series", x_values=["A"], series=[]
            )

    def test_a_series_short_of_values_is_a_retry_naming_both_counts(self):
        """The failure the old free-form `data` argument could not even express.

        A model that sends four months and three numbers has made a mistake it
        can fix, and the refusal has to say which series and how far out it is.
        """
        with pytest.raises(ModelRetry, match=r"'cost' has 3 value\(s\) for 4 x value\(s\)"):
            _charts.create_chart(
                _tool_ctx(),
                chart_type="line",
                title="Ragged",
                x_values=["Jan", "Feb", "Mar", "Apr"],
                series=[ChartSeriesInput(key="cost", values=[1, 2, 3])],
            )

    def test_a_scatter_series_is_measured_against_its_own_axis(self):
        with pytest.raises(ModelRetry, match=r"'A' has 1 value\(s\) for 2 x value\(s\)"):
            _charts.create_chart(
                _tool_ctx(),
                chart_type="scatter",
                title="Ragged scatter",
                x_values=[0.0, 1.0, 2.0],
                series=[ChartSeriesInput(key="A", values=[4.1], x_values=[2.0, 3.5])],
            )

    def test_a_spec_the_format_refuses_comes_back_naming_the_field(self):
        """The columns are checked here; the caps on the format still are not.

        `title` is bounded at 200 characters, and rows and series have ceilings,
        so `ChartSpec` can still refuse a call this method was happy to assemble.
        The retry has to carry which field was wrong rather than just that one
        was, which is what `_explain` is for.
        """
        with pytest.raises(ModelRetry, match="title"):
            _charts.create_chart(
                _tool_ctx(),
                chart_type="line",
                title="t" * 201,
                x_values=["Jan"],
                series=[ChartSeriesInput(key="revenue", values=[1])],
            )

    def test_the_shape_that_used_to_draw_an_empty_frame_is_now_unexpressible(self):
        """The payload a user actually received, twice.

        A model answered "here is the trend over six months" with `data=[{}]` and
        a full set of series, labels, colours and axis titles. Every check passed
        - the list did have a row - so a frame was drawn with axes and a legend
        around nothing, which reads as "there is no trend" rather than as a
        mistake. There is no longer an argument in which that can be said: the
        numbers arrive as `values`, and a missing one is a refusal naming it.
        """
        with pytest.raises(TypeError, match="data"):
            _charts.create_chart(  # ty: ignore[unknown-argument]
                _tool_ctx(),
                chart_type="line",
                title="Trend sprzedazy i kosztow",
                data=[{}],
                series=[ChartSeries(key="sprzedaz"), ChartSeries(key="koszt")],
                x_key="miesiac",
            )


class TestParseChartSpec:
    """parse_chart_spec round-trips valid specs and rejects junk."""

    def test_round_trip(self):
        result = _charts.create_chart(
            _tool_ctx(),
            chart_type="pie",
            title="Round trip",
            x_values=["Chrome", "Safari"],
            series=[ChartSeriesInput(key="value", values=[64, 36])],
        )
        spec = parse_chart_spec(result)
        assert isinstance(spec, ChartSpec)
        assert spec.chart_type == "pie"
        assert spec.title == "Round trip"

    def test_non_chart_json_returns_none(self):
        assert parse_chart_spec('{"kind": "something_else"}') is None

    def test_invalid_json_returns_none(self):
        assert parse_chart_spec("not json at all") is None
