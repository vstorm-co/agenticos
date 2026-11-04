"""A line that answers strangers needs a spending ceiling, against a real database.

The ceiling is the served agent's own monthly budget or the organization's monthly
cap. These build real rows - an organization, a published agent, a bot, its binding
- and drive the bot service, because what must hold is the decision read off the
stored rows: which agent a bot is bound to, paused or not, and which of the two caps
exists.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.db.models.agent import AgentVersion
from app.db.models.agent_exposure import AgentExposure
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.channel_bot import ChannelBot
from app.schemas.agent_environment import EnvironmentCreate, EnvironmentUpdate
from app.schemas.agent_exposure import ExposureCreate, ExposureUpdate
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotUpdate
from app.services.agent_environment import AgentEnvironmentService
from app.services.agent_exposure import AgentExposureService
from app.services.agent_registry import AgentRegistryService
from app.services.channel_bot import ChannelBotService, seal_bot_token
from tests.integration.test_platform_flows import (
    Tenant,
    _keyed_model_profile,
    _published_agent,
    _tenant,
)

pytestmark = pytest.mark.anyio

OPEN = {"mode": "open", "answer_unlinked_direct": True}
AUDIT = "channel.bot.public_line_changed"


async def _bot(
    db, tenant: Tenant, *, policy: dict | None = None, active: bool = True
) -> ChannelBot:
    bot = ChannelBot(
        organization_id=tenant.organization.id,
        platform="whatsapp",
        name="Front desk",
        token_encrypted=seal_bot_token("token", organization_id=tenant.organization.id).ciphertext,
        secret_key_version=1,
        webhook_mode=True,
        access_policy=policy or {},
        is_active=active,
        whatsapp_phone_number_id="104567890123456",
        whatsapp_account_id="207654321098765",
    )
    db.add(bot)
    await db.flush()
    return bot


async def _bind(db, tenant: Tenant, bot: ChannelBot, *, budget: float | None, paused: bool = False):
    spec = AgentSpec(
        name=f"Support {uuid.uuid4().hex[:6]}",
        budget=None if budget is None else {"monthly_usd": budget},
    )
    agent = await _published_agent(db, tenant, spec=spec)
    db.add(
        AgentExposure(
            id=uuid.uuid4(),
            organization_id=tenant.organization.id,
            agent_id=agent.id,
            surface="whatsapp",
            channel_bot_id=bot.id,
            is_active=not paused,
            created_by_user_id=tenant.user.id,
        )
    )
    await db.flush()
    return agent


async def _cap(db, tenant: Tenant, cap: str | None) -> None:
    tenant.organization.monthly_budget_usd = None if cap is None else Decimal(cap)
    await db.flush()


def _service(db, tenant: Tenant) -> ChannelBotService:
    return ChannelBotService(db, organization_id=tenant.organization.id)


async def _audits(db, tenant: Tenant) -> list[AppAdminAuditLog]:
    return list(
        (
            await db.execute(
                select(AppAdminAuditLog).where(
                    AppAdminAuditLog.organization_id == tenant.organization.id,
                    AppAdminAuditLog.action == AUDIT,
                )
            )
        ).scalars()
    )


def _opening(**fields) -> ChannelBotUpdate:
    return ChannelBotUpdate(access_policy={**OPEN, **fields})


class TestTurningTheSwitchOn:
    @pytest.mark.security
    async def test_a_bound_agent_with_no_budget_and_no_cap_is_refused(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        await _keyed_model_profile(db, tenant)
        bot = await _bot(db, tenant)
        await _bind(db, tenant, bot, budget=None)

        with pytest.raises(BadRequestError) as refused:
            await _service(db, tenant).update(bot.id, _opening(), actor_user_id=tenant.user.id)

        assert "needs a spending limit" in refused.value.message
        assert refused.value.details == {"channel_bot_id": str(bot.id)}
        await db.refresh(bot)
        assert bot.access_policy == {}
        assert await _audits(db, tenant) == []

    @pytest.mark.security
    async def test_an_agent_budget_is_a_ceiling(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        await _keyed_model_profile(db, tenant)
        bot = await _bot(db, tenant)
        await _bind(db, tenant, bot, budget=5)

        await _service(db, tenant).update(bot.id, _opening(), actor_user_id=tenant.user.id)

        await db.refresh(bot)
        assert bot.access_policy["answer_unlinked_direct"] is True

    async def test_an_organization_cap_is_a_ceiling(self, db) -> None:
        tenant = await _tenant(db, name="Shop", monthly_budget_usd=Decimal("50"))
        await _keyed_model_profile(db, tenant)
        bot = await _bot(db, tenant)
        await _bind(db, tenant, bot, budget=None)

        await _service(db, tenant).update(bot.id, _opening(), actor_user_id=tenant.user.id)

        await db.refresh(bot)
        assert bot.access_policy["answer_unlinked_direct"] is True

    @pytest.mark.security
    async def test_a_bot_with_no_binding_counts_only_the_organization_cap(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        bot = await _bot(db, tenant)

        with pytest.raises(BadRequestError):
            await _service(db, tenant).update(bot.id, _opening(), actor_user_id=tenant.user.id)

        await _cap(db, tenant, "50")
        await _service(db, tenant).update(bot.id, _opening(), actor_user_id=tenant.user.id)

        await db.refresh(bot)
        assert bot.access_policy["answer_unlinked_direct"] is True

    @pytest.mark.security
    async def test_a_paused_binding_still_counts_as_the_bound_agent(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        await _keyed_model_profile(db, tenant)
        with_budget = await _bot(db, tenant)
        without = await _bot(db, tenant)
        await _bind(db, tenant, with_budget, budget=5, paused=True)
        await _bind(db, tenant, without, budget=None, paused=True)

        await _service(db, tenant).update(with_budget.id, _opening(), actor_user_id=tenant.user.id)
        with pytest.raises(BadRequestError):
            await _service(db, tenant).update(without.id, _opening(), actor_user_id=tenant.user.id)

        await db.refresh(with_budget)
        assert with_budget.access_policy["answer_unlinked_direct"] is True

    @pytest.mark.security
    async def test_another_organizations_cap_is_not_this_ones(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        await _tenant(db, name="Other", monthly_budget_usd=Decimal("500"))
        bot = await _bot(db, tenant)

        with pytest.raises(BadRequestError):
            await _service(db, tenant).update(bot.id, _opening(), actor_user_id=tenant.user.id)


class TestOpeningTheLineByChangingTheMode:
    @pytest.mark.security
    async def test_it_needs_a_ceiling_and_is_audited_once_it_has_one(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        await _keyed_model_profile(db, tenant)
        bot = await _bot(db, tenant, policy={"mode": "jwt_linked", "answer_unlinked_direct": True})
        await _bind(db, tenant, bot, budget=None)

        with pytest.raises(BadRequestError):
            await _service(db, tenant).update(
                bot.id, _opening(mode="open"), actor_user_id=tenant.user.id
            )
        await db.refresh(bot)
        assert bot.access_policy["mode"] == "jwt_linked"
        assert await _audits(db, tenant) == []

        await _cap(db, tenant, "50")
        await _service(db, tenant).update(
            bot.id, _opening(mode="open"), actor_user_id=tenant.user.id
        )

        [entry] = await _audits(db, tenant)
        assert entry.details == {"answers_unlinked": True}
        assert entry.actor_user_id == tenant.user.id
        assert entry.target_type == "channel_bot"
        assert entry.target_id == str(bot.id)

    @pytest.mark.security
    async def test_closing_the_line_with_require_link_is_audited(self, db) -> None:
        tenant = await _tenant(db, name="Shop", monthly_budget_usd=Decimal("50"))
        bot = await _bot(db, tenant, policy=OPEN)

        await _service(db, tenant).update(
            bot.id, _opening(require_link=True), actor_user_id=tenant.user.id
        )

        [entry] = await _audits(db, tenant)
        assert entry.details == {"answers_unlinked": False}

    async def test_the_flip_is_audited_without_the_rest_of_the_policy(self, db) -> None:
        tenant = await _tenant(db, name="Shop", monthly_budget_usd=Decimal("50"))
        bot = await _bot(db, tenant)

        await _service(db, tenant).update(
            bot.id,
            _opening(whitelist=["secret-number"], denied_message="no"),
            actor_user_id=tenant.user.id,
        )

        [entry] = await _audits(db, tenant)
        assert entry.details == {"answers_unlinked": True}
        assert "secret-number" not in str(entry.details)

    async def test_an_update_that_does_not_change_the_state_writes_no_audit(self, db) -> None:
        tenant = await _tenant(db, name="Shop", monthly_budget_usd=Decimal("50"))
        bot = await _bot(db, tenant, policy=OPEN)

        await _service(db, tenant).update(
            bot.id, _opening(rate_limit_rpm=3), actor_user_id=tenant.user.id
        )

        assert await _audits(db, tenant) == []

    async def test_turning_it_off_needs_nothing(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        bot = await _bot(db, tenant, policy=OPEN)

        await _service(db, tenant).update(
            bot.id,
            ChannelBotUpdate(access_policy={"mode": "open"}),
            actor_user_id=tenant.user.id,
        )

        [entry] = await _audits(db, tenant)
        assert entry.details == {"answers_unlinked": False}


class TestCreatingWithTheLineOpen:
    def _data(self, **policy) -> ChannelBotCreate:
        return ChannelBotCreate(
            platform="whatsapp",
            name="Front desk",
            token="EAAG-access-token-0123456789",
            webhook_secret="app-secret-abcdef",
            whatsapp_phone_number_id="104567890123456",
            whatsapp_account_id="207654321098765",
            whatsapp_verify_token="verify-token-xyz",
            access_policy=policy,
        )

    @pytest.mark.security
    async def test_it_needs_the_organization_cap_and_is_audited(self, db) -> None:
        tenant = await _tenant(db, name="Shop")

        with pytest.raises(BadRequestError):
            await _service(db, tenant).create(self._data(**OPEN), actor_user_id=tenant.user.id)
        bots = (
            await db.execute(
                select(ChannelBot).where(ChannelBot.organization_id == tenant.organization.id)
            )
        ).scalars()
        assert list(bots) == []

        await _cap(db, tenant, "50")
        created = await _service(db, tenant).create(
            self._data(**OPEN), actor_user_id=tenant.user.id
        )

        [entry] = await _audits(db, tenant)
        assert entry.details == {"answers_unlinked": True}
        assert entry.target_id == str(created.id)


class TestReactivatingALine:
    @pytest.mark.security
    async def test_a_deactivated_line_that_answers_strangers_needs_a_ceiling_to_come_back(
        self, db
    ) -> None:
        tenant = await _tenant(db, name="Shop")
        await _keyed_model_profile(db, tenant)
        bot = await _bot(db, tenant, policy=OPEN, active=False)
        await _bind(db, tenant, bot, budget=None)

        with pytest.raises(BadRequestError):
            await _service(db, tenant).activate(bot.id)
        await db.refresh(bot)
        assert bot.is_active is False

        await _cap(db, tenant, "50")
        activated = await _service(db, tenant).activate(bot.id)

        assert activated.is_active is True

    async def test_a_deactivated_line_that_does_not_answer_strangers_comes_back_freely(
        self, db
    ) -> None:
        tenant = await _tenant(db, name="Shop")
        bot = await _bot(db, tenant, policy={"mode": "open"}, active=False)

        assert (await _service(db, tenant).activate(bot.id)).is_active is True


class TestReactivatingByUpdate:
    @pytest.mark.security
    async def test_an_update_cannot_bring_a_line_back_without_a_ceiling(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        await _keyed_model_profile(db, tenant)
        bot = await _bot(db, tenant, policy=OPEN, active=False)
        await _bind(db, tenant, bot, budget=None)

        with pytest.raises(BadRequestError):
            await _service(db, tenant).update(
                bot.id, ChannelBotUpdate(is_active=True), actor_user_id=tenant.user.id
            )
        await db.refresh(bot)
        assert bot.is_active is False

        await _cap(db, tenant, "50")
        updated = await _service(db, tenant).update(
            bot.id, ChannelBotUpdate(is_active=True), actor_user_id=tenant.user.id
        )

        assert updated.is_active is True

    async def test_a_closed_line_comes_back_by_update_freely(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        bot = await _bot(db, tenant, policy={"mode": "open"}, active=False)

        updated = await _service(db, tenant).update(
            bot.id, ChannelBotUpdate(is_active=True), actor_user_id=tenant.user.id
        )

        assert updated.is_active is True


class TestTheAgentsBudgetAloneBringsALineBack:
    @pytest.mark.security
    @pytest.mark.parametrize("how", ["activate", "update"])
    async def test_it_comes_back(self, db, how: str) -> None:
        tenant = await _tenant(db, name="Shop")
        await _keyed_model_profile(db, tenant)
        bot = await _bot(db, tenant, policy=OPEN, active=False)
        await _bind(db, tenant, bot, budget=5)

        service = _service(db, tenant)
        if how == "activate":
            brought_back = await service.activate(bot.id)
        else:
            brought_back = await service.update(
                bot.id, ChannelBotUpdate(is_active=True), actor_user_id=tenant.user.id
            )

        assert brought_back.is_active is True


class TestAPolicyStoredAsJsonText:
    @pytest.mark.security
    async def test_reactivation_reads_it_and_refuses_without_a_ceiling(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        bot = await _bot(db, tenant, policy={"mode": "open"})
        bot.access_policy = '{"mode": "open", "answer_unlinked_direct": true}'  # type: ignore[assignment]
        bot.is_active = False
        await db.flush()

        with pytest.raises(BadRequestError):
            await _service(db, tenant).activate(bot.id)


def _spec(budget: float | None, name: str = "Support") -> AgentSpec:
    return AgentSpec(name=name, budget=None if budget is None else {"monthly_usd": budget})


async def _versions(db, agent_id: uuid.UUID) -> list[AgentVersion]:
    return list(
        (
            await db.execute(
                select(AgentVersion)
                .where(AgentVersion.agent_id == agent_id)
                .order_by(AgentVersion.version)
            )
        ).scalars()
    )


async def _publish(db, tenant: Tenant, agent, budget: float | None) -> AgentVersion:
    registry = AgentRegistryService(db)
    draft = AgentSpec.model_validate(agent.draft_spec)
    wanted = None if budget is None else {"monthly_usd": budget}
    await registry.save_draft(
        tenant.ctx, agent.id, AgentSpec.model_validate({**draft.model_dump(), "budget": wanted})
    )
    return await registry.publish(tenant.ctx, agent.id)


async def _line(db, tenant: Tenant, *, policy: dict | None = OPEN, active: bool = True):
    """A published agent with a budgeted version, and a bot that has no binding yet."""
    await _keyed_model_profile(db, tenant)
    agent = await _published_agent(db, tenant, spec=_spec(5, f"Support {uuid.uuid4().hex[:6]}"))
    bot = await _bot(db, tenant, policy=policy, active=active)
    return agent, bot


async def _environment(db, tenant: Tenant, agent, name: str, version: AgentVersion):
    return await AgentEnvironmentService(db).create(
        tenant.ctx, agent.id, EnvironmentCreate(name=name, version_id=version.id)
    )


def _bound(
    tenant: Tenant, agent, bot: ChannelBot, *, environment=None, paused: bool = False
) -> AgentExposure:
    return AgentExposure(
        id=uuid.uuid4(),
        organization_id=tenant.organization.id,
        agent_id=agent.id,
        surface="whatsapp",
        channel_bot_id=bot.id,
        environment_id=None if environment is None else environment.id,
        is_active=not paused,
        created_by_user_id=tenant.user.id,
    )


async def _binding(db, tenant: Tenant, agent, bot: ChannelBot, **kwargs) -> AgentExposure:
    """A binding written straight to the table, as if made before the line opened."""
    exposure = _bound(tenant, agent, bot, **kwargs)
    db.add(exposure)
    await db.flush()
    return exposure


async def _bindings_on(db, bot: ChannelBot) -> list[AgentExposure]:
    return list(
        (
            await db.execute(select(AgentExposure).where(AgentExposure.channel_bot_id == bot.id))
        ).scalars()
    )


def _exposures(db) -> AgentExposureService:
    return AgentExposureService(db)


class TestBindingAnAgentToAPublicLine:
    @pytest.mark.security
    async def test_a_version_with_no_budget_and_no_cap_is_refused_and_leaves_no_row(
        self, db
    ) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        await _publish(db, tenant, agent, None)

        with pytest.raises(BadRequestError) as refused:
            await _exposures(db).create(tenant.ctx, agent.id, ExposureCreate(channel_bot_id=bot.id))

        assert "needs a spending limit" in refused.value.message
        assert refused.value.details == {"channel_bot_id": str(bot.id)}
        assert await _bindings_on(db, bot) == []

    @pytest.mark.security
    async def test_the_environment_it_names_is_the_version_that_is_judged(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        budgeted = (await _versions(db, agent.id))[0]
        await _publish(db, tenant, agent, None)
        dev = await _environment(db, tenant, agent, "dev", budgeted)

        with pytest.raises(BadRequestError):
            await _exposures(db).create(tenant.ctx, agent.id, ExposureCreate(channel_bot_id=bot.id))
        created = await _exposures(db).create(
            tenant.ctx, agent.id, ExposureCreate(channel_bot_id=bot.id, environment_id=dev.id)
        )

        assert created.environment_id == dev.id

    @pytest.mark.security
    async def test_an_organization_cap_lets_it_through(self, db) -> None:
        tenant = await _tenant(db, name="Shop", monthly_budget_usd=Decimal("50"))
        agent, bot = await _line(db, tenant)
        await _publish(db, tenant, agent, None)

        await _exposures(db).create(tenant.ctx, agent.id, ExposureCreate(channel_bot_id=bot.id))

        assert len(await _bindings_on(db, bot)) == 1

    async def test_a_bot_that_does_not_answer_strangers_is_bound_freely(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant, policy={"mode": "open"})
        await _publish(db, tenant, agent, None)

        await _exposures(db).create(tenant.ctx, agent.id, ExposureCreate(channel_bot_id=bot.id))

        assert len(await _bindings_on(db, bot)) == 1


class TestChangingWhatABindingServes:
    @pytest.mark.security
    @pytest.mark.parametrize("target", ["named", "default"])
    async def test_an_environment_with_no_budget_is_refused_and_the_binding_stays(
        self, db, target: str
    ) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        budgeted = (await _versions(db, agent.id))[0]
        bare_version = await _publish(db, tenant, agent, None)
        dev = await _environment(db, tenant, agent, "dev", budgeted)
        bare = await _environment(db, tenant, agent, "bare", bare_version)
        binding = await _binding(db, tenant, agent, bot, environment=dev)
        wanted = bare.id if target == "named" else None

        with pytest.raises(BadRequestError) as refused:
            await _exposures(db).update(
                tenant.ctx, agent.id, binding.id, ExposureUpdate(environment_id=wanted)
            )

        assert refused.value.details == {"channel_bot_id": str(bot.id)}
        await db.refresh(binding)
        assert binding.environment_id == dev.id

    @pytest.mark.security
    async def test_an_organization_cap_lets_the_environment_change(self, db) -> None:
        tenant = await _tenant(db, name="Shop", monthly_budget_usd=Decimal("50"))
        agent, bot = await _line(db, tenant)
        budgeted = (await _versions(db, agent.id))[0]
        bare = await _environment(
            db, tenant, agent, "bare", await _publish(db, tenant, agent, None)
        )
        dev = await _environment(db, tenant, agent, "dev", budgeted)
        binding = await _binding(db, tenant, agent, bot, environment=dev)

        updated = await _exposures(db).update(
            tenant.ctx, agent.id, binding.id, ExposureUpdate(environment_id=bare.id)
        )

        assert updated.environment_id == bare.id

    @pytest.mark.security
    async def test_resuming_a_paused_binding_that_has_no_budget_is_refused(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        await _publish(db, tenant, agent, None)
        binding = await _binding(db, tenant, agent, bot, paused=True)

        with pytest.raises(BadRequestError):
            await _exposures(db).update(
                tenant.ctx, agent.id, binding.id, ExposureUpdate(is_active=True)
            )

        await db.refresh(binding)
        assert binding.is_active is False

        await _cap(db, tenant, "50")
        resumed = await _exposures(db).update(
            tenant.ctx, agent.id, binding.id, ExposureUpdate(is_active=True)
        )
        assert resumed.is_active is True

    async def test_a_binding_on_a_bot_that_does_not_answer_strangers_changes_freely(
        self, db
    ) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant, policy={"mode": "open"})
        bare = await _environment(
            db, tenant, agent, "bare", await _publish(db, tenant, agent, None)
        )
        binding = await _binding(db, tenant, agent, bot, paused=True)

        await _exposures(db).update(
            tenant.ctx, agent.id, binding.id, ExposureUpdate(environment_id=bare.id)
        )
        resumed = await _exposures(db).update(
            tenant.ctx, agent.id, binding.id, ExposureUpdate(is_active=True)
        )

        assert resumed.is_active is True

    async def test_edits_that_serve_nothing_new_are_not_refused(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        await _publish(db, tenant, agent, None)
        binding = await _binding(db, tenant, agent, bot)

        await _exposures(db).update(
            tenant.ctx, agent.id, binding.id, ExposureUpdate(prompt="Be brief.")
        )
        await _exposures(db).update(
            tenant.ctx, agent.id, binding.id, ExposureUpdate(environment_id=None, is_active=True)
        )
        paused = await _exposures(db).update(
            tenant.ctx, agent.id, binding.id, ExposureUpdate(is_active=False)
        )

        assert paused.is_active is False


class TestVersionsThatWouldLeaveALineWithoutALimit:
    @pytest.mark.security
    async def test_publishing_a_version_with_no_budget_is_refused_and_leaves_nothing(
        self, db
    ) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        await _binding(db, tenant, agent, bot)
        agent_id = agent.id
        before = [v.id for v in await _versions(db, agent_id)]
        pointer = agent.current_version_id
        draft = AgentSpec.model_validate({**agent.draft_spec, "budget": None})
        await AgentRegistryService(db).save_draft(tenant.ctx, agent.id, draft)

        with pytest.raises(BadRequestError) as refused:
            async with db.begin_nested():
                await AgentRegistryService(db).publish(tenant.ctx, agent.id)

        assert refused.value.details == {"channel_bot_id": str(bot.id)}
        assert [v.id for v in await _versions(db, agent_id)] == before
        assert (await AgentRegistryService(db).get(tenant.ctx, agent_id)).current_version_id == (
            pointer
        )

    @pytest.mark.security
    async def test_a_version_with_a_budget_publishes(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        await _binding(db, tenant, agent, bot)

        version = await _publish(db, tenant, agent, 9)

        assert version.version == 2

    @pytest.mark.security
    async def test_an_organization_cap_lets_a_budget_less_version_publish(self, db) -> None:
        tenant = await _tenant(db, name="Shop", monthly_budget_usd=Decimal("50"))
        agent, bot = await _line(db, tenant)
        await _binding(db, tenant, agent, bot)

        assert (await _publish(db, tenant, agent, None)).version == 2

    async def test_a_paused_binding_is_judged_too(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        await _binding(db, tenant, agent, bot, paused=True)

        with pytest.raises(BadRequestError):
            async with db.begin_nested():
                await _publish(db, tenant, agent, None)

    async def test_a_bot_that_does_not_answer_strangers_does_not_matter(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant, policy={"mode": "open"})
        await _binding(db, tenant, agent, bot)

        assert (await _publish(db, tenant, agent, None)).version == 2

    async def test_a_binding_on_an_environment_that_does_not_follow_is_not_affected(
        self, db
    ) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        dev = await _environment(db, tenant, agent, "dev", (await _versions(db, agent.id))[0])
        await _binding(db, tenant, agent, bot, environment=dev)

        assert (await _publish(db, tenant, agent, None)).version == 2

    @pytest.mark.security
    async def test_a_rollback_to_a_version_with_no_budget_is_refused(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        await _publish(db, tenant, agent, None)
        _, second = await _versions(db, agent.id)
        await _publish(db, tenant, agent, 9)
        await _binding(db, tenant, agent, bot)
        agent_id, bare_id = agent.id, second.id

        with pytest.raises(BadRequestError):
            async with db.begin_nested():
                await AgentRegistryService(db).rollback(tenant.ctx, agent_id, to_version_id=bare_id)

        await _cap(db, tenant, "50")
        rolled = await AgentRegistryService(db).rollback(
            tenant.ctx, agent_id, to_version_id=bare_id
        )
        assert rolled.version == 4

    @pytest.mark.security
    async def test_promoting_a_version_with_no_budget_into_the_binding_is_refused(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        budgeted = (await _versions(db, agent.id))[0]
        bare = await _publish(db, tenant, agent, None)
        dev = await _environment(db, tenant, agent, "dev", budgeted)
        await _binding(db, tenant, agent, bot, environment=dev)
        service = AgentEnvironmentService(db)

        with pytest.raises(BadRequestError):
            async with db.begin_nested():
                await service.update(
                    tenant.ctx, agent.id, dev.id, EnvironmentUpdate(version_id=bare.id)
                )

        await db.refresh(dev)
        assert dev.version_id == budgeted.id

        await _cap(db, tenant, "50")
        promoted = await service.update(
            tenant.ctx, agent.id, dev.id, EnvironmentUpdate(version_id=bare.id)
        )
        assert promoted.version_id == bare.id

    @pytest.mark.security
    async def test_promoting_into_the_default_judges_the_bindings_that_follow_it(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        service = AgentEnvironmentService(db)
        [production] = await service.list_for_agent(tenant.ctx, agent.id)
        await service.update(
            tenant.ctx, agent.id, production.id, EnvironmentUpdate(tracks_latest=False)
        )
        budgeted = production.version_id
        bare = await _publish(db, tenant, agent, None)
        await _binding(db, tenant, agent, bot)
        agent_id, production_id = agent.id, production.id

        with pytest.raises(BadRequestError):
            async with db.begin_nested():
                await service.update(
                    tenant.ctx, agent_id, production_id, EnvironmentUpdate(version_id=bare.id)
                )

        [after] = await service.list_for_agent(tenant.ctx, agent_id)
        assert after.version_id == budgeted
        assert (await AgentRegistryService(db).get(tenant.ctx, agent_id)).current_version_id == (
            budgeted
        )

    @pytest.mark.security
    async def test_following_the_latest_version_adopts_one_with_no_budget_and_is_refused(
        self, db
    ) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        budgeted = (await _versions(db, agent.id))[0]
        await _publish(db, tenant, agent, None)
        dev = await _environment(db, tenant, agent, "dev", budgeted)
        await _binding(db, tenant, agent, bot, environment=dev)
        service = AgentEnvironmentService(db)

        with pytest.raises(BadRequestError):
            async with db.begin_nested():
                await service.update(
                    tenant.ctx, agent.id, dev.id, EnvironmentUpdate(tracks_latest=True)
                )

        await db.refresh(dev)
        assert (dev.version_id, dev.tracks_latest) == (budgeted.id, False)

    async def test_an_edit_that_moves_no_version_is_not_judged(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        bare = await _publish(db, tenant, agent, None)
        dev = await _environment(db, tenant, agent, "dev", bare)
        await _binding(db, tenant, agent, bot, environment=dev)

        renamed = await AgentEnvironmentService(db).update(
            tenant.ctx, agent.id, dev.id, EnvironmentUpdate(name="staging")
        )

        assert renamed.name == "staging"


class TestChangesThatLeaveABindingWhereItIs:
    """A binding with no limit is not made worse by a change that does not move it."""

    @staticmethod
    async def _unbounded_binding(db, tenant: Tenant):
        """A binding pinned to a version with no budget, on an organization with no cap."""
        agent, bot = await _line(db, tenant)
        budgeted = (await _versions(db, agent.id))[0]
        bare = await _publish(db, tenant, agent, None)
        pinned = await _environment(db, tenant, agent, "pinned", bare)
        await _binding(db, tenant, agent, bot, environment=pinned)
        return agent, budgeted, bare

    @pytest.mark.security
    async def test_a_publish_with_a_budget_goes_through(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, _, _ = await self._unbounded_binding(db, tenant)

        assert (await _publish(db, tenant, agent, 9)).version == 3

    @pytest.mark.security
    async def test_a_publish_with_no_budget_that_does_not_move_it_goes_through(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, _, _ = await self._unbounded_binding(db, tenant)

        assert (await _publish(db, tenant, agent, None)).version == 3

    @pytest.mark.security
    async def test_a_rollback_that_does_not_move_it_goes_through(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, budgeted, _ = await self._unbounded_binding(db, tenant)

        rolled = await AgentRegistryService(db).rollback(
            tenant.ctx, agent.id, to_version_id=budgeted.id
        )

        assert rolled.version == 3

    @pytest.mark.security
    async def test_promoting_another_environment_goes_through(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, budgeted, bare = await self._unbounded_binding(db, tenant)
        other = await _environment(db, tenant, agent, "other", budgeted)

        promoted = await AgentEnvironmentService(db).update(
            tenant.ctx, agent.id, other.id, EnvironmentUpdate(version_id=bare.id)
        )

        assert promoted.version_id == bare.id

    @pytest.mark.security
    async def test_deleting_another_environment_goes_through(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, budgeted, _ = await self._unbounded_binding(db, tenant)
        other = await _environment(db, tenant, agent, "other", budgeted)

        await AgentEnvironmentService(db).delete(tenant.ctx, agent.id, other.id)

    @pytest.mark.security
    async def test_a_publish_with_no_budget_that_does_move_a_binding_is_refused(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, _, _ = await self._unbounded_binding(db, tenant)
        following = await _bot(db, tenant, policy=OPEN)
        await _binding(db, tenant, agent, following)
        followed = following.id

        with pytest.raises(BadRequestError) as refused:
            async with db.begin_nested():
                await _publish(db, tenant, agent, None)

        assert refused.value.details == {"channel_bot_id": str(followed)}


class TestDeletingTheEnvironmentABindingServes:
    @pytest.mark.security
    async def test_deleting_an_environment_that_would_leave_a_line_without_a_limit_is_refused(
        self, db
    ) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        budgeted = (await _versions(db, agent.id))[0]
        await _publish(db, tenant, agent, None)
        dev = await _environment(db, tenant, agent, "dev", budgeted)
        binding = await _binding(db, tenant, agent, bot, environment=dev)

        with pytest.raises(BadRequestError) as refused:
            await AgentEnvironmentService(db).delete(tenant.ctx, agent.id, dev.id)

        assert refused.value.details == {"channel_bot_id": str(bot.id)}
        await db.refresh(binding)
        assert binding.environment_id == dev.id

    @pytest.mark.security
    async def test_an_organization_cap_lets_it_go_and_the_binding_falls_back(self, db) -> None:
        tenant = await _tenant(db, name="Shop", monthly_budget_usd=Decimal("50"))
        agent, bot = await _line(db, tenant)
        budgeted = (await _versions(db, agent.id))[0]
        await _publish(db, tenant, agent, None)
        dev = await _environment(db, tenant, agent, "dev", budgeted)
        binding = await _binding(db, tenant, agent, bot, environment=dev)

        await AgentEnvironmentService(db).delete(tenant.ctx, agent.id, dev.id)

        await db.refresh(binding)
        assert binding.environment_id is None

    @pytest.mark.security
    async def test_a_default_version_with_a_budget_lets_it_go(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant)
        bare = await _publish(db, tenant, agent, None)
        dev = await _environment(db, tenant, agent, "dev", bare)
        await _publish(db, tenant, agent, 9)
        binding = await _binding(db, tenant, agent, bot, environment=dev)

        await AgentEnvironmentService(db).delete(tenant.ctx, agent.id, dev.id)

        await db.refresh(binding)
        assert binding.environment_id is None

    async def test_an_environment_no_public_line_serves_goes_freely(self, db) -> None:
        tenant = await _tenant(db, name="Shop")
        agent, bot = await _line(db, tenant, policy={"mode": "open"})
        budgeted = (await _versions(db, agent.id))[0]
        await _publish(db, tenant, agent, None)
        dev = await _environment(db, tenant, agent, "dev", budgeted)
        await _binding(db, tenant, agent, bot, environment=dev)
        other = await _environment(db, tenant, agent, "qa", budgeted)

        await AgentEnvironmentService(db).delete(tenant.ctx, agent.id, other.id)
        await AgentEnvironmentService(db).delete(tenant.ctx, agent.id, dev.id)
