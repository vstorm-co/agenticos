"""Channel previews follow runtime events, including renamed and nested tools."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.test import TestModel

from app.agents.browser_events import BrowserEvent
from app.agents.deps import AgentDeps
from app.services.channels.live_reply import channel_stream

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("tool_name", ["computer_screenshot", "browser_open", "renamed_browser"])
@pytest.mark.parametrize("preview_available", [True, False])
@pytest.mark.parametrize("has_observer", [True, False])
async def test_channel_tools_deliver_authenticated_preview_links_from_open_events(
    tool_name: str, preview_available: bool, has_observer: bool
) -> None:
    run_id = uuid4()
    original = AsyncMock(return_value=False)
    observer = original if has_observer else None
    deps = AgentDeps(run_id=run_id, organization_id=uuid4(), browser_events=observer)
    reply = AsyncMock()
    events = [
        BrowserEvent(kind="browser_opened", call_id="window-1", step=0, run_id=str(run_id)),
        BrowserEvent(kind="browser_frame", call_id="window-1", step=1, image="PRIVATE-SCREEN"),
        BrowserEvent(kind="browser_finished", call_id="window-1", step=1, outcome="done"),
    ]

    async def screen(ctx: RunContext[AgentDeps]) -> str:
        assert ctx.deps.browser_events is not None
        for event in events:
            assert await ctx.deps.browser_events(event) is False
        return "Finished"

    agent = Agent(TestModel(), deps_type=AgentDeps)
    agent.tool(screen, name=tool_name)
    with patch(
        "app.services.channels.live_reply.live_browse.available", return_value=preview_available
    ):
        async with agent.iter("Look at the page", deps=deps) as run:
            await channel_stream(reply)(run)

    links = [source.url for call in reply.step.await_args_list for source in call.args[0].sources]
    if preview_available:
        assert any(f"/browse/{run_id}/window-1" in url for url in links)
    else:
        assert links == []
    assert "PRIVATE-SCREEN" not in str(reply.mock_calls)
    assert [call.args[0] for call in original.await_args_list] == (events if has_observer else [])
    assert deps.browser_events is observer


async def test_final_answer_retains_authenticated_views_after_stream_replacement() -> None:
    from app.services.channels.live_reply import with_preview_links

    run_id = uuid4()
    url = f"https://console.example/browse/{run_id}/window"
    with patch(
        "app.services.channels.live_reply.live_browse.view_links", AsyncMock(return_value=(url,))
    ):
        answer = await with_preview_links("Finished the work.", run_id)
        assert "Finished the work." in answer
        assert f"[Live view (sign-in required)]({url})" in answer
        assert await with_preview_links(answer, run_id) == answer
        assert await with_preview_links("", run_id) == ""


async def test_resumed_channel_delivery_carries_the_authenticated_preview() -> None:
    from unittest.mock import MagicMock

    from app.db.models.agent_run import AgentRun
    from app.db.models.channel_bot import ChannelBot
    from app.services.agent_runner import RunSegment
    from app.services.channels.prompts import ChannelPrompts

    run_id = uuid4()
    run = MagicMock(spec=AgentRun, id=run_id, conversation_id=uuid4())
    bot = MagicMock(spec=ChannelBot, id=uuid4(), organization_id=uuid4(), api_base_url=None)
    adapter = MagicMock(send_message=AsyncMock())
    url = f"https://console.example/browse/{run_id}/window"
    with (
        patch("app.services.channels.prompts.drawn_picture", AsyncMock(return_value=None)),
        patch("app.services.channels.prompts.get_adapter", return_value=adapter),
        patch("app.services.channels.prompts.unseal_bot_token", return_value="secret"),
        patch(
            "app.services.channels.live_reply.live_browse.view_links",
            AsyncMock(return_value=(url,)),
        ),
    ):
        await ChannelPrompts(MagicMock())._send_segment(
            bot,
            "mattermost",
            "room:thread",
            RunSegment(output="Completed after approval.", run=run, tool_calls=[], settled={}),
        )
    message = adapter.send_message.await_args.args[1]
    assert message.platform_chat_id == "room:thread"
    assert "Completed after approval." in message.text
    assert url in message.text
