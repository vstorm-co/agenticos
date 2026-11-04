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
from app.db.models.agent_exposure import AgentExposure
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.channel_bot import ChannelBot
from app.schemas.channel_bot import ChannelBotCreate, ChannelBotUpdate
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
