"""Integration tests for guarantees only the database can make.

Everything here asserts something a mock cannot: that a ``CHECK`` rejects a row,
that a partial unique index prevents a second default, that a cascade removes
what it should. These are the promises the schema makes to the code above it,
and code that trusts an unenforced promise fails in production rather than here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.agent_exposure import AgentExposure, ExposureSurface
from app.db.models.agent_run import AgentRun, RunStatus, ToolApproval
from app.db.models.channel_bot import ChannelBot
from app.db.models.credential import ModelProfile
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.skill import Skill
from app.db.models.user import User
from app.repositories import agent_run_repo

pytestmark = pytest.mark.anyio


async def _org(db) -> Organization:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="owner")
    )
    await db.flush()
    org.owner_user = user  # type: ignore[attr-defined]  - test convenience
    return org


def _secret(org_id: uuid.UUID) -> OrganizationSecret:
    return OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=org_id,
        name="prod",
        purpose="openai",
        visibility="org",
        kind="api_key",
        sealed_secret="{}",
        hint="1234",
    )


class TestKeyLifecycle:
    """The vault is the only key store, so these are the guarantees that matter."""

    async def test_deleting_a_key_leaves_the_model_visibly_broken(self, db):
        """SET NULL, not CASCADE.

        Deleting a key must not silently delete every agent's model, nor
        silently repoint them at a different one. The profile is left keyless
        and fails loudly at resolution - which is what the "no key" marker in
        the Builder is reading.
        """
        org = await _org(db)
        secret = _secret(org.id)
        db.add(secret)
        await db.flush()

        profile = ModelProfile(
            id=uuid.uuid4(),
            organization_id=org.id,
            label="GPT-5.6",
            provider="openai",
            model="gpt-5.6-sol",
            secret_id=secret.id,
        )
        db.add(profile)
        await db.flush()

        await db.delete(secret)
        await db.flush()
        await db.refresh(profile)

        assert profile.secret_id is None

    async def test_deleting_an_organization_removes_its_keys(self, db):
        org = await _org(db)
        db.add(_secret(org.id))
        await db.flush()

        await db.delete(org)
        await db.flush()

        remaining = await db.execute(
            select(OrganizationSecret).where(OrganizationSecret.organization_id == org.id)
        )
        assert remaining.scalars().all() == []


class TestMcpConnectionOwnership:
    """Who owns a connection, enforced where it cannot be forgotten.

    The two scopes share a table, and the personal routes authorize on
    ``user_id`` alone while asking for no organization permission at all. So an
    organization row that carried a ``user_id`` would be editable and deletable
    by whoever created it - they could repoint a published agent's server at a
    host of their own. A query filter would close that; a check constraint
    closes it for every query anybody writes next.
    """

    async def test_an_organization_server_cannot_have_an_owner(self, db):
        org = await _org(db)
        db.add(
            McpConnection(
                id=uuid.uuid4(),
                organization_id=org.id,
                user_id=org.owner_user.id,
                scope="org",
                name="github",
                url="https://mcp.example.com/mcp",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_personal_connection_must_have_one(self, db):
        org = await _org(db)
        db.add(
            McpConnection(
                id=uuid.uuid4(),
                organization_id=org.id,
                user_id=None,
                scope="user",
                name="github",
                url="https://mcp.example.com/mcp",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    @staticmethod
    async def _leaver(db, org: Organization) -> User:
        """A member who can actually be deleted - not the organization's creator,
        whom the organization row still references."""
        user = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="member"
            )
        )
        await db.flush()
        return user

    async def test_an_organization_server_outlives_the_person_who_added_it(self, db):
        """SET NULL, not CASCADE.

        A shared server is the organization's, and the day its author leaves is
        exactly the day nobody is watching for a fleet of agents quietly losing
        half their tools.
        """
        org = await _org(db)
        leaver = await self._leaver(db, org)
        connection = McpConnection(
            id=uuid.uuid4(),
            organization_id=org.id,
            created_by_user_id=leaver.id,
            scope="org",
            name="github",
            url="https://mcp.example.com/mcp",
        )
        db.add(connection)
        await db.flush()

        await db.delete(leaver)
        await db.flush()
        await db.refresh(connection)

        assert connection.created_by_user_id is None

    async def test_a_personal_connection_dies_with_its_owner(self, db):
        """CASCADE, and that is the difference. A personal token belongs to one
        account and has no meaning once that account is gone."""
        org = await _org(db)
        leaver = await self._leaver(db, org)
        connection_id = uuid.uuid4()
        db.add(
            McpConnection(
                id=connection_id,
                organization_id=org.id,
                user_id=leaver.id,
                scope="user",
                name="github",
                url="https://mcp.example.com/mcp",
            )
        )
        await db.flush()

        await db.delete(leaver)
        await db.flush()

        remaining = await db.execute(select(McpConnection).where(McpConnection.id == connection_id))
        assert remaining.scalars().all() == []

    async def test_two_organizations_may_each_have_a_server_called_github(self, db):
        for org in (await _org(db), await _org(db)):
            db.add(
                McpConnection(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    scope="org",
                    name="github",
                    url="https://mcp.example.com/mcp",
                )
            )
        await db.flush()

    async def test_one_organization_may_not(self, db):
        """The name becomes the agent's tool prefix, so a duplicate inside one
        organization is two sets of tools nobody can tell apart in a spec."""
        org = await _org(db)
        for _ in range(2):
            db.add(
                McpConnection(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    scope="org",
                    name="github",
                    url="https://mcp.example.com/mcp",
                )
            )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_personal_server_of_the_same_name_is_not_a_collision(self, db):
        """Different namespaces. Refusing a member the name "github" because the
        organization uses it would be a rule nobody could see the reason for."""
        org = await _org(db)
        db.add(
            McpConnection(
                id=uuid.uuid4(),
                organization_id=org.id,
                scope="org",
                name="github",
                url="https://mcp.example.com/mcp",
            )
        )
        db.add(
            McpConnection(
                id=uuid.uuid4(),
                organization_id=org.id,
                user_id=org.owner_user.id,
                scope="user",
                name="github",
                url="https://mcp.example.com/mcp",
            )
        )
        await db.flush()


class TestAgentConstraints:
    async def test_slugs_are_unique_per_organization(self, db):
        """A slug is an @mention handle; a duplicate routes messages to the wrong agent."""
        org = await _org(db)
        for _ in range(2):
            db.add(
                Agent(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    slug="support",
                    name="Support",
                    draft_spec={},
                )
            )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_two_organizations_may_use_the_same_slug(self, db):
        first, second = await _org(db), await _org(db)
        for org in (first, second):
            db.add(
                Agent(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    slug="support",
                    name="Support",
                    draft_spec={},
                )
            )
        await db.flush()

    async def test_an_invalid_status_is_rejected(self, db):
        org = await _org(db)
        db.add(
            Agent(
                id=uuid.uuid4(),
                organization_id=org.id,
                slug="odd",
                name="Odd",
                draft_spec={},
                status="halfway",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_version_numbers_are_unique_per_agent(self, db):
        org = await _org(db)
        agent = Agent(
            id=uuid.uuid4(),
            organization_id=org.id,
            slug="support",
            name="Support",
            draft_spec={},
        )
        db.add(agent)
        await db.flush()

        for _ in range(2):
            db.add(
                AgentVersion(
                    id=uuid.uuid4(),
                    agent_id=agent.id,
                    organization_id=org.id,
                    version=1,
                    spec={},
                )
            )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_deleting_an_agent_takes_its_versions(self, db):
        org = await _org(db)
        agent = Agent(
            id=uuid.uuid4(),
            organization_id=org.id,
            slug="support",
            name="Support",
            draft_spec={},
        )
        db.add(agent)
        await db.flush()
        db.add(
            AgentVersion(
                id=uuid.uuid4(),
                agent_id=agent.id,
                organization_id=org.id,
                version=1,
                spec={},
            )
        )
        await db.flush()

        await db.delete(agent)
        await db.flush()

        remaining = await db.execute(select(AgentVersion).where(AgentVersion.agent_id == agent.id))
        assert remaining.scalars().all() == []


class TestRunAccounting:
    async def test_cost_is_stored_exactly(self, db):
        """Numeric, not float: these are summed into monthly totals that must not drift."""
        org = await _org(db)
        agent = Agent(
            id=uuid.uuid4(),
            organization_id=org.id,
            slug="support",
            name="Support",
            draft_spec={},
        )
        db.add(agent)
        await db.flush()

        run = AgentRun(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            status=RunStatus.COMPLETED.value,
            cost_usd=Decimal("0.123456"),
        )
        db.add(run)
        await db.flush()
        await db.refresh(run)

        assert run.cost_usd == Decimal("0.123456")

    async def test_a_deleted_version_does_not_take_the_run_with_it(self, db):
        """A run must not lose the record of what it executed."""
        org = await _org(db)
        agent = Agent(
            id=uuid.uuid4(),
            organization_id=org.id,
            slug="support",
            name="Support",
            draft_spec={},
        )
        db.add(agent)
        await db.flush()
        version = AgentVersion(
            id=uuid.uuid4(),
            agent_id=agent.id,
            organization_id=org.id,
            version=1,
            spec={},
        )
        db.add(version)
        await db.flush()

        run = AgentRun(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            agent_version_id=version.id,
            status=RunStatus.COMPLETED.value,
        )
        db.add(run)
        await db.flush()

        await db.delete(version)
        await db.flush()
        await db.refresh(run)

        assert run.agent_version_id is None
        assert run.status == RunStatus.COMPLETED.value

    async def test_an_invalid_approval_status_is_rejected(self, db):
        org = await _org(db)
        agent = Agent(
            id=uuid.uuid4(),
            organization_id=org.id,
            slug="support",
            name="Support",
            draft_spec={},
        )
        db.add(agent)
        await db.flush()
        run = AgentRun(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            status=RunStatus.AWAITING_APPROVAL.value,
        )
        db.add(run)
        await db.flush()

        db.add(
            ToolApproval(
                id=uuid.uuid4(),
                organization_id=org.id,
                run_id=run.id,
                agent_id=agent.id,
                tool_id="send_email",
                status="maybe",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()


class TestResourceGrants:
    async def test_a_member_has_at_most_one_grant_per_resource(self, db):
        """Two rows would make "what level does this person have" ambiguous."""
        org = await _org(db)
        resource_id = uuid.uuid4()
        for level in (GrantLevel.READ, GrantLevel.EDIT):
            db.add(
                ResourceGrant(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    subject_user_id=org.owner_user.id,
                    resource_type="agent",
                    resource_id=resource_id,
                    level=level.value,
                )
            )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_an_invalid_level_is_rejected(self, db):
        org = await _org(db)
        db.add(
            ResourceGrant(
                id=uuid.uuid4(),
                organization_id=org.id,
                subject_user_id=org.owner_user.id,
                resource_type="agent",
                resource_id=uuid.uuid4(),
                level="admin",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_removing_a_member_removes_their_grants(self, db):
        # A plain member, not the org's creator: organizations.created_by_user_id
        # is RESTRICT, so deleting the creator is refused for a different and
        # entirely correct reason.
        org = await _org(db)
        member = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        db.add(member)
        await db.flush()
        db.add(
            ResourceGrant(
                id=uuid.uuid4(),
                organization_id=org.id,
                subject_user_id=member.id,
                resource_type="agent",
                resource_id=uuid.uuid4(),
                level=GrantLevel.READ.value,
            )
        )
        await db.flush()

        await db.delete(member)
        await db.flush()

        remaining = await db.execute(
            select(ResourceGrant).where(ResourceGrant.organization_id == org.id)
        )
        assert remaining.scalars().all() == []


class TestSkillConstraints:
    async def test_names_are_unique_per_organization(self, db):
        """The name is how the model refers to a skill; two is an ambiguity."""
        org = await _org(db)
        for _ in range(2):
            db.add(
                Skill(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    name="refunds",
                    description="How refunds work",
                )
            )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_an_invalid_visibility_is_rejected(self, db):
        org = await _org(db)
        db.add(
            Skill(
                id=uuid.uuid4(),
                organization_id=org.id,
                name="refunds",
                description="How refunds work",
                visibility="everyone",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_valid_visibilities_are_accepted(self, db):
        org = await _org(db)
        for index, visibility in enumerate(Visibility):
            db.add(
                Skill(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    name=f"skill-{index}",
                    description="x",
                    visibility=visibility.value,
                )
            )
        await db.flush()


class TestAgentStatusValues:
    @pytest.mark.parametrize("status", list(AgentStatus))
    async def test_every_status_the_code_uses_is_accepted(self, db, status):
        """The enum and the check constraint must not drift apart."""
        org = await _org(db)
        db.add(
            Agent(
                id=uuid.uuid4(),
                organization_id=org.id,
                slug=f"agent-{status.value}",
                name="Agent",
                draft_spec={},
                status=status.value,
            )
        )
        await db.flush()


async def _agent(db, org: Organization, *, slug: str = "support") -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=slug,
        name="Support",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _bot(db, org: Organization, *, platform: str = "slack") -> ChannelBot:
    bot = ChannelBot(
        id=uuid.uuid4(),
        organization_id=org.id,
        platform=platform,
        name="Acme Support",
        token_encrypted="sealed",
    )
    db.add(bot)
    await db.flush()
    return bot


def _exposure(agent: Agent, bot: ChannelBot, *, surface: str = "slack") -> AgentExposure:
    return AgentExposure(
        id=uuid.uuid4(),
        organization_id=agent.organization_id,
        agent_id=agent.id,
        surface=surface,
        channel_bot_id=bot.id,
    )


class TestExposureConstraints:
    """Where an agent is available, and what the database refuses to let it be."""

    async def test_an_agent_is_bound_to_a_bot_at_most_once(self, db):
        """Two rows would make "is this available here" a question with two answers.

        Revoking would then remove one of them and leave the agent answering, which
        is the failure mode worth a constraint rather than a service check.
        """
        org = await _org(db)
        agent, bot = await _agent(db, org), await _bot(db, org)
        db.add(_exposure(agent, bot))
        await db.flush()

        db.add(_exposure(agent, bot))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_one_agent_may_answer_on_several_bots(self, db):
        org = await _org(db)
        agent = await _agent(db, org)
        for platform in ("slack", "telegram"):
            bot = await _bot(db, org, platform=platform)
            db.add(_exposure(agent, bot, surface=platform))
        await db.flush()

    @pytest.mark.parametrize("surface", list(ExposureSurface))
    async def test_every_surface_the_code_uses_is_accepted(self, db, surface):
        """The enum and the check constraint must not drift apart."""
        org = await _org(db)
        agent = await _agent(db, org)
        bot = await _bot(db, org, platform=surface.value)
        db.add(_exposure(agent, bot, surface=surface.value))
        await db.flush()

    async def test_a_surface_nothing_serves_is_rejected(self, db):
        """A binding on a platform with no adapter would look correct and route nothing."""
        org = await _org(db)
        agent, bot = await _agent(db, org), await _bot(db, org, platform="discord")
        db.add(_exposure(agent, bot, surface="discord"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_deleting_a_bot_takes_its_bindings(self, db):
        """A binding to a bot that no longer exists can only mislead whoever reads it."""
        org = await _org(db)
        agent, bot = await _agent(db, org), await _bot(db, org)
        db.add(_exposure(agent, bot))
        await db.flush()

        await db.delete(bot)
        await db.flush()

        remaining = await db.execute(
            select(AgentExposure).where(AgentExposure.agent_id == agent.id)
        )
        assert remaining.scalars().all() == []

    async def test_deleting_an_agent_takes_its_bindings(self, db):
        """Otherwise an archived agent's handle stays live in a channel."""
        org = await _org(db)
        agent, bot = await _agent(db, org), await _bot(db, org)
        db.add(_exposure(agent, bot))
        await db.flush()

        await db.delete(agent)
        await db.flush()

        remaining = await db.execute(
            select(AgentExposure).where(AgentExposure.channel_bot_id == bot.id)
        )
        assert remaining.scalars().all() == []

    async def test_two_organizations_bind_their_own_agents_independently(self, db):
        """The pair is unique globally, so a shared slug must not collide across tenants."""
        first, second = await _org(db), await _org(db)
        for org in (first, second):
            agent, bot = await _agent(db, org), await _bot(db, org)
            db.add(_exposure(agent, bot))
        await db.flush()


class TestOrganizationBudgetConstraint:
    """The organization's monthly ceiling, and the values the column refuses."""

    async def test_no_ceiling_is_the_default(self, db):
        """Every organization predating the column has none, and that must be legal.

        A cap is opt-in: a default number nobody chose would stop somebody's
        agents on a date they did not pick.
        """
        org = await _org(db)

        assert org.monthly_budget_usd is None

    async def test_a_ceiling_of_zero_is_refused(self, db):
        """Zero is not a tighter cap, it is an organization that can never answer.

        It is also one keystroke from the number somebody meant to type, which
        is why the database refuses it rather than a form.
        """
        org = await _org(db)
        org.monthly_budget_usd = Decimal("0")

        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_ceiling_survives_at_the_scale_costs_are_recorded_in(self, db):
        """The cap is compared against a sum of ``agent_runs.cost_usd``.

        Stored at a coarser scale it would round differently from the total it
        is measured against, and the two numbers would disagree in the one place
        that matters.
        """
        org = await _org(db)
        org.monthly_budget_usd = Decimal("12.345678")
        await db.flush()
        await db.refresh(org)

        assert org.monthly_budget_usd == Decimal("12.345678")


class TestExposureBudgets:
    """The ceilings a binding runs under, and what the database refuses."""

    @pytest.mark.parametrize("column", ["max_per_run_usd", "monthly_usd"])
    @pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1")])
    async def test_a_cap_of_zero_or_less_is_rejected(self, db, column, amount):
        """Not a tighter limit - a binding that can never answer.

        Somebody arrives at it by clearing a field rather than by deciding to,
        which is exactly the kind of value a constraint should catch rather than
        a form.
        """
        org = await _org(db)
        agent, bot = await _agent(db, org), await _bot(db, org)
        exposure = _exposure(agent, bot)
        setattr(exposure, column, amount)
        db.add(exposure)
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_binding_may_carry_no_cap_at_all(self, db):
        """Binding an agent to a bot is not the same act as budgeting it."""
        org = await _org(db)
        agent, bot = await _agent(db, org), await _bot(db, org)
        db.add(_exposure(agent, bot))
        await db.flush()

    async def test_spend_is_summed_for_one_binding_and_not_the_organization(self, db):
        """The property that makes an exposure's cap a cap.

        Measured against the organization's total it would be exhausted by
        unrelated internal traffic, while this binding's own spend stayed
        invisible in it.
        """
        org = await _org(db)
        agent, bot = await _agent(db, org), await _bot(db, org)
        exposure = _exposure(agent, bot)
        db.add(exposure)
        await db.flush()

        started = datetime.now(UTC)
        for cost, exposure_id in (
            (Decimal("1.50"), exposure.id),
            (Decimal("0.25"), exposure.id),
            (Decimal("99.00"), None),
        ):
            db.add(
                AgentRun(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    agent_id=agent.id,
                    exposure_id=exposure_id,
                    status=RunStatus.COMPLETED.value,
                    cost_usd=cost,
                    started_at=started,
                )
            )
        await db.flush()

        total = await agent_run_repo.sum_cost_since(
            db,
            organization_id=org.id,
            since=started - timedelta(minutes=1),
            exposure_id=exposure.id,
        )

        assert total == Decimal("1.75")

    async def test_one_organizations_binding_cannot_meter_anothers_runs(self, db):
        """Both filters, not either: the tenant boundary holds even given an id."""
        mine, theirs = await _org(db), await _org(db)
        my_agent, my_bot = await _agent(db, mine), await _bot(db, mine)
        exposure = _exposure(my_agent, my_bot)
        db.add(exposure)
        await db.flush()

        started = datetime.now(UTC)
        their_agent = await _agent(db, theirs)
        db.add(
            AgentRun(
                id=uuid.uuid4(),
                organization_id=theirs.id,
                agent_id=their_agent.id,
                status=RunStatus.COMPLETED.value,
                cost_usd=Decimal("50.00"),
                started_at=started,
            )
        )
        await db.flush()

        total = await agent_run_repo.sum_cost_since(
            db,
            organization_id=theirs.id,
            since=started - timedelta(minutes=1),
            exposure_id=exposure.id,
        )

        assert total == Decimal("0")

    async def test_deleting_a_binding_keeps_the_record_of_what_it_spent(self, db):
        """A run that happened still happened, and still cost money.

        CASCADE here would delete history to tidy up a configuration change,
        and the month's total would move because somebody unbound a bot.
        """
        org = await _org(db)
        agent, bot = await _agent(db, org), await _bot(db, org)
        exposure = _exposure(agent, bot)
        db.add(exposure)
        await db.flush()

        run = AgentRun(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            exposure_id=exposure.id,
            status=RunStatus.COMPLETED.value,
            cost_usd=Decimal("2.00"),
            started_at=datetime.now(UTC),
        )
        db.add(run)
        await db.flush()

        await db.delete(exposure)
        await db.flush()
        await db.refresh(run)

        assert (run.exposure_id, run.cost_usd) == (None, Decimal("2.00"))
