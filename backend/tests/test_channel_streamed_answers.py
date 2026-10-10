"""An answer a platform draws itself while it is written, and the steps in it (#2084)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)

from app.services.channels.base import (
    AnswerStep,
    ChannelAdapter,
    IncomingMessage,
    IncomingPress,
    NativeAnswer,
    OutgoingMessage,
    StepSource,
    feedback_value,
    read_feedback,
)
from app.services.channels.live_reply import (
    LiveReply,
    StreamedReply,
    channel_stream,
    step_sources,
)
from app.services.channels.slack_answer import (
    FEEDBACK_ACTION,
    SlackNativeAnswer,
    answer_blocks,
    feedback_block,
    split_first_table,
)

pytestmark = pytest.mark.anyio

TABLE = (
    "Here are the totals:\n\n| Month | Total |\n|---|---:|\n| May | 10 |\n| June | 12 |\n\nBoth up."
)


class TestFeedbackValues:
    def test_a_value_names_the_run_and_the_verdict(self) -> None:
        assert read_feedback(feedback_value("abc", helpful=True)) == ("abc", True)
        assert read_feedback(feedback_value("abc", helpful=False)) == ("abc", False)

    @pytest.mark.parametrize("value", ["aos:prompt:0", "aosfb:abc:maybe", "aosfb:abc"])
    def test_anything_else_is_not_a_rating(self, value: str) -> None:
        assert read_feedback(value) is None


class TestTheDefaultsAPlatformGetsForFree:
    """A platform with no native answer, thumbs or reactions answers the old way."""

    class _Plain(ChannelAdapter):
        platform = "plain"

        async def send_message(self, bot_token: str, msg: OutgoingMessage) -> None: ...
        async def start_polling(self, bot_id: str, bot_token: str) -> None: ...
        async def stop_polling(self, bot_id: str) -> None: ...
        async def register_webhook(self, bot_token: str, url: str, secret: str | None) -> bool:
            return True

        async def delete_webhook(self, bot_token: str) -> bool:
            return True

        def verify_webhook_signature(self, headers: Any, secret: str, body: Any = None) -> bool:
            return True

        def parse_incoming(self, raw_payload: Any, bot_id: str) -> None:
            return None

    async def test_nothing_is_streamed_rated_or_reacted_to(self) -> None:
        adapter = self._Plain()
        incoming = IncomingMessage(
            platform="plain",
            bot_id="b",
            platform_user_id="u",
            platform_chat_id="c",
            chat_type="private",
            text="hi",
        )
        press = IncomingPress(
            platform="plain", bot_id="b", platform_user_id="u", platform_chat_id="c", value="v"
        )

        assert await adapter.open_answer("t", incoming, steps="timeline") is None
        await adapter.offer_feedback("t", OutgoingMessage("c", "hi"), "h", "r", bot_id="b")
        await adapter.settle_feedback("t", press, True)
        await adapter.acknowledge_message("t", incoming, "eyes")


class TestTables:
    def test_the_first_table_is_split_from_the_text_around_it(self) -> None:
        assert split_first_table(TABLE) == (
            "Here are the totals:",
            [["Month", "Total"], ["May", "10"], ["June", "12"]],
            "Both up.",
        )

    @pytest.mark.parametrize(
        "text",
        [
            "No table here.",
            "| only | a header |\nno rule under it",
            "| one |\n|---|\n| cell |",
            "| " + " | ".join(str(i) for i in range(21)) + " |\n|" + "---|" * 21,
        ],
    )
    def test_text_with_no_table_slack_can_draw_is_left_alone(self, text: str) -> None:
        assert split_first_table(text) is None

    def test_a_table_longer_than_slack_allows_stays_text(self) -> None:
        rows = "\n".join(f"| {i} | {i} |" for i in range(100))
        assert split_first_table(f"| a | b |\n|---|---|\n{rows}") is None


class TestAnswerBlocks:
    def test_plain_text_with_nothing_to_rate_needs_no_blocks(self) -> None:
        assert answer_blocks("Just words.", None) is None

    def test_a_table_is_drawn_between_the_text_around_it(self) -> None:
        blocks = answer_blocks(TABLE, "run-1")
        assert blocks is not None
        assert [block["type"] for block in blocks] == [
            "markdown",
            "table",
            "markdown",
            "context_actions",
        ]
        assert blocks[1]["rows"][0] == [
            {"type": "raw_text", "text": "Month"},
            {"type": "raw_text", "text": "Total"},
        ]

    def test_a_table_with_nothing_around_it_is_only_the_table(self) -> None:
        blocks = answer_blocks("| a | b |\n|---|---|\n| 1 | 2 |", None)
        assert blocks is not None
        assert [block["type"] for block in blocks] == ["table"]

    def test_the_thumbs_each_name_the_run_they_rate(self) -> None:
        block = feedback_block("run-1")
        buttons = block["elements"][0]
        assert buttons["action_id"] == FEEDBACK_ACTION
        assert read_feedback(buttons["positive_button"]["value"]) == ("run-1", True)
        assert read_feedback(buttons["negative_button"]["value"]) == ("run-1", False)


def _client() -> MagicMock:
    return MagicMock(
        chat_appendStream=AsyncMock(),
        chat_stopStream=AsyncMock(),
        chat_update=AsyncMock(),
    )


class TestSlackNativeAnswer:
    async def test_text_and_steps_are_appended_to_the_stream(self) -> None:
        client = _client()
        answer = SlackNativeAnswer(client, channel="C1", handle="111.1")

        await answer.append("Hello")
        await answer.step(AnswerStep("call-1", "Searching the web…", "in_progress"))

        assert client.chat_appendStream.await_args_list[0].kwargs == {
            "channel": "C1",
            "ts": "111.1",
            "markdown_text": "Hello",
        }
        assert client.chat_appendStream.await_args_list[1].kwargs["chunks"] == [
            {
                "type": "task_update",
                "id": "call-1",
                "title": "Searching the web…",
                "status": "in_progress",
            }
        ]

    async def test_a_step_links_the_pages_it_read(self) -> None:
        client = _client()
        answer = SlackNativeAnswer(client, channel="C1", handle="111.1")

        await answer.step(
            AnswerStep(
                "1",
                "Searching the web…",
                "complete",
                sources=(StepSource("https://a.example", "A"),),
            )
        )

        task = client.chat_appendStream.await_args.kwargs["chunks"][0]
        assert task["sources"] == [{"type": "url", "url": "https://a.example", "text": "A"}]

    async def test_a_finished_answer_ends_with_its_thumbs(self) -> None:
        client = _client()
        answer = SlackNativeAnswer(client, channel="C1", handle="111.1")

        await answer.finish("Done.", failed=False, feedback_run_id="run-1")

        stopped = client.chat_stopStream.await_args.kwargs
        assert stopped["markdown_text"] == "Done."
        assert stopped["blocks"] == [feedback_block("run-1")]
        client.chat_update.assert_not_awaited()

    async def test_a_failed_answer_is_not_offered_for_rating(self) -> None:
        client = _client()
        answer = SlackNativeAnswer(client, channel="C1", handle="111.1")

        await answer.finish("", failed=True, feedback_run_id="run-1")

        stopped = client.chat_stopStream.await_args.kwargs
        assert stopped["markdown_text"] is None
        assert stopped["blocks"] is None

    async def test_a_table_rewrites_the_streamed_text_as_blocks(self) -> None:
        client = _client()
        answer = SlackNativeAnswer(client, channel="C1", handle="111.1")
        await answer.append(TABLE[:30])

        await answer.finish(TABLE[30:], failed=False, feedback_run_id=None)

        assert client.chat_stopStream.await_args.kwargs["blocks"] is None
        update = client.chat_update.await_args.kwargs
        assert update["text"] == TABLE
        assert [block["type"] for block in update["blocks"]] == ["markdown", "table", "markdown"]


class _Native(NativeAnswer):
    def __init__(self) -> None:
        self.handle = "h"
        self.appended: list[str] = []
        self.steps: list[AnswerStep] = []
        self.finished: tuple[str, bool, str | None] | None = None

    async def append(self, text: str) -> None:
        self.appended.append(text)

    async def step(self, step: AnswerStep) -> None:
        self.steps.append(step)

    async def finish(self, text: str, *, failed: bool, feedback_run_id: str | None) -> None:
        self.finished = (text, failed, feedback_run_id)


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class TestStreamedReply:
    async def test_text_is_appended_at_most_once_a_second(self) -> None:
        native, clock = _Native(), _Clock()
        reply = StreamedReply(native, now=clock)

        await reply.add("Good ")
        await reply.add("morning")
        clock.now += 1.5
        await reply.add(" there")

        assert native.appended == ["Good ", "morning there"]
        assert reply.text == "Good morning there"
        assert reply.handle == "h"

    async def test_a_step_follows_the_text_written_before_it(self) -> None:
        native, clock = _Native(), _Clock()
        reply = StreamedReply(native, now=clock)
        await reply.add("Let me look.")
        await reply.add(" Again.")

        await reply.step(AnswerStep("1", "Looking…", "in_progress"))

        assert native.appended == ["Let me look.", " Again."]
        assert native.steps == [AnswerStep("1", "Looking…", "in_progress")]

    async def test_the_finish_carries_what_was_not_sent_yet(self) -> None:
        native, clock = _Native(), _Clock()
        reply = StreamedReply(native, now=clock)
        await reply.add("Hello")

        assert await reply.finish("Hello world", failed=False, feedback_run_id="r")

        assert native.finished == (" world", False, "r")

    async def test_an_answer_that_does_not_continue_the_stream_is_reported(self) -> None:
        native, clock = _Native(), _Clock()
        reply = StreamedReply(native, now=clock)
        await reply.add("The secret is 42")

        assert not await reply.finish("[redacted]", failed=False, feedback_run_id=None)

        assert native.finished == ("", False, None)

    async def test_a_failed_append_is_carried_by_the_next_one(self) -> None:
        native, clock = _Native(), _Clock()
        native.append = AsyncMock(side_effect=[RuntimeError("rate limited"), None])  # type: ignore[method-assign]
        reply = StreamedReply(native, now=clock)

        await reply.add("Hello")
        clock.now += 1.5
        await reply.add(" world")

        assert native.append.await_args_list[1].args == ("Hello world",)

    async def test_a_step_slack_refused_costs_nothing_else(self) -> None:
        native, clock = _Native(), _Clock()
        native.step = AsyncMock(side_effect=RuntimeError("no"))  # type: ignore[method-assign]
        reply = StreamedReply(native, now=clock)

        await reply.step(AnswerStep("1", "Looking…", "in_progress"))
        await reply.add("Still here")

        assert reply.text == "Still here"


class TestLiveReplySteps:
    async def test_a_step_starting_is_said_and_its_end_is_not(self) -> None:
        pushed: list[str] = []

        async def push(text: str) -> None:
            pushed.append(text)

        reply = LiveReply(push)

        await reply.step(AnswerStep("1", "Searching the web…", "in_progress"))
        await reply.step(AnswerStep("1", "Searching the web…", "complete"))

        assert pushed == ["Searching the web…"]


class _ToolNode:
    def __init__(self, events: list[Any]) -> None:
        self._events = events

    def stream(self, _ctx: Any) -> Any:
        events = self._events

        class _Stream:
            async def __aenter__(self) -> Any:
                async def iterate() -> Any:
                    for event in events:
                        yield event

                return iterate()

            async def __aexit__(self, *exc: object) -> None:
                return None

        return _Stream()


class TestStepsFromARun:
    async def test_each_tool_call_is_a_step_from_its_call_to_its_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pydantic_ai import Agent

        events = [
            FunctionToolCallEvent(ToolCallPart("web_search", {}, tool_call_id="a")),
            FunctionToolResultEvent(ToolReturnPart("web_search", "ok", tool_call_id="a")),
            FunctionToolCallEvent(ToolCallPart("lookup", {}, tool_call_id="b")),
            FunctionToolResultEvent(
                RetryPromptPart("bad args", tool_name="lookup", tool_call_id="b")
            ),
            FunctionToolResultEvent(ToolReturnPart("ghost", "ok", tool_call_id="c")),
        ]
        node = _ToolNode(events)
        monkeypatch.setattr(Agent, "is_model_request_node", staticmethod(lambda _n: False))
        monkeypatch.setattr(Agent, "is_call_tools_node", staticmethod(lambda _n: True))

        class _Run:
            ctx = None

            def __aiter__(self) -> Any:
                async def nodes() -> Any:
                    yield node

                return nodes()

        sink = MagicMock(step=AsyncMock(), add=AsyncMock())
        await channel_stream(sink)(_Run())  # type: ignore[arg-type]

        steps = [call.args[0] for call in sink.step.await_args_list]
        assert [(step.id, step.status) for step in steps] == [
            ("a", "in_progress"),
            ("a", "complete"),
            ("b", "in_progress"),
            ("b", "error"),
            ("c", "complete"),
        ]
        assert steps[0].title == "Searching the web…"
        assert steps[4].title == "Working on it…"


class TestStepSources:
    def test_a_search_result_s_pages_are_its_sources(self) -> None:
        from app.agents.capabilities.web_research._search import WebSearchResult, WebSearchResults

        result = WebSearchResults(
            query="q",
            results=[
                WebSearchResult(title="A", url="https://a.example", content="..."),
                WebSearchResult(title="B", url="https://b.example", content="..."),
                WebSearchResult(title="A again", url="https://a.example", content="..."),
            ],
        )
        assert step_sources(result) == (
            StepSource("https://a.example", "A"),
            StepSource("https://b.example", "B"),
        )

    def test_a_link_without_a_title_is_named_by_itself_and_five_is_enough(self) -> None:
        links = [{"url": f"https://{i}.example"} for i in range(8)] + [{"url": "ftp://x"}]
        found = step_sources({"items": links})
        assert len(found) == 5
        assert found[0] == StepSource("https://0.example", "https://0.example")

    def test_a_result_naming_no_page_links_none(self) -> None:
        assert step_sources("just text") == ()
