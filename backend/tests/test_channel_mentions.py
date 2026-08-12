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
from app.services.channels.mentions import (
    ChannelAgentRouter,
    UnaddressedMessage,
    channel_key,
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
            patch("app.services.access.member_repo", new=members),
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
            patch("app.services.access.member_repo", new=members),
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
            patch("app.services.access.member_repo", new=members),
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
            patch("app.services.access.member_repo", new=members),
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
            patch("app.services.access.member_repo", new=members),
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
            patch("app.services.access.member_repo", new=members),
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
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
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
        """The context a turn ran under, admitting an unnamed sender."""
        agent = MagicMock(id=uuid.uuid4(), slug="support")
        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            members.get = AsyncMock(return_value=kwargs.pop("membership", None))
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
        creator = uuid.uuid4()
        exposure = self._binding(creator, uuid.uuid4())
        agent = MagicMock(id=uuid.uuid4(), slug="support")

        with (
            patch("app.services.channels.mentions.member_repo") as members,
            patch("app.services.access.member_repo", new=members),
            patch("app.services.channels.mentions.agent_exposure_repo") as exposures,
            patch("app.services.channels.mentions.AgentRunnerService") as runner_cls,
        ):
            # The departed sender first, then the creator's own membership.
            members.get = AsyncMock(side_effect=[None, MagicMock(role=OrgRoleName.ADMIN)])
            exposures.list_active_for_bot = AsyncMock(return_value=[(exposure, agent)])
            execute = AsyncMock(return_value=("hello", MagicMock()))
            runner_cls.return_value.execute = execute

            await ChannelAgentRouter(MagicMock()).answer_default(
                "hello",
                platform="mattermost",
                organization_id=exposure.organization_id,
                bot_id=_BOT_ID,
                user_id=uuid.uuid4(),
                admit_unlinked=True,
            )

        ctx = execute.call_args.args[0]
        assert ctx.user_id == creator, "the turn runs under the binding, not under them"
        assert ctx.role == OrgRoleName.ADMIN

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
            members.get = AsyncMock(return_value=MagicMock(role=OrgRoleName.MEMBER))
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
