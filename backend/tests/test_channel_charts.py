"""A chart the agent drew, delivered to a chat (#157).

`create_chart` returns a spec and never a picture: the web chat renders it with
Recharts, and the same payload is persisted so a replay draws the same chart. A
chat platform has neither, so somebody has to produce a PNG - and nobody did.
Three docstrings and the capability's README said the channel adapters rendered
one, the adapters could send an image, and nothing built one. So an agent asked
for a chart on a channel answered "here is the chart" with no chart, which is the
worst shape a bug can take: the sentence is confident and the evidence is absent.
"""

import threading
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.charts._spec import ChartSpec
from app.core.permissions import OrgRoleName
from app.services.channels.base import OutgoingAttachment
from app.services.channels.chart_png import render_chart_png
from app.services.channels.mentions import ChannelAgentRouter, drawn_chart
from app.services.transcript import RecordedToolCall

ROWS = [{"x": "Jan", "revenue": 120}, {"x": "Feb", "revenue": 150}, {"x": "Mar", "revenue": 90}]


def _spec(chart_type: str = "bar", **overrides) -> ChartSpec:
    return ChartSpec(
        chart_type=chart_type,
        title=overrides.pop("title", "Monthly revenue"),
        data=overrides.pop("data", ROWS),
        x_key="x",
        series=overrides.pop("series", [{"key": "revenue", "label": "Revenue"}]),
        **overrides,
    )


def _call(result: str | None, name: str = "create_chart") -> RecordedToolCall:
    return RecordedToolCall(tool_call_id="c-1", tool_name=name, args={}, result=result)


class TestDrawing:
    @pytest.mark.parametrize("chart_type", ["bar", "line", "area", "scatter", "pie"])
    def test_every_chart_type_the_spec_allows_can_be_drawn(self, chart_type: str):
        """A type the tool accepts and the renderer cannot draw is an answer with
        a confident sentence and no picture, which is what this replaced."""
        png = render_chart_png(_spec(chart_type))

        assert png.startswith(b"\x89PNG")

    def test_a_chart_with_no_series_plots_the_numbers_it_was_given(self):
        """A model that sends rows and names no series has still described a
        chart; refusing would turn a small omission into no picture at all."""
        assert render_chart_png(_spec(series=[])).startswith(b"\x89PNG")

    def test_a_gap_in_a_series_is_skipped_rather_than_plotted_as_zero(self):
        """A month with no figure yet is not a month with sales of nil, and a
        line dropping to the axis says the second."""
        with_gap = render_chart_png(_spec(data=[*ROWS, {"x": "Apr", "revenue": None}]))

        assert with_gap != render_chart_png(_spec(data=[*ROWS, {"x": "Apr", "revenue": 0}]))

    def test_a_non_finite_value_is_a_gap_not_a_crash(self):
        """`json.loads` accepts bare `NaN`/`Infinity`, and one reaching `_bounds`
        poisons the axis until PIL cannot convert it and no chart is sent."""
        spec = _spec(data=[{"x": "Jan", "revenue": 120}, {"x": "Feb", "revenue": float("nan")}])

        assert render_chart_png(spec).startswith(b"\x89PNG")

    def test_a_single_row_still_draws(self):
        """The x axis divides by `count - 1` for a line, which is zero here."""
        assert render_chart_png(_spec("line", data=[{"x": "Jan", "revenue": 5}])).startswith(
            b"\x89PNG"
        )

    def test_one_flat_value_does_not_divide_by_a_zero_range(self):
        assert render_chart_png(
            _spec(data=[{"x": "Jan", "revenue": 7}, {"x": "Feb", "revenue": 7}])
        ).startswith(b"\x89PNG")

    def test_a_stacked_bar_chart_draws(self):
        spec = _spec(
            data=[{"x": "Jan", "a": 3, "b": 4}],
            series=[{"key": "a"}, {"key": "b"}],
            style={"stacked": True},
        )
        assert render_chart_png(spec).startswith(b"\x89PNG")

    def test_a_stacked_bars_axis_reaches_the_stack_not_the_tallest_bar(self):
        """The bug: `_bounds` took the max of individual values, so a two-series
        stack climbed to `a + b` while the axis read `max(a, b)` and the bar drew
        past the top of the plot."""
        from app.services.channels.chart_png import _bounds

        rows = [{"x": "Jan", "a": 3, "b": 4}]
        keys = ["a", "b"]
        stacked = _spec(data=rows, series=[{"key": "a"}, {"key": "b"}], style={"stacked": True})
        grouped = _spec(data=rows, series=[{"key": "a"}, {"key": "b"}])

        assert _bounds(stacked, keys) == (0.0, 7.0)
        assert _bounds(grouped, keys) == (0.0, 4.0)

    def test_a_stacked_bar_with_negatives_reaches_below_zero(self):
        from app.services.channels.chart_png import _bounds

        spec = _spec(
            data=[{"x": "Jan", "a": 5, "b": -3, "c": -2}],
            series=[{"key": "a"}, {"key": "b"}, {"key": "c"}],
            style={"stacked": True},
        )

        assert _bounds(spec, ["a", "b", "c"]) == (-5.0, 5.0)
        assert render_chart_png(spec).startswith(b"\x89PNG")

    @pytest.mark.parametrize("color", ["#f00", "red", "#ff0000"])
    def test_an_area_chart_draws_in_any_colour_pillow_accepts(self, color: str):
        """`color` is a free-form string the model picks; only its description
        says hex. A short hex or a named colour crashed `_translucent` and sent
        no chart - the #157 regression this module exists to kill."""
        spec = _spec("area", series=[{"key": "revenue", "color": color}])

        assert render_chart_png(spec).startswith(b"\x89PNG")

    def test_a_pie_of_values_that_sum_to_nothing_draws_no_ring(self):
        """Zero and negative slices have no angle, and dividing by their total is
        a crash where an empty frame is merely useless."""
        spec = _spec("pie", data=[{"x": "Jan", "revenue": 0}, {"x": "Feb", "revenue": -1}])

        assert render_chart_png(spec).startswith(b"\x89PNG")

    def test_the_axis_always_includes_zero(self):
        """A bar chart whose axis starts at the smallest bar exaggerates every
        difference on it - and this picture gets screenshotted into a
        conversation where nobody can check the axis."""
        near = render_chart_png(_spec(data=[{"x": "a", "v": 100}, {"x": "b", "v": 101}]))
        far = render_chart_png(_spec(data=[{"x": "a", "v": 0}, {"x": "b", "v": 101}]))

        assert near == far


class TestChoosingWhatToSend:
    def test_a_turn_that_drew_nothing_sends_no_image(self):
        assert drawn_chart([]) is None
        assert drawn_chart([_call(None, name="web_search")]) is None

    def test_a_chart_call_that_never_returned_is_skipped(self):
        """`result` is None for a call the run was parked on, stopped at, or
        broke before it completed."""
        assert drawn_chart([_call(None)]) is None

    def test_a_result_that_is_not_a_chart_spec_is_skipped(self):
        assert drawn_chart([_call("not json at all")]) is None

    def test_the_chart_is_drawn_from_the_tool_result(self):
        png = drawn_chart([_call(_spec().model_dump_json())])

        assert png is not None
        assert png.startswith(b"\x89PNG")

    def test_the_last_chart_wins(self):
        """A turn that draws twice refined the first attempt, and a reply carries
        one image."""
        first = _spec(title="First")
        second = _spec(title="Second")

        assert drawn_chart([_call(first.model_dump_json()), _call(second.model_dump_json())]) == (
            render_chart_png(second)
        )

    def test_a_chart_that_cannot_be_drawn_does_not_cost_the_answer(self):
        """The reply it came with is what somebody asked for; losing it because
        the picture failed is the more expensive of the two failures."""
        with patch(
            "app.services.channels.mentions.render_chart_png", side_effect=RuntimeError("boom")
        ):
            assert drawn_chart([_call(_spec().model_dump_json())]) is None


def _runner_that_draws() -> AsyncMock:
    """A runner whose turn draws a chart, writes a file, and drops one.

    It fills all three lists it was handed the way `AgentRunnerService.execute`
    does, and takes all three as required keywords: a router that stops passing
    one fails here with a `TypeError` rather than quietly replying without the
    picture, without the file, or without saying a file was dropped.
    """

    async def execute(
        *_args: Any,
        tool_calls: list[RecordedToolCall],
        outbound: list[OutgoingAttachment],
        outbound_refused: list[str],
        **_kwargs: Any,
    ) -> tuple[str, MagicMock]:
        tool_calls.append(_call(_spec().model_dump_json()))
        outbound.append(OutgoingAttachment(filename="revenue.csv", content=b"x,revenue\n"))
        outbound_refused.append("/too-big.csv")
        return "here is the chart", MagicMock()

    return AsyncMock(side_effect=execute)


class TestTheReplyAChannelTurnBuilds:
    """The seam between the two halves above: `drawn_chart` reads what the run
    called, and the run only has somewhere to put it because the router passes a
    list into `execute` (#205).

    Both halves are covered on their own, so deleting `tool_calls=called` from
    either call site leaves the suite green, the coverage gate at 100%, and Slack
    back to "here is the chart" with no chart - which is the #157 shape this
    module exists to keep dead (#515).

    `outbound` and `outbound_refused` are the same seam under different names -
    a list the router builds, hands to `execute` and reads back into
    `AnsweredTurn` - and each was equally undefended: deleting either from
    `answer` left the whole suite green (4381 passed), so a reply could say
    "here is your file" and carry none. All three are asserted here for that
    reason, rather than the one the issue happened to name.
    """

    @pytest.mark.anyio
    async def test_a_mention_that_drew_a_chart_answers_with_the_picture(self):
        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
            agents.get_by_slug = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            exposures.get_for_bot = AsyncMock(return_value=MagicMock(is_active=True))
            runner_cls.return_value.execute = _runner_that_draws()

            answered = await ChannelAgentRouter(MagicMock()).answer(
                "@support chart my revenue",
                platform="slack",
                organization_id=uuid.uuid4(),
                bot_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            )

        assert answered.image_png is not None
        assert answered.image_png.startswith(b"\x89PNG")
        assert [a.filename for a in answered.attachments] == ["revenue.csv"]
        assert answered.refused == ["/too-big.csv"]

    @pytest.mark.anyio
    async def test_a_message_naming_no_handle_answers_with_the_picture_too(self):
        """`answer_default` is the ordinary path on a direct-message bot, and it
        passes its own lists - a fix applied to `answer` alone leaves it out."""
        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
            exposures.list_active_for_bot = AsyncMock(
                return_value=[(MagicMock(), MagicMock(id=uuid.uuid4(), slug="support"))]
            )
            runner_cls.return_value.execute = _runner_that_draws()

            answered = await ChannelAgentRouter(MagicMock()).answer_default(
                "chart my revenue",
                platform="slack",
                organization_id=uuid.uuid4(),
                bot_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            )

        assert answered.image_png is not None
        assert answered.image_png.startswith(b"\x89PNG")
        assert [a.filename for a in answered.attachments] == ["revenue.csv"]
        assert answered.refused == ["/too-big.csv"]

    @pytest.mark.anyio
    @pytest.mark.parametrize("path", ["answer", "answer_default"])
    async def test_a_channel_chart_is_rendered_off_the_event_loop(
        self, path: str, monkeypatch: pytest.MonkeyPatch
    ):
        """Pillow rasterises and PNG-encodes the picture, and a channel turn runs
        on the loop every poller and webhook task on the worker shares - so a
        chart drawn inline stalled every other channel turn for its duration.
        Asserted the way the upload offload is: the render lands on a thread
        other than the loop's, which fails if the `to_thread` is removed."""
        loop_thread = threading.get_ident()
        ran_on: list[int] = []

        def recording(spec: ChartSpec) -> bytes:
            ran_on.append(threading.get_ident())
            return render_chart_png(spec)

        monkeypatch.setattr("app.services.channels.mentions.render_chart_png", recording)
        membership = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))

        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = membership
            members.get_active = membership
            agents.get_by_slug = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            exposures.get_for_bot = AsyncMock(return_value=MagicMock(is_active=True))
            exposures.list_active_for_bot = AsyncMock(
                return_value=[(MagicMock(), MagicMock(id=uuid.uuid4(), slug="support"))]
            )
            runner_cls.return_value.execute = _runner_that_draws()

            answered = await getattr(ChannelAgentRouter(MagicMock()), path)(
                "@support chart my revenue" if path == "answer" else "chart my revenue",
                platform="slack",
                organization_id=uuid.uuid4(),
                bot_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            )

        assert answered.image_png is not None
        assert ran_on and ran_on[0] != loop_thread
