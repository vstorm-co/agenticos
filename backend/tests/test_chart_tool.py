"""Tests for the agent chart tool and the surfaces that render what it emits."""

import json

import pytest
from pydantic_ai import ModelRetry

from app.agents.capabilities.charts import ChartsToolset
from app.agents.capabilities.charts._spec import (
    ChartSeries,
    ChartSpec,
    ChartStyle,
    parse_chart_spec,
)

# The toolset is stateless; one instance serves every case below.
_charts = ChartsToolset()


class TestCreateChart:
    """The tool emits a valid JSON ChartSpec, or a retry the model can act on."""

    @pytest.mark.parametrize("chart_type", ["line", "bar", "pie", "area", "scatter"])
    def test_create_chart_each_type_returns_valid_spec(self, chart_type: str):
        result = _charts.create_chart(
            chart_type=chart_type,
            title="Demo",
            data=[{"x": "A", "y": 1}, {"x": "B", "y": 2}],
        )
        payload = json.loads(result)
        assert payload["kind"] == "chart"
        assert payload["chart_type"] == chart_type
        assert payload["title"] == "Demo"

    def test_series_inferred_from_numeric_fields(self):
        result = _charts.create_chart(
            chart_type="line",
            title="Auto series",
            data=[{"x": "Jan", "revenue": 10, "cost": 5}],
        )
        payload = json.loads(result)
        keys = {s["key"] for s in payload["series"]}
        assert keys == {"revenue", "cost"}

    def test_explicit_series_and_style_preserved(self):
        result = _charts.create_chart(
            chart_type="bar",
            title="Styled",
            data=[{"x": "A", "v": 3}],
            series=[ChartSeries(key="v", label="Value", color="#123456")],
            style=ChartStyle(grid=False, legend=False, stacked=True, palette=["#abcdef"]),
        )
        payload = json.loads(result)
        assert payload["series"][0]["label"] == "Value"
        assert payload["series"][0]["color"] == "#123456"
        assert payload["style"]["grid"] is False
        assert payload["style"]["stacked"] is True
        assert payload["style"]["palette"] == ["#abcdef"]

    def test_empty_data_is_a_retry_naming_the_problem(self):
        with pytest.raises(ModelRetry, match="at least one row"):
            _charts.create_chart(chart_type="line", title="Empty", data=[])

    def test_data_with_nothing_numeric_is_a_retry_naming_the_fix(self):
        """The model recovers by naming the series or sending numbers - say so."""
        with pytest.raises(ModelRetry, match="series"):
            _charts.create_chart(
                chart_type="line",
                title="No numbers",
                data=[{"x": "A", "label": "only text"}],
            )


class TestParseChartSpec:
    """parse_chart_spec round-trips valid specs and rejects junk."""

    def test_round_trip(self):
        result = _charts.create_chart(
            chart_type="pie",
            title="Round trip",
            data=[{"x": "Chrome", "value": 64}, {"x": "Safari", "value": 36}],
            series=[ChartSeries(key="value")],
        )
        spec = parse_chart_spec(result)
        assert isinstance(spec, ChartSpec)
        assert spec.chart_type == "pie"
        assert spec.title == "Round trip"

    def test_non_chart_json_returns_none(self):
        assert parse_chart_spec('{"kind": "something_else"}') is None

    def test_invalid_json_returns_none(self):
        assert parse_chart_spec("not json at all") is None
