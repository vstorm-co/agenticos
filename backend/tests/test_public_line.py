"""What it takes for a line to answer people who never linked an account.

The switch is one key in the access policy, and it only counts when nothing
stronger says no: a mode named for a linked account, or the switch that makes
every mode ask for a link. These pin that reading, on the raw key and on the
policy as it is stored.
"""

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.services.channels.public_line import (
    Ceiling,
    answers_unlinked_direct,
    answers_unlinked_on,
    bot_answers_unlinked_direct,
    bot_served_spec,
    ceiling_for,
    refuse_without_ceiling,
    served_spec,
)

pytestmark = pytest.mark.anyio


class TestWhenALineAnswersStrangers:
    def test_the_switch_on_opens_the_line(self) -> None:
        assert answers_unlinked_direct({"mode": "open", "answer_unlinked_direct": True}) is True

    def test_a_policy_stored_before_the_switch_existed_does_not_answer(self) -> None:
        assert answers_unlinked_direct({"mode": "open", "require_link": False}) is False

    def test_an_empty_policy_does_not_answer(self) -> None:
        assert answers_unlinked_direct({}) is False

    def test_the_switch_off_does_not_answer(self) -> None:
        assert answers_unlinked_direct({"answer_unlinked_direct": False}) is False

    @pytest.mark.parametrize("stored", ["true", "True", 1, "yes", [True]])
    def test_only_a_real_true_counts(self, stored: object) -> None:
        """A value that merely reads as true is not somebody having switched it on."""
        assert answers_unlinked_direct({"answer_unlinked_direct": stored}) is False

    @pytest.mark.security
    def test_jwt_linked_wins_over_the_switch(self) -> None:
        policy = {"mode": "jwt_linked", "answer_unlinked_direct": True}

        assert answers_unlinked_direct(policy) is False

    @pytest.mark.security
    def test_require_link_wins_over_the_switch(self) -> None:
        policy = {"mode": "open", "require_link": True, "answer_unlinked_direct": True}

        assert answers_unlinked_direct(policy) is False

    @pytest.mark.security
    def test_require_link_wins_in_every_mode(self) -> None:
        for mode in ("open", "whitelist", "group_only"):
            policy = {"mode": mode, "require_link": True, "answer_unlinked_direct": True}

            assert answers_unlinked_direct(policy) is False, mode

    def test_the_mode_is_not_needed_to_open_the_line(self) -> None:
        assert answers_unlinked_direct({"answer_unlinked_direct": True}) is True


def _spec(monthly_usd: float | None = None) -> AgentSpec:
    return AgentSpec(
        name="Front desk", budget=None if monthly_usd is None else {"monthly_usd": monthly_usd}
    )


class TestTheCeilingOfARunWithNoMember:
    @pytest.mark.security
    async def test_an_agent_budget_alone_is_a_ceiling(self) -> None:
        with patch(
            "app.services.channels.public_line.organization_repo.get_by_id",
            new=AsyncMock(return_value=MagicMock(monthly_budget_usd=None)),
        ):
            ceiling = await ceiling_for(MagicMock(), organization_id=uuid.uuid4(), spec=_spec(0.1))

        assert ceiling == Ceiling(Decimal("0.1"), None)
        assert ceiling.exists is True

    async def test_an_organization_cap_alone_is_a_ceiling(self) -> None:
        with patch(
            "app.services.channels.public_line.organization_repo.get_by_id",
            new=AsyncMock(return_value=MagicMock(monthly_budget_usd=Decimal("50"))),
        ):
            ceiling = await ceiling_for(MagicMock(), organization_id=uuid.uuid4(), spec=_spec())

        assert ceiling == Ceiling(None, Decimal("50"))
        assert ceiling.exists is True

    async def test_neither_cap_is_no_ceiling(self) -> None:
        with patch(
            "app.services.channels.public_line.organization_repo.get_by_id",
            new=AsyncMock(return_value=MagicMock(monthly_budget_usd=None)),
        ):
            ceiling = await ceiling_for(MagicMock(), organization_id=uuid.uuid4(), spec=_spec())
            nothing_served = await ceiling_for(MagicMock(), organization_id=uuid.uuid4(), spec=None)

        assert ceiling == nothing_served == Ceiling(None, None)
        assert ceiling.exists is False

    async def test_an_organization_that_is_gone_has_no_cap(self) -> None:
        with patch(
            "app.services.channels.public_line.organization_repo.get_by_id",
            new=AsyncMock(return_value=None),
        ):
            ceiling = await ceiling_for(MagicMock(), organization_id=uuid.uuid4(), spec=None)

        assert ceiling.exists is False

    @pytest.mark.security
    async def test_a_refusal_names_the_fix_and_the_bot_and_nothing_else(self) -> None:
        bot_id = uuid.uuid4()
        with (
            patch(
                "app.services.channels.public_line.organization_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(monthly_budget_usd=None)),
            ),
            pytest.raises(BadRequestError) as refused,
        ):
            await refuse_without_ceiling(
                MagicMock(), organization_id=uuid.uuid4(), spec=_spec(), channel_bot_id=bot_id
            )

        assert "needs a spending limit" in refused.value.message
        assert "monthly budget" in refused.value.message
        assert "monthly cap" in refused.value.message
        assert refused.value.details == {"channel_bot_id": str(bot_id)}

    @pytest.mark.security
    async def test_a_bot_not_yet_created_has_no_id_to_name(self) -> None:
        with (
            patch(
                "app.services.channels.public_line.organization_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(monthly_budget_usd=None)),
            ),
            pytest.raises(BadRequestError) as refused,
        ):
            await refuse_without_ceiling(
                MagicMock(), organization_id=uuid.uuid4(), spec=None, channel_bot_id=None
            )

        assert refused.value.details == {"channel_bot_id": None}

    async def test_a_ceiling_lets_it_through(self) -> None:
        with patch(
            "app.services.channels.public_line.organization_repo.get_by_id",
            new=AsyncMock(return_value=MagicMock(monthly_budget_usd=Decimal("5"))),
        ):
            await refuse_without_ceiling(
                MagicMock(), organization_id=uuid.uuid4(), spec=None, channel_bot_id=None
            )


class TestWhatABindingAnswersWith:
    """The spec a binding is served: its environment's version, else the agent's current one."""

    ORG = uuid.uuid4()

    @staticmethod
    def _binding(environment_id: uuid.UUID | None = None) -> MagicMock:
        return MagicMock(
            agent_id=uuid.uuid4(),
            organization_id=TestWhatABindingAnswersWith.ORG,
            environment_id=environment_id,
        )

    @staticmethod
    def _repos(*, agent, environment=None, version_spec=None):
        versions: dict[uuid.UUID, object] = {}

        async def get_version(db, version_id, *, organization_id):
            assert organization_id == TestWhatABindingAnswersWith.ORG
            return versions.get(version_id)

        if version_spec is not None:
            versions[version_spec[0]] = SimpleNamespace(spec=version_spec[1])
        return (
            patch(
                "app.services.channels.public_line.agent_repo.get", AsyncMock(return_value=agent)
            ),
            patch("app.services.channels.public_line.agent_repo.get_version", get_version),
            patch(
                "app.services.channels.public_line.agent_environment_repo.get",
                AsyncMock(return_value=environment),
            ),
        )

    async def _served(self, binding, **repos):
        a, b, c = self._repos(**repos)
        with a, b, c:
            return await served_spec(MagicMock(), binding)

    async def test_the_agents_current_version_answers_by_default(self) -> None:
        version = uuid.uuid4()
        agent = MagicMock(id=uuid.uuid4(), current_version_id=version)

        spec = await self._served(
            self._binding(), agent=agent, version_spec=(version, _spec(7).model_dump(mode="json"))
        )

        assert spec is not None
        assert spec.budget is not None
        assert spec.budget.monthly_usd == 7

    async def test_the_environment_a_binding_names_decides_the_version(self) -> None:
        current, pinned = uuid.uuid4(), uuid.uuid4()
        agent = MagicMock(id=uuid.uuid4(), current_version_id=current)
        environment = MagicMock(agent_id=agent.id, version_id=pinned)

        spec = await self._served(
            self._binding(uuid.uuid4()),
            agent=agent,
            environment=environment,
            version_spec=(pinned, _spec(3).model_dump(mode="json")),
        )

        assert spec is not None
        assert spec.budget is not None
        assert spec.budget.monthly_usd == 3

    async def test_a_missing_agent_serves_nothing(self) -> None:
        assert await self._served(self._binding(), agent=None) is None

    async def test_an_environment_of_another_agent_serves_nothing(self) -> None:
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        environment = MagicMock(agent_id=uuid.uuid4(), version_id=uuid.uuid4())

        assert (
            await self._served(self._binding(uuid.uuid4()), agent=agent, environment=environment)
            is None
        )

    async def test_an_environment_that_is_gone_serves_nothing(self) -> None:
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())

        assert await self._served(self._binding(uuid.uuid4()), agent=agent) is None

    async def test_an_agent_never_published_serves_nothing(self) -> None:
        agent = MagicMock(id=uuid.uuid4(), current_version_id=None)

        assert await self._served(self._binding(), agent=agent) is None

    async def test_a_version_that_is_gone_serves_nothing(self) -> None:
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())

        assert await self._served(self._binding(), agent=agent) is None


class TestTheSpecABotIsBoundTo:
    async def test_a_bot_with_no_binding_has_none(self) -> None:
        with patch(
            "app.services.channels.public_line.agent_exposure_repo.bound_to_bot",
            new=AsyncMock(return_value=None),
        ):
            assert await bot_served_spec(MagicMock(), uuid.uuid4()) is None

    async def test_a_binding_is_read_whether_or_not_it_is_active(self) -> None:
        binding, spec = MagicMock(is_active=False), _spec(2)
        with (
            patch(
                "app.services.channels.public_line.agent_exposure_repo.bound_to_bot",
                new=AsyncMock(return_value=binding),
            ),
            patch(
                "app.services.channels.public_line.served_spec", new=AsyncMock(return_value=spec)
            ) as served,
        ):
            assert await bot_served_spec(MagicMock(), uuid.uuid4()) is spec

        served.assert_awaited_once()
        assert served.await_args.args[1] is binding


class TestWhichBotsAnswerStrangers:
    """The policy key counts only on a platform that can take it, and is read from the
    stored row the way the router reads it - a dict, or JSON text."""

    @staticmethod
    def _bot(policy, platform: str = "whatsapp") -> MagicMock:
        return MagicMock(platform=platform, access_policy=policy)

    def test_a_whatsapp_bot_with_the_switch_answers(self) -> None:
        assert bot_answers_unlinked_direct(self._bot(OPEN)) is True

    @pytest.mark.security
    @pytest.mark.parametrize("platform", ["telegram", "slack", "discord", "teams", "mattermost"])
    def test_another_platform_never_does_whatever_its_policy_says(self, platform: str) -> None:
        assert bot_answers_unlinked_direct(self._bot(OPEN, platform)) is False
        assert answers_unlinked_on(platform, OPEN) is False

    def test_a_policy_stored_as_json_text_is_read(self) -> None:
        assert bot_answers_unlinked_direct(self._bot('{"answer_unlinked_direct": true}')) is True
        assert (
            bot_answers_unlinked_direct(
                self._bot('{"answer_unlinked_direct": true, "require_link": true}')
            )
            is False
        )

    @pytest.mark.parametrize("stored", [None, {}, "", "{}"])
    def test_a_bot_with_no_policy_does_not(self, stored) -> None:
        assert bot_answers_unlinked_direct(self._bot(stored)) is False

    def test_a_mock_bot_does_not(self) -> None:
        """A double that never said anything about the platform or the policy is closed."""
        assert bot_answers_unlinked_direct(MagicMock()) is False


OPEN = {"mode": "open", "answer_unlinked_direct": True}
