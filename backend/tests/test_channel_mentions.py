"""Tests for routing a channel message to the agent it names.

Two things are worth proving here and they are quite different. The parser is
pure and its edge cases are where a bot starts answering messages nobody
addressed to it. The router is a boundary: what it must not do is let a handle
typed in a public Slack channel become a way to reach an agent, an organization
or an account the sender is not entitled to.

Every test that gets as far as running an agent has to bind one now. A handle
used to resolve against every published agent in the bot's organization, so one
Slack app was a door onto all of them; ``_bound`` is what that door being closed
by default looks like from a test.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import OrgRoleName
from app.db.models.agent_run import RunSurface
from app.services.channels.mentions import (
    ChannelAgentRouter,
    UnaddressedMessage,
    parse_mention,
)

pytestmark = pytest.mark.anyio

_BOT_ID = uuid.uuid4()


def _bound(*, is_active: bool = True) -> AsyncMock:
    """An exposure lookup that says this agent answers on this bot."""
    return AsyncMock(return_value=MagicMock(is_active=is_active))


class TestParseMention:
    @pytest.mark.parametrize(
        ("text", "slug", "prompt"),
        [
            ("@support what is the refund window", "support", "what is the refund window"),
            ("  @support   spaced out  ", "support", "spaced out"),
            ("@support: with a colon", "support", "with a colon"),
            ("@support, with a comma", "support", "with a comma"),
            ("@billing-eu multi word handle", "billing-eu", "multi word handle"),
            ("@support first line\nsecond line", "support", "first line\nsecond line"),
        ],
    )
    def test_a_handle_and_a_question_split_cleanly(self, text, slug, prompt):
        mention = parse_mention(text)

        assert mention is not None
        assert (mention.slug, mention.prompt) == (slug, prompt)

    @pytest.mark.parametrize(
        "text",
        [
            "no handle at all",
            "ask @support about it",  # mid-sentence: talking about, not to
            "@support",  # a greeting, and a billed run to answer it
            "@support   ",
            "@",
            "@-leading-dash hello",
            "@Support upper case is not a slug",
            "",
        ],
    )
    def test_anything_that_is_not_an_address_is_left_alone(self, text):
        assert parse_mention(text) is None

    def test_a_handle_longer_than_a_slug_can_be_is_not_one(self):
        """Slugs are capped at 64 characters, so nothing longer can exist."""
        assert parse_mention("@" + "a" * 65 + " hello") is None


class TestAnswer:
    async def test_an_unaddressed_message_is_handed_back_to_the_caller(self):
        """The bot's own assistant still owns everything not addressed to an agent."""
        with pytest.raises(UnaddressedMessage):
            await ChannelAgentRouter(MagicMock()).answer(
                "hello there",
                platform="slack",
                organization_id=uuid.uuid4(),
                bot_id=_BOT_ID,
                user_id=uuid.uuid4(),
            )

    async def test_an_unlinked_sender_is_asked_to_link_before_anything_is_looked_up(self):
        """No membership, no role — and a run with no role has no checks."""
        db = MagicMock()
        with (
            patch("app.services.channels.mentions.agent_repo") as agents,
            pytest.raises(AuthorizationError) as refused,
        ):
            await ChannelAgentRouter(db).answer(
                "@support hello",
                platform="slack",
                organization_id=uuid.uuid4(),
                bot_id=_BOT_ID,
                user_id=None,
            )

        assert "/link" in refused.value.message
        agents.get_by_slug.assert_not_called()

    async def test_a_linked_sender_who_left_the_organization_is_refused_the_same_way(self):
        """Their account exists; their standing in this workspace does not."""
        with patch("app.services.channels.mentions.member_repo") as members:
            members.get = AsyncMock(return_value=None)

            with pytest.raises(AuthorizationError) as refused:
                await ChannelAgentRouter(MagicMock()).answer(
                    "@support hello",
                    platform="slack",
                    organization_id=uuid.uuid4(),
                    bot_id=_BOT_ID,
                    user_id=uuid.uuid4(),
                )

        assert "/link" in refused.value.message

    async def test_an_unknown_handle_is_reported_as_missing(self):
        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
        ):
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
            agents.get_by_slug = AsyncMock(return_value=None)

            with pytest.raises(NotFoundError) as refused:
                await ChannelAgentRouter(MagicMock()).answer(
                    "@nobody hello",
                    platform="slack",
                    organization_id=uuid.uuid4(),
                    bot_id=_BOT_ID,
                    user_id=uuid.uuid4(),
                )

        assert refused.value.details == {"slug": "nobody"}
        # A handle that names nothing must not be distinguishable from one naming
        # an agent that is merely not bound here — the binding is never consulted.
        exposures.get_for_bot.assert_not_called()

    async def test_an_agent_nobody_bound_to_this_bot_is_refused_with_the_fix(self):
        """The change that closed the door has to explain itself in the channel.

        A bot that used to answer and now does not is the common case for this
        message, and answering it with the same line a typo gets would leave
        somebody debugging a silent bot from a changelog.
        """
        agent_id = uuid.uuid4()

        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
            agents.get_by_slug = AsyncMock(return_value=MagicMock(id=agent_id))
            exposures.get_for_bot = AsyncMock(return_value=None)
            runner_cls.return_value.execute = AsyncMock()

            with pytest.raises(BadRequestError) as refused:
                await ChannelAgentRouter(MagicMock()).answer(
                    "@support hello",
                    platform="slack",
                    organization_id=uuid.uuid4(),
                    bot_id=_BOT_ID,
                    user_id=uuid.uuid4(),
                )

        assert "not available on this bot" in refused.value.message
        assert "Where this agent is available" in refused.value.message
        assert refused.value.details["agent_id"] == str(agent_id)
        runner_cls.return_value.execute.assert_not_called()

    async def test_a_paused_binding_answers_nothing(self):
        """Pausing is how a binding is switched off without losing who made it."""
        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
            agents.get_by_slug = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            exposures.get_for_bot = _bound(is_active=False)
            runner_cls.return_value.execute = AsyncMock()

            with pytest.raises(BadRequestError):
                await ChannelAgentRouter(MagicMock()).answer(
                    "@support hello",
                    platform="slack",
                    organization_id=uuid.uuid4(),
                    bot_id=_BOT_ID,
                    user_id=uuid.uuid4(),
                )

        runner_cls.return_value.execute.assert_not_called()

    async def test_the_binding_is_looked_up_for_the_bot_the_message_arrived_on(self):
        """One organization's bot must not inherit another bot's bindings.

        The organization is where the handle is looked up; the bot is what makes
        it reachable. Resolving the binding against anything but the bot in hand
        would restore the hole this replaced, one workspace wider.
        """
        agent_id = uuid.uuid4()

        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
            agents.get_by_slug = AsyncMock(return_value=MagicMock(id=agent_id))
            exposures.get_for_bot = _bound()
            runner_cls.return_value.execute = AsyncMock(return_value=("hi", MagicMock()))

            await ChannelAgentRouter(MagicMock()).answer(
                "@support hello",
                platform="slack",
                organization_id=uuid.uuid4(),
                bot_id=_BOT_ID,
                user_id=uuid.uuid4(),
            )

        assert exposures.get_for_bot.call_args.kwargs == {
            "agent_id": agent_id,
            "channel_bot_id": _BOT_ID,
        }

    async def test_the_slug_is_resolved_inside_the_bots_organization_only(self):
        """One workspace's handle must not reach another workspace's agent."""
        organization_id = uuid.uuid4()
        agent = MagicMock(id=uuid.uuid4())

        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
            agents.get_by_slug = AsyncMock(return_value=agent)
            exposures.get_for_bot = _bound()
            runner_cls.return_value.execute = AsyncMock(return_value=("hi", MagicMock()))

            await ChannelAgentRouter(MagicMock()).answer(
                "@support hello",
                platform="slack",
                organization_id=organization_id,
                bot_id=_BOT_ID,
                user_id=uuid.uuid4(),
            )

        assert agents.get_by_slug.call_args.kwargs["organization_id"] == organization_id

    async def test_the_run_carries_the_senders_own_role(self):
        """Not the bot's, and not the owner's: the person who typed the handle."""
        user_id = uuid.uuid4()
        organization_id = uuid.uuid4()

        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.VIEWER))
            agents.get_by_slug = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            exposures.get_for_bot = _bound()
            execute = AsyncMock(return_value=("hi", MagicMock()))
            runner_cls.return_value.execute = execute

            await ChannelAgentRouter(MagicMock()).answer(
                "@support hello",
                platform="slack",
                organization_id=organization_id,
                bot_id=_BOT_ID,
                user_id=user_id,
            )

        ctx = execute.call_args.args[0]
        assert (ctx.user_id, ctx.organization_id, ctx.role) == (
            user_id,
            organization_id,
            OrgRoleName.VIEWER,
        )
        assert ctx.is_app_admin is False

    @pytest.mark.parametrize(
        ("platform", "surface"),
        [
            ("slack", RunSurface.SLACK),
            ("telegram", RunSurface.TELEGRAM),
            ("something-new", RunSurface.API),
        ],
    )
    async def test_the_run_records_where_it_came_from(self, platform, surface):
        """An unknown platform is recorded as API rather than guessed at."""
        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
            agents.get_by_slug = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            exposures.get_for_bot = _bound()
            execute = AsyncMock(return_value=("hi", MagicMock()))
            runner_cls.return_value.execute = execute

            await ChannelAgentRouter(MagicMock()).answer(
                "@support hello",
                platform=platform,
                organization_id=uuid.uuid4(),
                bot_id=_BOT_ID,
                user_id=uuid.uuid4(),
            )

        assert execute.call_args.kwargs["surface"] is surface

    async def test_only_the_words_after_the_handle_reach_the_agent(self):
        """The handle is addressing, not part of the question."""
        conversation_id = uuid.uuid4()

        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
            agents.get_by_slug = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            exposures.get_for_bot = _bound()
            execute = AsyncMock(return_value=("42 days", MagicMock()))
            runner_cls.return_value.execute = execute

            answer = await ChannelAgentRouter(MagicMock()).answer(
                "@support what is the refund window",
                platform="slack",
                organization_id=uuid.uuid4(),
                bot_id=_BOT_ID,
                user_id=uuid.uuid4(),
                conversation_id=conversation_id,
            )

        assert execute.call_args.args[2] == "what is the refund window"
        assert execute.call_args.kwargs["conversation_id"] == conversation_id
        assert answer == "42 days"
