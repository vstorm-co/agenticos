"""Tests for routing a channel message to the agent it names.

Two things are worth proving here and they are quite different. The parser is
pure and its edge cases are where a bot starts answering messages nobody
addressed to it. The router is a boundary: what it must not do is let a handle
typed in a public Slack channel become a way to reach an agent, an organization
or an account the sender is not entitled to.

Every test that gets as far as running an agent has to bind one now. A handle
used to resolve against every published agent in the bot's organization, so one
Slack app was a door onto all of them; `_bound` is what that door being closed
by default looks like from a test.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent_run import RunSurface
from app.services.channels.base import ROOM_HANDLES, channel_key, split_thread, thread_key
from app.services.channels.mentions import (
    ChannelAgentRouter,
    UnaddressedMessage,
    parse_mention,
)
from app.services.usage_report import UsageReport

pytestmark = pytest.mark.anyio


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


_BOT_ID = uuid.uuid4()


def _bound(*, is_active: bool = True) -> AsyncMock:
    """An exposure lookup that says this agent answers on this bot."""
    return AsyncMock(return_value=MagicMock(is_active=is_active))


class TestTheChannelAWorkspaceSharesAcross:
    """`channel` scope keys on the chat with the thread stripped.

    Slack folds `thread_ts` into `platform_chat_id`, so the raw id identifies a
    *thread*. Keying a channel-scoped workspace on it would give one workspace
    per thread - which is what `conversation` scope already does, and under a
    container backend it is fifty containers in a busy channel.
    """

    @pytest.mark.parametrize(
        ("platform_chat_id", "expected"),
        [
            ("C0123456:1717171717.001", "C0123456"),
            ("C0123456", "C0123456"),
            ("-1001234567890", "-1001234567890"),
        ],
    )
    def test_a_thread_resolves_to_the_channel_that_holds_it(
        self, platform_chat_id: str, expected: str
    ):
        assert channel_key(platform_chat_id) == expected

    def test_two_threads_in_one_channel_agree_on_the_key(self):
        first = channel_key("C0123456:1717171717.001")
        second = channel_key("C0123456:1818181818.002")

        assert first == second


class TestWhatTheBotSaysAboutWhatItCost:
    """The footer, and the fact that it never costs an answer.

    A bot that stops answering because its organization hit a cap looks broken,
    so the report exists - but it hangs off a reply somebody is already waiting
    for, and an accounting read that failed must not take that reply with it.
    """

    async def test_a_failed_report_returns_the_answer_unchanged(self):
        router = ChannelAgentRouter(MagicMock())
        router.usage = MagicMock(for_run=AsyncMock(side_effect=RuntimeError("no")))
        router.runner = MagicMock(monthly_spend=AsyncMock(return_value=None))

        answered = await router._with_usage(
            _ctx(), "here you go", MagicMock(id=uuid.uuid4()), usage_reporting=None, turn=1
        )

        assert answered == "here you go"

    async def test_an_empty_answer_stays_empty(self):
        """That is the parked-approval contract, and a footer under nothing would
        look like the reply."""
        router = ChannelAgentRouter(MagicMock())
        router.usage = MagicMock(
            for_run=AsyncMock(
                return_value=UsageReport(input_tokens=1, output_tokens=1, cost_usd=Decimal("0.01"))
            )
        )
        router.runner = MagicMock(monthly_spend=AsyncMock(return_value=None))
        router._budget = AsyncMock(return_value=None)

        assert (
            await router._with_usage(
                _ctx(), "", MagicMock(id=uuid.uuid4()), usage_reporting={"mode": "always"}, turn=1
            )
            == ""
        )

    async def test_always_puts_the_line_under_the_answer(self):
        router = ChannelAgentRouter(MagicMock())
        router.usage = MagicMock(
            for_run=AsyncMock(
                return_value=UsageReport(
                    input_tokens=1000, output_tokens=200, cost_usd=Decimal("0.02")
                )
            )
        )
        router.runner = MagicMock(monthly_spend=AsyncMock(return_value=None))
        router._budget = AsyncMock(return_value=None)

        answered = await router._with_usage(
            _ctx(),
            "here you go",
            MagicMock(id=uuid.uuid4()),
            usage_reporting={"mode": "always"},
            turn=1,
        )

        assert answered.startswith("here you go")
        assert "1,200 tokens" in answered

    async def test_off_records_it_and_says_nothing(self):
        router = ChannelAgentRouter(MagicMock())
        router.usage = MagicMock(
            for_run=AsyncMock(
                return_value=UsageReport(input_tokens=1, output_tokens=1, cost_usd=Decimal("0.01"))
            )
        )
        router.runner = MagicMock(monthly_spend=AsyncMock(return_value=None))
        router._budget = AsyncMock(return_value=None)

        answered = await router._with_usage(
            _ctx(),
            "here you go",
            MagicMock(id=uuid.uuid4()),
            usage_reporting={"mode": "off"},
            turn=1,
        )

        assert answered == "here you go"

    async def test_the_organizations_cap_is_what_it_compares_against(self):
        """An agent's own cap is its author's to raise; this one stops every agent
        at once, which is the one worth warning a channel about."""
        organization = MagicMock(monthly_budget_usd=Decimal("100"))
        db = MagicMock(get=AsyncMock(return_value=organization))
        router = ChannelAgentRouter(db)

        assert await router._budget(_ctx()) == Decimal("100")

    async def test_an_organization_that_vanished_has_no_cap(self):
        router = ChannelAgentRouter(MagicMock(get=AsyncMock(return_value=None)))

        assert await router._budget(_ctx()) is None


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

    @pytest.mark.parametrize("handle", sorted(ROOM_HANDLES))
    def test_a_handle_that_addresses_the_room_is_not_an_agent(self, handle):
        """`@channel deploying at five` matched the slug pattern, so it read as a
        mention of an agent called `channel`. And a channel-wide mention puts every
        member including the bot in the platform's own mention list, so the bot
        considered itself named and posted "No agent here answers to @channel" under
        every announcement - the interruption #634 exists to end.
        """
        assert parse_mention(f"@{handle} deploying at five") is None

    def test_a_handle_that_merely_starts_with_one_is_still_an_agent(self):
        """The set is exact, not a prefix: an agent may perfectly well be called
        `channel-bot` or `all-hands`."""
        mention = parse_mention("@channel-bot what is the refund window")

        assert mention is not None
        assert mention.slug == "channel-bot"


class TestAnswer:
    async def test_an_unaddressed_message_is_handed_back_to_the_caller(self):
        """The caller decides what no handle means - for a channel bot, the
        default-agent path in :meth:`answer_default`."""
        with pytest.raises(UnaddressedMessage):
            await ChannelAgentRouter(MagicMock()).answer(
                "hello there",
                platform="slack",
                organization_id=uuid.uuid4(),
                bot_id=_BOT_ID,
                user_id=uuid.uuid4(),
            )

    async def test_an_unlinked_sender_is_asked_to_link_before_anything_is_looked_up(self):
        """No membership, no role - and a run with no role has no checks."""
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
        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.access.member_repo", new=members),
            patch("app.services.access.member_repo", new=members),
        ):
            members.get_active = AsyncMock(return_value=None)

            with pytest.raises(AuthorizationError) as refused:
                await ChannelAgentRouter(MagicMock()).answer(
                    "@support hello",
                    platform="slack",
                    organization_id=uuid.uuid4(),
                    bot_id=_BOT_ID,
                    user_id=uuid.uuid4(),
                )

        assert "/link" in refused.value.message

    async def test_a_deactivated_linked_member_does_not_run_a_channel_turn_at_their_old_role(
        self,
    ):
        """Deactivating an account revokes its sessions but leaves its membership row
        and its chat-account link where they were. The plain read still answered
        with that row, so an offboarded Owner kept running turns from Slack at
        Owner - blocked everywhere they sign in, except here. The joined read is
        what says the account is gone; a DM then asks for a link, as it does for a
        stranger, and nothing runs."""
        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.OWNER))
            members.get_active = AsyncMock(return_value=None)

            with pytest.raises(AuthorizationError) as refused:
                await ChannelAgentRouter(MagicMock()).answer(
                    "@support delete every agent",
                    platform="slack",
                    organization_id=uuid.uuid4(),
                    bot_id=_BOT_ID,
                    user_id=uuid.uuid4(),
                )

        assert "/link" in refused.value.message
        agents.get_by_slug.assert_not_called()
        runner_cls.return_value.execute.assert_not_called()

    async def test_an_unknown_handle_is_reported_as_missing(self):
        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
        ):
            members.get_active = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
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
        # an agent that is merely not bound here - the binding is never consulted.
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
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get_active = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
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
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get_active = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
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
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get_active = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
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
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get_active = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
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
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get_active = AsyncMock(return_value=MagicMock(role=OrgRoleName.VIEWER))
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
            ("mattermost", RunSurface.MATTERMOST),
            ("something-new", RunSurface.API),
        ],
    )
    async def test_the_run_records_where_it_came_from(self, platform, surface):
        """An unknown platform is recorded as API rather than guessed at."""
        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get_active = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
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
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get_active = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
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
        assert answer.text == "42 days"


def _serving(*slugs: str) -> AsyncMock:
    """An exposure listing that says these agents actively answer on the bot."""
    return AsyncMock(
        return_value=[(MagicMock(), MagicMock(id=uuid.uuid4(), slug=slug)) for slug in slugs]
    )


class TestAnswerDefault:
    """A message naming no handle goes to the agent behind the bot.

    A bot serves exactly one - `uq_exposure_bot` - so this is the ordinary path
    and not a special case, and the only other state is a bot nobody has bound
    anything to. It answers as the *sender*, exactly like a mention.
    """

    async def test_a_bot_serving_no_agent_refuses_with_the_fix(self):
        with (
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            exposures.list_active_for_bot = _serving()
            runner_cls.return_value.execute = AsyncMock()

            with pytest.raises(BadRequestError) as refused:
                await ChannelAgentRouter(MagicMock()).answer_default(
                    "hello there",
                    platform="slack",
                    organization_id=uuid.uuid4(),
                    bot_id=_BOT_ID,
                    user_id=uuid.uuid4(),
                )

        assert "No agent is available on this bot" in refused.value.message
        assert "Where this agent is available" in refused.value.message
        runner_cls.return_value.execute.assert_not_called()

    async def test_an_unlinked_sender_is_refused_before_anything_runs(self):
        """The default path takes a subject exactly as a mention does."""
        with (
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            exposures.list_active_for_bot = _serving("support")
            runner_cls.return_value.execute = AsyncMock()

            with pytest.raises(AuthorizationError) as refused:
                await ChannelAgentRouter(MagicMock()).answer_default(
                    "hello there",
                    platform="slack",
                    organization_id=uuid.uuid4(),
                    bot_id=_BOT_ID,
                    user_id=None,
                )

        assert "/link" in refused.value.message
        runner_cls.return_value.execute.assert_not_called()

    async def test_the_only_exposed_agent_runs_the_whole_message_with_its_thread(self):
        """No handle to strip, so the prompt is the message; the history and the
        binding both travel with the run, or a cap set on the bot bounds nothing."""
        conversation_id = uuid.uuid4()
        history = [MagicMock()]
        exposure = MagicMock()
        agent = MagicMock(id=uuid.uuid4(), slug="support")

        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get_active = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
            exposures.list_active_for_bot = AsyncMock(return_value=[(exposure, agent)])
            execute = AsyncMock(return_value=("42 days", MagicMock()))
            runner_cls.return_value.execute = execute

            answer = await ChannelAgentRouter(MagicMock()).answer_default(
                "what is the refund window",
                platform="telegram",
                organization_id=uuid.uuid4(),
                bot_id=_BOT_ID,
                user_id=uuid.uuid4(),
                conversation_id=conversation_id,
                message_history=history,
            )

        assert execute.call_args.args[1] == agent.id
        assert execute.call_args.args[2] == "what is the refund window"
        assert execute.call_args.kwargs["surface"] is RunSurface.TELEGRAM
        assert execute.call_args.kwargs["conversation_id"] == conversation_id
        assert execute.call_args.kwargs["message_history"] is history
        assert execute.call_args.kwargs["exposure"] is exposure
        assert answer.text == "42 days"


def _standing(by_user: dict[uuid.UUID, MagicMock | None]):
    """A `member_repo.get_active` that knows who can still sign in: anybody not
    listed cannot - they left, or their account was deactivated."""

    async def get_active(db, *, organization_id, user_id):
        return by_user.get(user_id)

    return get_active


class TestWhatARoomRunsAs:
    """A channel admits somebody this platform cannot name (#639).

    A direct message is a conversation with a person and keeps asking for a
    linked account. A channel is a room: whoever could invite the bot chose the
    audience, so the turn runs under the *binding* - and what it may reach is
    the binding creator's role, never more.
    """

    @staticmethod
    def _binding(creator: uuid.UUID | None, organization_id: uuid.UUID) -> MagicMock:
        return MagicMock(created_by_user_id=creator, organization_id=organization_id)

    async def _ran_as(self, exposure: MagicMock, **kwargs) -> AuthContext:
        """The context a turn ran under, admitting an unnamed sender.

        `membership` is what `member_repo.get_active` answers with, so it stands for
        an account that is both still a member and still able to sign in: `None`
        covers having left *and* having been deactivated, which is the same answer
        for the same reason (`access.publisher_context`). `standing` (see
        `_standing`) replaces it when the sender and the creator must answer
        differently.

        `stale_row` is what the plain `get` would still answer with - the membership
        row a deactivation leaves behind. Nothing on this path may read it, so by
        default it raises.
        """
        agent = MagicMock(id=uuid.uuid4(), slug="support")
        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            membership = kwargs.pop("membership", None)
            stale_row = kwargs.pop("stale_row", None)
            members.get = (
                AsyncMock(return_value=stale_row)
                if stale_row is not None
                else AsyncMock(side_effect=AssertionError("the joined read decides this"))
            )
            standing = kwargs.pop("standing", None)
            if standing is not None:
                members.get_active = AsyncMock(side_effect=standing)
            else:
                members.get_active = AsyncMock(return_value=membership)
            exposures.list_active_for_bot = AsyncMock(return_value=[(exposure, agent)])
            execute = AsyncMock(return_value=("hello", MagicMock()))
            runner_cls.return_value.execute = execute

            await ChannelAgentRouter(MagicMock()).answer_default(
                "what is the refund window",
                platform="mattermost",
                organization_id=exposure.organization_id,
                bot_id=_BOT_ID,
                admit_unlinked=True,
                **kwargs,
            )

        return execute.call_args.args[0]

    async def test_a_sender_nobody_can_name_runs_under_the_binding_creator(self):
        organization_id, creator = uuid.uuid4(), uuid.uuid4()
        exposure = self._binding(creator, organization_id)

        ctx = await self._ran_as(
            exposure,
            user_id=None,
            membership=MagicMock(role=OrgRoleName.BUILDER),
        )

        assert ctx.user_id == creator
        assert ctx.role == OrgRoleName.BUILDER
        assert ctx.organization_id == organization_id

    async def test_a_creator_who_left_the_organization_drops_the_turn_to_viewer(self):
        """Their departure must not silently widen what a channel can reach."""
        exposure = self._binding(uuid.uuid4(), uuid.uuid4())

        ctx = await self._ran_as(exposure, user_id=None, membership=None)

        assert ctx.role == OrgRoleName.VIEWER

    async def test_the_creators_role_is_read_off_a_membership_that_can_sign_in(self):
        """Deactivation leaves the membership row in place, so the plain read kept a
        binding answering at its creator's Owner role after their account stopped
        being able to sign in at all. `get` here is the defect, so it raises."""
        exposure = self._binding(uuid.uuid4(), uuid.uuid4())
        agent = MagicMock(id=uuid.uuid4(), slug="support")

        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = AsyncMock(side_effect=AssertionError("the joined read decides this"))
            members.get_active = AsyncMock(return_value=None)
            exposures.list_active_for_bot = AsyncMock(return_value=[(exposure, agent)])
            execute = AsyncMock(return_value=("hello", MagicMock()))
            runner_cls.return_value.execute = execute

            await ChannelAgentRouter(MagicMock()).answer_default(
                "what is the refund window",
                platform="mattermost",
                organization_id=exposure.organization_id,
                bot_id=_BOT_ID,
                admit_unlinked=True,
                user_id=None,
            )

        assert execute.call_args.args[0].role == OrgRoleName.VIEWER

    async def test_a_binding_nobody_is_recorded_against_runs_as_viewer(self):
        """A row old enough to predate the column is not a row with an owner."""
        exposure = self._binding(None, uuid.uuid4())

        ctx = await self._ran_as(exposure, user_id=None)

        assert ctx.user_id is None
        assert ctx.role == OrgRoleName.VIEWER

    async def test_the_chat_account_is_recorded_even_though_it_is_not_the_subject(self):
        """Who asked, beside who it ran as - the two are different in a room."""
        identity_id, creator = uuid.uuid4(), uuid.uuid4()
        exposure = self._binding(creator, uuid.uuid4())

        ctx = await self._ran_as(
            exposure,
            user_id=None,
            channel_identity_id=identity_id,
            membership=MagicMock(role=OrgRoleName.MEMBER),
        )

        assert ctx.channel_identity_id == identity_id
        assert ctx.user_id == creator

    async def test_a_linked_member_in_a_room_still_runs_as_themselves(self):
        """Admitting strangers must not stop naming the people it can name."""
        user_id, identity_id = uuid.uuid4(), uuid.uuid4()
        exposure = self._binding(uuid.uuid4(), uuid.uuid4())

        ctx = await self._ran_as(
            exposure,
            user_id=user_id,
            channel_identity_id=identity_id,
            membership=MagicMock(role=OrgRoleName.OPERATOR),
        )

        assert ctx.user_id == user_id
        assert ctx.role == OrgRoleName.OPERATOR
        assert ctx.channel_identity_id == identity_id

    async def test_a_former_member_in_a_room_is_no_more_entitled_than_a_stranger(self):
        """An account that exists and a standing in this workspace are not the
        same thing, and only the second one carries a role."""
        creator, departed = uuid.uuid4(), uuid.uuid4()
        exposure = self._binding(creator, uuid.uuid4())

        ctx = await self._ran_as(
            exposure,
            user_id=departed,
            standing=_standing({creator: MagicMock(role=OrgRoleName.ADMIN)}),
        )

        assert ctx.user_id == creator, "the turn runs under the binding, not under them"
        assert ctx.role == OrgRoleName.ADMIN

    @pytest.mark.parametrize(
        ("creator_standing", "expected_role"),
        [
            (MagicMock(role=OrgRoleName.MEMBER), OrgRoleName.MEMBER),
            (None, OrgRoleName.VIEWER),
        ],
    )
    async def test_a_deactivated_member_in_a_room_runs_under_the_binding_not_at_their_old_role(
        self, creator_standing: MagicMock | None, expected_role: str
    ):
        """Offboarding leaves both the membership row and the chat account's link
        in place, so the plain read let a deactivated Owner keep speaking to the
        bot at Owner. `get` answering with that row is the defect; the joined read
        is what says they can no longer sign in, and a room then admits them as
        it admits anybody else - under whoever bound the agent."""
        creator, deactivated = uuid.uuid4(), uuid.uuid4()
        exposure = self._binding(creator, uuid.uuid4())

        ctx = await self._ran_as(
            exposure,
            user_id=deactivated,
            channel_identity_id=uuid.uuid4(),
            standing=_standing({creator: creator_standing}),
            stale_row=MagicMock(role=OrgRoleName.OWNER),
        )

        assert ctx.user_id == creator
        assert ctx.role == expected_role

    async def test_a_room_that_asks_for_a_link_refuses_instead(self):
        """`require_link` is the opt-out, and this is the layer that honours it:
        the caller passes what its policy decided."""
        with (
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            exposures.list_active_for_bot = _serving("support")
            runner_cls.return_value.execute = AsyncMock()

            with pytest.raises(AuthorizationError) as refused:
                await ChannelAgentRouter(MagicMock()).answer_default(
                    "hello there",
                    platform="mattermost",
                    organization_id=uuid.uuid4(),
                    bot_id=_BOT_ID,
                    user_id=None,
                    admit_unlinked=False,
                )

        assert "/link" in refused.value.message
        runner_cls.return_value.execute.assert_not_called()

    async def test_a_mention_in_a_room_runs_under_the_binding_too(self):
        """The `@handle` path and the ordinary one admit the same people."""
        creator = uuid.uuid4()
        exposure = self._binding(creator, uuid.uuid4())
        agent = MagicMock(id=uuid.uuid4(), slug="support")

        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_repo") as agents,
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get_active = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
            agents.get_by_slug = AsyncMock(return_value=agent)
            exposures.get_for_bot = AsyncMock(return_value=exposure)
            execute = AsyncMock(return_value=("hello", MagicMock()))
            runner_cls.return_value.execute = execute

            await ChannelAgentRouter(MagicMock()).answer(
                "@support hello",
                platform="mattermost",
                organization_id=exposure.organization_id,
                bot_id=_BOT_ID,
                user_id=None,
                admit_unlinked=True,
            )

        assert execute.call_args.args[0].user_id == creator


class TestTheThreadAConversationIsKeyedOn:
    """`thread_key` - the one place that decides, since #1339.

    A mention's reply opens a thread rooted at that message. Keyed on the bare
    channel, the mention and the thread were two conversations, so the agent
    answered and then had no memory of it one message later.
    """

    def test_a_message_already_in_a_thread_keys_on_that_thread(self):
        assert thread_key("c1", thread_id="root9", message_id="m2") == "c1:root9"

    def test_a_channel_message_keys_on_itself(self):
        """Because that is where the reply's thread will be rooted."""
        assert thread_key("c1", thread_id="", message_id="m1") == "c1:m1"

    def test_a_direct_message_keys_on_itself_too(self):
        """It used to key on the chat, which made a DM one conversation for ever:
        it never rolls over, so it walks past the context window in days and every
        turn pays for the whole history. A thread per question is a per-topic
        context instead - and the cost is that a new message at the bottom of the
        DM starts fresh, so continuing means replying inside the thread.
        """
        assert thread_key("c1", thread_id="", message_id="m1") == "c1:m1"

    def test_a_second_direct_message_is_a_second_conversation(self):
        """The point of the change, stated as the thing somebody would notice."""
        first = thread_key("c1", thread_id="", message_id="m1")
        second = thread_key("c1", thread_id="", message_id="m2")

        assert first != second

    def test_a_reply_inside_that_thread_rejoins_the_first(self):
        """And the other half: the conversation continues where it was opened."""
        opened = thread_key("c1", thread_id="", message_id="m1")

        assert thread_key("c1", thread_id="m1", message_id="m7") == opened

    def test_a_platform_that_sends_no_message_id_keys_on_the_chat(self):
        """Better one conversation per chat than one per unidentifiable turn.
        Telegram is the shape that needs it, and has no threads to key on."""
        assert thread_key("c1", thread_id="", message_id=None) == "c1"

    def test_the_channel_is_still_recoverable_from_the_key(self):
        """Everything scoped to the channel - membership, a shared workspace -
        reads `channel_key`, which must keep working over the new shape."""
        key = thread_key("c1", thread_id="", message_id="m1")

        assert channel_key(key) == "c1"
        assert split_thread(key) == ("c1", "m1")


class TestWhoseAccountsAPersonalBindingSpeaksThrough:
    """`acts_for_sender` is what lets a personal MCP binding reach the sender's own
    connections, and it is this message's author or nobody. A room does not make
    the first speaker's account everybody's, and an unlinked sender has none to
    lend - the turn then runs under the binding's publisher, whose own accounts
    must not be reached for either.
    """

    @staticmethod
    def _patched():
        return (
            patch("app.services.channels.mentions.member_repo"),
            patch("app.services.channels.mentions.agent_repo"),
            patch("app.services.channels.mentions.agent_exposure_repo"),
            patch("app.services.channels.mentions.AgentRunnerService"),
        )

    async def _mentioned(self, *, user_id: uuid.UUID | None, member: bool = True) -> dict:
        members_patch, agents_patch, exposures_patch, runner_patch = self._patched()
        with (
            members_patch as members,
            patch("app.services.access.member_repo", new=members),
            agents_patch as agents,
            exposures_patch as exposures,
            runner_patch as runner_cls,
        ):
            membership = MagicMock(role=OrgRoleName.MEMBER) if member else None
            members.get = AsyncMock(return_value=membership)
            members.get_active = AsyncMock(return_value=membership)
            agents.get_by_slug = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
            exposures.get_for_bot = AsyncMock(
                return_value=MagicMock(
                    is_active=True, created_by_user_id=uuid.uuid4(), organization_id=uuid.uuid4()
                )
            )
            execute = AsyncMock(return_value=("hi", MagicMock()))
            runner_cls.return_value.execute = execute

            await ChannelAgentRouter(MagicMock()).answer(
                "@support what is on page XYZ",
                platform="slack",
                organization_id=uuid.uuid4(),
                bot_id=_BOT_ID,
                user_id=user_id,
                admit_unlinked=True,
            )

        return execute.call_args.kwargs

    async def _defaulted(self, *, user_id: uuid.UUID | None, member: bool = True) -> dict:
        members_patch, _agents_patch, exposures_patch, runner_patch = self._patched()
        organization_id = uuid.uuid4()
        exposure = MagicMock(created_by_user_id=uuid.uuid4(), organization_id=organization_id)
        agent = MagicMock(id=uuid.uuid4(), slug="support")
        with (
            members_patch as members,
            patch("app.services.access.member_repo", new=members),
            exposures_patch as exposures,
            runner_patch as runner_cls,
        ):
            membership = MagicMock(role=OrgRoleName.MEMBER) if member else None
            members.get = AsyncMock(return_value=membership)
            members.get_active = AsyncMock(return_value=membership)
            exposures.list_active_for_bot = AsyncMock(return_value=[(exposure, agent)])
            execute = AsyncMock(return_value=("hi", MagicMock()))
            runner_cls.return_value.execute = execute

            await ChannelAgentRouter(MagicMock()).answer_default(
                "what is on page XYZ",
                platform="slack",
                organization_id=organization_id,
                bot_id=_BOT_ID,
                user_id=user_id,
                admit_unlinked=True,
            )

        return execute.call_args.kwargs

    async def test_a_linked_sender_who_names_the_agent_in_a_room_speaks_as_themselves(self):
        """A mention is by definition in a room, and that used to be the reason
        the sender's own account was never reached. The account is now the
        message's author's, and the room reads the answer as it read the question."""
        assert (await self._mentioned(user_id=uuid.uuid4()))["acts_for_sender"] is True

    async def test_a_linked_sender_on_the_default_path_speaks_as_themselves(self):
        assert (await self._defaulted(user_id=uuid.uuid4()))["acts_for_sender"] is True

    async def test_an_unlinked_sender_admitted_to_a_room_speaks_as_nobody(self):
        """The turn runs under the binding's publisher, and their own Notion is
        not the room's to use."""
        assert (await self._defaulted(user_id=None))["acts_for_sender"] is False

    async def test_an_unlinked_mention_admitted_to_a_room_speaks_as_nobody(self):
        assert (await self._mentioned(user_id=None))["acts_for_sender"] is False

    async def test_a_linked_former_member_in_a_room_speaks_as_nobody(self):
        """Their chat account still names a person, but that person is no longer
        a member, so the turn runs under the binding's publisher - and reading
        `user_id` alone would have reached for the *publisher's* own Notion on a
        stranger's behalf. The flag follows who the context is for."""
        assert (await self._defaulted(user_id=uuid.uuid4(), member=False))["acts_for_sender"] is (
            False
        )

    async def test_a_linked_former_member_who_names_the_agent_speaks_as_nobody(self):
        assert (await self._mentioned(user_id=uuid.uuid4(), member=False))["acts_for_sender"] is (
            False
        )
