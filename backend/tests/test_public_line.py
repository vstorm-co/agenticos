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
    bot_ceiling,
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


class TestTheCeilingOfABotsLine:
    async def test_it_is_the_ceiling_of_the_spec_the_bot_serves(self) -> None:
        bot, spec = MagicMock(), _spec(2)
        ceiling = Ceiling(Decimal(3), None)
        with (
            patch(
                "app.services.channels.public_line.bot_served_spec",
                new=AsyncMock(return_value=spec),
            ) as served,
            patch(
                "app.services.channels.public_line.ceiling_for", new=AsyncMock(return_value=ceiling)
            ) as caps,
        ):
            assert await bot_ceiling(MagicMock(), bot) is ceiling

        assert served.await_args.args[1] == bot.id
        assert caps.await_args.kwargs == {"organization_id": bot.organization_id, "spec": spec}


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


class TestWhatALineReaches:
    """The warning a person reads before switching a line on, computed from the spec it serves."""

    ORG = uuid.uuid4()
    COLLECTION, CONTEXT, SKILL, TABLE, DELEGATE, CONNECTION = (uuid.uuid4() for _ in range(6))

    def _spec(self, *, monthly_usd: float | None = 5.0, capabilities=None) -> AgentSpec:
        return AgentSpec(
            name="Front desk",
            budget=None if monthly_usd is None else {"monthly_usd": monthly_usd},
            collection_ids=[self.COLLECTION],
            context_ids=[self.CONTEXT],
            skill_ids=[self.SKILL],
            subagents=[{"agent_id": self.DELEGATE, "agent_version_id": uuid.uuid4()}],
            mcp_servers=[{"account": "organization", "connection_id": self.CONNECTION}],
            capabilities=capabilities
            if capabilities is not None
            else [
                {
                    "id": "virtual_tables",
                    "config": {
                        "tables": [{"table_id": str(self.TABLE), "operations": ["read", "update"]}],
                        "allow_create": True,
                    },
                },
                {"id": "web_fetch"},
                {"id": "code_execution"},
                {"id": "image_generation"},
            ],
        )

    def _bot(self, **policy) -> MagicMock:
        return MagicMock(
            id=uuid.uuid4(),
            organization_id=self.ORG,
            platform="whatsapp",
            transcribe_voice_notes=True,
            access_policy={"mode": "open", "rate_limit_rpm": 7, **policy},
        )

    async def _reach(self, spec: AgentSpec, bot: MagicMock, *, org_cap: Decimal | None = None):
        from app.services.channels.public_line import reach_of

        base = "app.services.channels.public_line."
        version = SimpleNamespace(version=4, spec=spec.model_dump(mode="json"))
        with (
            patch(
                base + "agent_exposure_repo.bound_to_bot",
                AsyncMock(
                    return_value=MagicMock(
                        agent_id=uuid.uuid4(), organization_id=self.ORG, environment_id=None
                    )
                ),
            ),
            patch(base + "_served_version_id", AsyncMock(return_value=uuid.uuid4())),
            patch(base + "agent_repo.get_version", AsyncMock(return_value=version)),
            patch(
                base + "agent_repo.get_many",
                AsyncMock(
                    side_effect=lambda _db, ids, **_k: {
                        i: SimpleNamespace(name="Billing") for i in ids
                    }
                ),
            ),
            patch(
                base + "organization_repo.get_by_id",
                AsyncMock(return_value=MagicMock(monthly_budget_usd=org_cap)),
            ),
            patch(
                base + "knowledge_base_repo.get_by_ids",
                AsyncMock(
                    side_effect=lambda _db, ids: {
                        i: SimpleNamespace(name="Handbook", organization_id=self.ORG) for i in ids
                    }
                ),
            ),
            patch(
                base + "context_repo.get_many",
                AsyncMock(
                    side_effect=lambda _db, ids, **_k: {
                        i: SimpleNamespace(name="Tone") for i in ids
                    }
                ),
            ),
            patch(
                base + "skill_repo.get_many",
                AsyncMock(
                    side_effect=lambda _db, ids, **_k: {
                        i: SimpleNamespace(name="Refunds") for i in ids
                    }
                ),
            ),
            patch(
                base + "virtual_table_repo.get_table",
                AsyncMock(return_value=SimpleNamespace(name="Support")),
            ),
            patch(
                base + "mcp_connection_repo.get_org_scoped_by_ids",
                AsyncMock(
                    side_effect=lambda _db, connection_ids, **_k: {
                        i: SimpleNamespace(name="CRM") for i in connection_ids
                    }
                ),
            ),
        ):
            return await reach_of(MagicMock(), bot)

    async def test_every_kind_the_agent_can_reach_has_one_entry_with_names(self) -> None:
        read = await self._reach(self._spec(), self._bot(answer_unlinked_direct=True))

        by_kind = {entry.kind: entry for entry in read.reaches}
        assert set(by_kind) == {
            "knowledge",
            "context",
            "skills",
            "tables",
            "web",
            "code",
            "generation",
            "delegates",
            "mcp",
        }
        assert by_kind["knowledge"].names == ["Handbook"]
        assert by_kind["context"].names == ["Tone"]
        assert by_kind["skills"].names == ["Refunds"]
        assert by_kind["delegates"].names == ["Billing"]
        assert by_kind["mcp"].names == ["CRM"]
        assert by_kind["tables"].names == ["Support"]
        assert [(g.name, g.operations) for g in by_kind["tables"].grants] == [
            ("Support", ["read", "update"])
        ]
        assert by_kind["tables"].may_create
        assert by_kind["generation"].names == ["image_generation"]
        assert read.answers_unlinked is True
        assert (read.agent_name, read.agent_version) == ("Front desk", 4)
        assert read.refused == [
            "memory",
            "conversation_search",
            "artifacts",
            "workflows",
            "background_tasks",
            "platform_mcp",
        ]

    async def test_web_and_code_say_they_are_outside_the_spending_limit(self) -> None:
        read = await self._reach(self._spec(), self._bot())

        by_kind = {entry.kind: entry for entry in read.reaches}
        assert by_kind["web"].detail == "outside_ledger"
        assert by_kind["code"].detail == "outside_ledger"

    @pytest.mark.security
    async def test_with_no_budget_and_no_cap_the_line_cannot_be_turned_on(self) -> None:
        read = await self._reach(self._spec(monthly_usd=None), self._bot())

        assert read.can_turn_on is False
        assert read.agent_monthly_usd is None
        assert read.organization_monthly_usd is None

    @pytest.mark.security
    async def test_either_budget_makes_it_possible(self) -> None:
        read = await self._reach(self._spec(), self._bot(), org_cap=Decimal("50"))

        assert read.can_turn_on is True
        assert read.agent_monthly_usd == Decimal("5.0")
        assert read.organization_monthly_usd == Decimal("50")

    async def test_the_limits_a_customer_meets_are_stated(self) -> None:
        from app.core.config import settings

        read = await self._reach(self._spec(), self._bot())

        assert read.rate_limit_rpm == 7
        assert read.approval_expiry_hours == settings.APPROVAL_EXPIRY_HOURS == 72
        assert read.recording_max_mb == 2
        assert read.file_max_mb == settings.EMBED_MAX_UPLOAD_SIZE_MB

    async def test_voice_notes_need_an_organization_cap(self) -> None:
        only_agent = await self._reach(self._spec(), self._bot())
        with_cap = await self._reach(self._spec(), self._bot(), org_cap=Decimal("9"))
        off = self._bot()
        off.transcribe_voice_notes = False

        assert only_agent.voice == "refused_no_org_cap"
        assert with_cap.voice == "on"
        assert (await self._reach(self._spec(), off, org_cap=Decimal("9"))).voice == "off"

    async def test_files_are_listed_only_while_the_setting_is_on(self) -> None:
        off = await self._reach(self._spec(), self._bot())
        on = await self._reach(self._spec(), self._bot(accept_customer_files=True))

        assert "files" not in {entry.kind for entry in off.reaches}
        assert off.accept_customer_files is False
        assert "files" in {entry.kind for entry in on.reaches}
        assert on.accept_customer_files is True

    async def test_a_bot_with_no_binding_reaches_nothing(self) -> None:
        from app.services.channels.public_line import reach_of

        base = "app.services.channels.public_line."
        with (
            patch(base + "agent_exposure_repo.bound_to_bot", AsyncMock(return_value=None)),
            patch(
                base + "organization_repo.get_by_id",
                AsyncMock(return_value=MagicMock(monthly_budget_usd=Decimal("3"))),
            ),
        ):
            read = await reach_of(MagicMock(), self._bot())

        assert read.reaches == []
        assert read.agent_name is None
        assert read.can_turn_on is True

    async def test_a_spec_with_nothing_to_reach_lists_no_entries(self) -> None:
        bare = AgentSpec(name="Bare", budget={"monthly_usd": 1})

        read = await self._reach(bare, self._bot())

        assert read.reaches == []

    async def test_a_disabled_capability_and_a_table_that_is_gone_are_not_listed(self) -> None:
        from app.services.channels import public_line

        spec = self._spec(
            capabilities=[
                {"id": "web_fetch", "enabled": False},
                {
                    "id": "virtual_tables",
                    "enabled": False,
                    "config": {"tables": [{"table_id": str(self.TABLE)}]},
                },
            ]
        )
        read = await self._reach(spec, self._bot())
        assert not {"web", "tables"} & {entry.kind for entry in read.reaches}

        with patch.object(
            public_line.virtual_table_repo, "get_table", AsyncMock(return_value=None)
        ):
            assert (
                await public_line._table_reach(
                    MagicMock(),
                    self._spec(
                        capabilities=[
                            {
                                "id": "virtual_tables",
                                "config": {"tables": [{"table_id": str(self.TABLE)}]},
                            }
                        ]
                    ),
                    organization_id=self.ORG,
                )
                is None
            )

    async def test_read_only_tables_do_not_claim_they_can_create(self) -> None:
        spec = self._spec(
            capabilities=[
                {"id": "virtual_tables", "config": {"tables": [{"table_id": str(self.TABLE)}]}}
            ]
        )

        read = await self._reach(spec, self._bot())

        tables = next(entry for entry in read.reaches if entry.kind == "tables")
        assert [(g.name, g.operations) for g in tables.grants] == [("Support", ["read"])]

    async def test_an_agent_with_nothing_published_reaches_nothing(self) -> None:
        from app.services.channels.public_line import reach_of

        base = "app.services.channels.public_line."
        with (
            patch(
                base + "agent_exposure_repo.bound_to_bot",
                AsyncMock(
                    return_value=MagicMock(
                        agent_id=uuid.uuid4(), organization_id=self.ORG, environment_id=None
                    )
                ),
            ),
            patch(base + "_served_version_id", AsyncMock(return_value=None)),
            patch(
                base + "organization_repo.get_by_id",
                AsyncMock(return_value=MagicMock(monthly_budget_usd=None)),
            ),
        ):
            read = await reach_of(MagicMock(), self._bot())

        assert (read.reaches, read.agent_name, read.can_turn_on) == ([], None, False)
