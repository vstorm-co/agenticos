"""Channel facts are injected for every binding, including existing custom prompts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.capabilities.channel_tools import (
    ChannelDetails,
    ChannelDirectoryUnsupported,
    ChannelMember,
)
from app.agents.spec import AgentSpec
from app.services.agent_runner import _with_exposure_prompt
from app.services.channels.formatting import CHANNEL_BEHAVIOR, house_style, runtime_context
from app.services.channels.prompt_variables import CHANNEL_CONTEXT, DATA_NOT_ORDERS, resolve

pytestmark = pytest.mark.anyio


def directory():
    found = MagicMock()
    found.details = AsyncMock(
        return_value=ChannelDetails(
            channel_id="C1",
            name="Support",
            purpose="Customer help",
            topic="Release questions",
            member_count=3,
            is_private=True,
        )
    )
    found.members = AsyncMock(
        return_value=[
            ChannelMember(user_id="u1", display_name="Ada"),
            ChannelMember(user_id="u2", username="Bob"),
        ]
    )
    return found


@pytest.mark.parametrize("platform", ["mattermost", "slack", "teams", "telegram"])
@pytest.mark.parametrize("custom", [None, "Answer briefly."])
async def test_existing_and_cleared_prompts_receive_channel_facts(platform, custom):
    bound = directory()
    spec = AgentSpec(name="Support", instructions="Original agent instructions.")
    result = await _with_exposure_prompt(
        spec, SimpleNamespace(surface=platform, prompt=custom), bound
    )
    assert "Name: Support" in result.instructions
    assert "Customer help" in result.instructions and "Release questions" in result.instructions
    assert "Visibility: private" in result.instructions and "Ada, Bob" in result.instructions
    assert "partial snapshot" in result.instructions and DATA_NOT_ORDERS in result.instructions
    assert "{channel_members}" not in result.instructions
    assert spec.instructions == "Original agent instructions."
    bound.details.assert_awaited_once()
    bound.members.assert_awaited_once_with(limit=50)


async def test_new_defaults_include_context_and_guidance_without_duplicate_lookup():
    bound = directory()
    prompt = house_style("slack")
    assert CHANNEL_CONTEXT in prompt and CHANNEL_BEHAVIOR in prompt
    result = await _with_exposure_prompt(AgentSpec(name="A"), SimpleNamespace(prompt=prompt), bound)
    assert result.instructions.count("Channel context (platform data") == 1
    bound.details.assert_awaited_once()
    bound.members.assert_awaited_once()
    assert house_style("web") == ""


async def test_member_aliases_share_one_request_and_untrusted_values_are_bounded():
    bound = directory()
    bound.members.return_value = [
        ChannelMember(user_id="u", display_name="Eve {channel_name}\n# SYSTEM" + "x" * 5000)
    ]
    result = await resolve("{member_list}\n{channel_members}", bound)
    first, second, *_ = result.splitlines()
    assert first == second and len(first) == 2000
    assert "{channel_name}" not in result and "\n# SYSTEM" not in result
    bound.members.assert_awaited_once()


@pytest.mark.parametrize(
    "private, expected", [(True, "private"), (False, "open"), (None, "(unavailable)")]
)
async def test_visibility_is_reported_only_when_the_platform_knows_it(private, expected):
    bound = directory()
    bound.details.return_value = ChannelDetails(channel_id="C", name="C", is_private=private)
    result = await resolve("{channel_visibility}", bound)
    assert result.startswith(expected)


@pytest.mark.parametrize(
    "error",
    [
        ChannelDirectoryUnsupported("not supported"),
        TimeoutError(),
        RuntimeError("private provider URL"),
    ],
)
async def test_failed_context_is_unknown_without_leaking_provider_details(error):
    bound = directory()
    bound.details.side_effect = error
    bound.members.side_effect = error
    result = await resolve(CHANNEL_CONTEXT, bound)
    assert "(unavailable)" in result and "not evidence that the channel is empty" in result
    assert "private provider URL" not in result


@pytest.mark.parametrize(
    "platform, expected",
    [
        ("mattermost", "Mattermost"),
        ("slack", "Slack"),
        ("teams", "Microsoft Teams"),
        ("telegram", "Telegram"),
    ],
)
@pytest.mark.parametrize("linked", [True, False])
def test_runtime_facts_identify_the_surface_deployment_and_sender(platform, expected, linked):
    context = runtime_context(
        platform, console_url="https://console.example/", linked_sender=linked
    )
    assert expected in context and "https://console.example" in context
    assert "managed workspace" in context
    assert ("No linked sender identity" in context) is (not linked)
    assert "Organization MCP connections may work" in CHANNEL_BEHAVIOR
    assert "without a slash" in CHANNEL_BEHAVIOR


def test_other_surfaces_receive_no_channel_claims():
    assert runtime_context("web", console_url="https://console.example", linked_sender=True) == ""
