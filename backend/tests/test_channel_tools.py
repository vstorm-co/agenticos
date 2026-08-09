"""What an agent may ask about the channel it is standing in.

Four reads, one contract, three platforms. The tests worth having here are about
the refusals and the boundary rather than the happy path: a directory bound to
one channel, a platform that cannot answer saying so instead of failing the run,
and a provider's own error text staying out of a message the model will quote
into a public channel.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.models.test import TestModel

from app.agents.capabilities import build as build_capabilities
from app.agents.capabilities._registry import CapabilityBinding, CapabilityBuildContext, get
from app.agents.capabilities.channel_tools import (
    CHANNEL_DIRECTORY_RESOURCE,
    ChannelDetails,
    ChannelDirectoryUnsupported,
    ChannelMember,
    ChannelPost,
    ChannelSummary,
    ChannelTools,
    ChannelToolsConfig,
)
from app.agents.capabilities.channel_tools._toolset import build_channel_toolset
from app.services.channels.base import ChannelAdapter
from app.services.channels.directory import (
    PLATFORM_TOOLS,
    TOOL_METHODS,
    BoundChannelDirectory,
    supported_tools,
)
from app.services.channels.mattermost import MattermostAdapter
from app.services.channels.slack import SlackAdapter
from app.services.channels.telegram import TelegramAdapter

pytestmark = pytest.mark.anyio


class FakeDirectory:
    """A directory that answers whatever it was constructed with.

    Records what it was asked for, because half of what these tools have to get
    right is *which* channel and *how much* of it - neither of which shows up in
    the string the model reads.
    """

    def __init__(self, **answers: Any) -> None:
        self.answers = answers
        self.limits: list[int] = []
        self.queries: list[str] = []

    def _answer(self, name: str) -> Any:
        answer = self.answers[name]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def details(self) -> ChannelDetails:
        return self._answer("details")

    async def members(self, *, limit: int) -> list[ChannelMember]:
        self.limits.append(limit)
        return self._answer("members")

    async def search(self, query: str, *, limit: int) -> list[ChannelSummary]:
        self.limits.append(limit)
        self.queries.append(query)
        return self._answer("search")

    async def history(self, *, limit: int) -> list[ChannelPost]:
        self.limits.append(limit)
        return self._answer("history")


ALL_TOOLS = frozenset(get("channel_tools").tool_ids)


def toolset(directory: Any, *, default_limit: int = 20, tools: Any = ALL_TOOLS) -> Any:
    return build_channel_toolset(directory=directory, default_limit=default_limit, tools=tools)


async def call(directory: Any, name: str, /, *, default_limit: int = 20, **kwargs: Any) -> str:
    """Invoke one tool the way the agent would, by the name it is offered under."""
    built = toolset(directory, default_limit=default_limit)
    tools = await built.get_tools(_run_context())
    return await built.call_tool(name, kwargs, _run_context(), tools[name])


def _run_context() -> Any:
    from pydantic_ai._run_context import RunContext

    return RunContext(deps=MagicMock(), model=TestModel(), usage=MagicMock())


class TestWhatTheModelIsToldAboutTheChannel:
    async def test_the_channel_is_described_with_only_the_fields_it_has(self):
        """A blank purpose is absent, not an empty line the model repeats."""
        answer = await call(
            FakeDirectory(details=ChannelDetails(channel_id="c1", name="Support", member_count=3)),
            "get_channel_info",
        )

        assert answer == "Channel: Support\nMembers: 3"

    async def test_a_described_channel_says_whether_it_is_open(self):
        answer = await call(
            FakeDirectory(
                details=ChannelDetails(
                    channel_id="c1",
                    name="Support",
                    purpose="Customer questions",
                    topic="On call: Ada",
                    is_private=False,
                )
            ),
            "get_channel_info",
        )

        assert answer.splitlines() == [
            "Channel: Support",
            "Purpose: Customer questions",
            "Topic: On call: Ada",
            "Visibility: open",
        ]

    async def test_a_member_without_a_name_is_still_a_member(self):
        """Every platform leaves some of these blank; none of them is a hole."""
        answer = await call(
            FakeDirectory(
                members=[
                    ChannelMember(user_id="u1", username="ada", display_name="Ada L", role="admin"),
                    ChannelMember(user_id="u2"),
                    ChannelMember(user_id="u3", username="helper", is_bot=True),
                ]
            ),
            "list_channel_members",
        )

        assert answer.splitlines() == [
            "- Ada L (ada, admin)",
            "- u2",
            "- helper (helper, bot)",
        ]

    async def test_history_comes_back_as_a_conversation(self):
        answer = await call(
            FakeDirectory(
                history=[
                    ChannelPost(
                        author="ada",
                        text="ship it",
                        posted_at=datetime(2026, 8, 9, 14, 30, tzinfo=UTC),
                    ),
                    ChannelPost(author="bob", text="done"),
                ]
            ),
            "read_channel_history",
        )

        assert answer.splitlines() == ["[2026-08-09T14:30+00:00] ada: ship it", "bob: done"]

    async def test_a_search_result_carries_the_id_a_reply_can_link(self):
        answer = await call(
            FakeDirectory(
                search=[
                    ChannelSummary(channel_id="c9", name="billing", purpose="Invoices"),
                    ChannelSummary(channel_id="c8", name="billing-eu"),
                ]
            ),
            "search_channels",
            query="billing",
        )

        assert answer.splitlines() == ["- billing (c9) - Invoices", "- billing-eu (c8)"]

    @pytest.mark.parametrize(
        ("tool", "answers", "kwargs"),
        [
            ("list_channel_members", {"members": []}, {}),
            ("search_channels", {"search": []}, {"query": "billing"}),
            ("read_channel_history", {"history": []}, {}),
        ],
    )
    async def test_an_empty_answer_says_so_rather_than_returning_nothing(
        self, tool: str, answers: dict[str, Any], kwargs: dict[str, Any]
    ):
        """An empty string reads to a model as a tool that failed."""
        assert await call(FakeDirectory(**answers), tool, **kwargs) == "Nothing came back."


class TestHowMuchOneCallMayBringBack:
    async def test_the_agents_default_applies_when_the_model_names_no_number(self):
        directory = FakeDirectory(members=[])
        await call(directory, "list_channel_members", default_limit=7)

        assert directory.limits == [7]

    async def test_the_model_cannot_ask_for_more_than_a_reply_can_carry(self):
        """ "All of them" is what a model asks for, and it is a turn's whole budget."""
        directory = FakeDirectory(history=[])
        await call(directory, "read_channel_history", limit=10_000)

        assert directory.limits == [200]

    async def test_a_nonsense_limit_still_fetches_something(self):
        directory = FakeDirectory(members=[])
        await call(directory, "list_channel_members", limit=0)

        assert directory.limits == [20]


class TestWhatHappensWhenTheChannelCannotAnswer:
    @pytest.mark.parametrize(
        ("tool", "kwargs"),
        [
            ("get_channel_info", {}),
            ("list_channel_members", {}),
            ("search_channels", {"query": "billing"}),
            ("read_channel_history", {}),
        ],
    )
    async def test_a_platform_that_cannot_answer_says_so_without_failing_the_run(
        self, tool: str, kwargs: dict[str, Any]
    ):
        """Telegram has no channel search. That is an answer, not an exception."""
        refusal = ChannelDirectoryUnsupported("telegram has no channel search for a bot.")
        directory = FakeDirectory(details=refusal, members=refusal, search=refusal, history=refusal)

        assert await call(directory, tool, **kwargs) == str(refusal)

    @pytest.mark.parametrize(
        ("tool", "kwargs"),
        [
            ("get_channel_info", {}),
            ("list_channel_members", {}),
            ("search_channels", {"query": "billing"}),
            ("read_channel_history", {}),
        ],
    )
    async def test_a_providers_own_error_never_reaches_the_model(
        self, tool: str, kwargs: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """The model quotes what it is given into a public channel.

        A Mattermost client puts the failing request URL in its message, and that
        URL is somebody's own server with a token in the query string. So the
        refusal names what the reader can act on and the client's text stays in
        the log line beside it.
        """
        boom = RuntimeError("401 for https://mm.acme.internal/api/v4/channels/c1?token=hunter2")
        directory = FakeDirectory(details=boom, members=boom, search=boom, history=boom)

        answer = await call(directory, tool, **kwargs)

        assert "acme.internal" not in answer
        assert "member of this channel" in answer
        assert "acme.internal" in caplog.text


class TestWhereTheCapabilityAppears:
    def test_a_run_outside_a_channel_gets_no_channel_tools(self):
        """Four tools that can only answer "there is no channel here" are worse
        than none: the model keeps calling them."""
        definition = get("channel_tools")
        blob = {"tools": sorted(definition.tool_ids)}

        assert (
            definition.builder(
                CapabilityBuildContext(
                    binding=CapabilityBinding(capability_id="channel_tools", config=blob),
                    config=definition.validate_config(blob),
                    resources={},
                )
            )
            is None
        )

    def test_it_is_not_offered_in_the_toolbox(self):
        """An agent on two Mattermost servers has two answers to "may it read
        what was said here", and a switch in the spec has one."""
        assert get("channel_tools").selectable is False

    def test_a_binding_that_granted_nothing_gets_no_tools(self):
        """A binding starts empty, and empty means the agent gets none of these.

        The other half of the same decision: the capability is per bound bot, so
        "in a channel" is not the same question as "allowed to ask about it".
        """
        assert (
            build_capabilities(
                [CapabilityBinding(capability_id="channel_tools", config={"tools": []})],
                resources={CHANNEL_DIRECTORY_RESOURCE: FakeDirectory()},
            )
            == []
        )

    def test_a_channel_run_gets_what_its_binding_granted_and_nothing_else(self):
        built = build_capabilities(
            [
                CapabilityBinding(
                    capability_id="channel_tools",
                    config={"tools": ["get_channel_info"], "default_limit": 5},
                )
            ],
            resources={CHANNEL_DIRECTORY_RESOURCE: FakeDirectory()},
        )

        assert isinstance(built[0], ChannelTools)
        assert built[0].default_limit == 5
        assert built[0].tools == frozenset({"get_channel_info"})

    async def test_a_tool_this_binding_did_not_grant_is_not_offered_at_all(self):
        """Not offered rather than offered-and-refusing.

        The model reads a tool's description before it reads its answer, so a
        tool it must not call is a step spent discovering it must not call it -
        and on a customer Slack, `read_channel_history` is exactly the one an
        operator switched off.
        """
        built = toolset(FakeDirectory(), tools={"get_channel_info"})

        assert sorted(await built.get_tools(_run_context())) == ["get_channel_info"]

    def test_the_toolset_is_built_once_per_agent(self):
        """A second toolset would be a second set of tool objects for one agent."""
        capability: ChannelTools[Any] = ChannelTools(directory=FakeDirectory(), tools=ALL_TOOLS)

        assert capability.get_toolset() is capability.get_toolset()

    def test_the_config_refuses_a_limit_no_reply_could_carry(self):
        with pytest.raises(ValueError, match="less than or equal to 200"):
            ChannelToolsConfig(default_limit=5_000)


class TestWhatEachPlatformCanActuallyAnswer:
    """`PLATFORM_TOOLS` is what the Builder offers, so it has to be true.

    Declared rather than derived - the exposure service validates against it
    without an adapter registered - which is exactly why it needs a test in both
    directions. A row for a method nobody implemented is a checkbox that grants
    a tool which always refuses; an implementation with no row is a tool nobody
    can reach.
    """

    @pytest.mark.parametrize(
        ("platform", "adapter"),
        [
            ("slack", SlackAdapter),
            ("telegram", TelegramAdapter),
            ("mattermost", MattermostAdapter),
        ],
    )
    def test_the_offered_list_matches_what_the_adapter_implements(
        self, platform: str, adapter: type[ChannelAdapter]
    ):
        assert set(PLATFORM_TOOLS[platform]) == supported_tools(adapter)

    def test_telegram_offers_neither_search_nor_history(self):
        """Named rather than only computed: Telegram gives a bot no directory of
        chats and no way to read messages it was not sent, and a future adapter
        change that appeared to add them should be read twice."""
        assert set(PLATFORM_TOOLS["telegram"]) == {"get_channel_info", "list_channel_members"}

    def test_every_registered_tool_has_a_method_that_would_answer_it(self):
        """A fifth tool cannot be added without saying what implements it."""
        assert set(TOOL_METHODS) == set(get("channel_tools").tool_ids)


class TestTheBoundDirectory:
    """The channel is decided before the agent is built, and stays decided."""

    def _adapter(self) -> Any:
        adapter = MagicMock(spec=ChannelAdapter)
        adapter.channel_details = AsyncMock(return_value=ChannelDetails(channel_id="c1", name="x"))
        adapter.channel_members = AsyncMock(return_value=[])
        adapter.search_channels = AsyncMock(return_value=[])
        adapter.channel_history = AsyncMock(return_value=[])
        return adapter

    async def test_every_call_carries_the_channel_the_message_arrived_in(self):
        adapter = self._adapter()
        directory = BoundChannelDirectory(
            adapter=adapter, bot_token="tok", channel_id="c1", api_base_url="https://mm.example"
        )

        await directory.details()
        await directory.members(limit=3)
        await directory.search("billing", limit=3)
        await directory.history(limit=3)

        for mock in (
            adapter.channel_details,
            adapter.channel_members,
            adapter.search_channels,
            adapter.channel_history,
        ):
            assert mock.await_args.args == ("tok", "c1")
            assert mock.await_args.kwargs["api_base_url"] == "https://mm.example"

        assert adapter.search_channels.await_args.kwargs["query"] == "billing"

    async def test_an_adapter_that_does_not_implement_one_refuses_by_default(self):
        """A new adapter is correct on the day it is written, and says what it
        cannot do rather than answering an empty list."""

        class Bare(ChannelAdapter):
            platform = "carrier-pigeon"

            async def send_message(self, bot_token: str, msg: Any) -> None: ...
            async def start_polling(self, bot_id: str, bot_token: str) -> None: ...
            async def stop_polling(self, bot_id: str) -> None: ...
            async def register_webhook(
                self, bot_token: str, url: str, secret: str | None
            ) -> bool: ...
            async def delete_webhook(self, bot_token: str) -> bool: ...
            def verify_webhook_signature(
                self, headers: dict[str, str], secret: str, body: str | None = None
            ) -> bool: ...
            def parse_incoming(self, raw_payload: dict[str, Any], bot_id: str) -> None: ...

        directory = BoundChannelDirectory(adapter=Bare(), bot_token="tok", channel_id="c1")

        for awaitable in (
            directory.details(),
            directory.members(limit=1),
            directory.search("x", limit=1),
            directory.history(limit=1),
        ):
            with pytest.raises(ChannelDirectoryUnsupported, match="carrier-pigeon"):
                await awaitable
