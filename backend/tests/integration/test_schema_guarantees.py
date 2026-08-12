"""Integration tests for guarantees only the database can make.

Everything here asserts something a mock cannot: that a `CHECK` rejects a row,
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
from app.db.models.agent_embed import AgentEmbed
from app.db.models.agent_exposure import AgentExposure, ExposureSurface
from app.db.models.agent_run import AgentRun, RunStatus, ToolApproval
from app.db.models.channel_bot import ChannelBot
from app.db.models.conversation import Conversation
from app.db.models.credential import ModelProfile
from app.db.models.embed_visitor import EmbedVisitor
from app.db.models.ingestion_spend import IngestionSpend
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.rag_document import RAGDocument
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.skill import Skill
from app.db.models.user import User
from app.repositories import embed_visitor_repo, ingestion_spend_repo

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
    `user_id` alone while asking for no organization permission at all. So an
    organization row that carried a `user_id` would be editable and deletable
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
        """The cap is compared against a sum of `agent_runs.cost_usd`.

        Stored at a coarser scale it would round differently from the total it
        is measured against, and the two numbers would disagree in the one place
        that matters.
        """
        org = await _org(db)
        org.monthly_budget_usd = Decimal("12.345678")
        await db.flush()
        await db.refresh(org)

        assert org.monthly_budget_usd == Decimal("12.345678")


class TestIngestionSpend:
    """The half of the monthly bill that no run carries."""

    async def test_the_sum_is_one_organizations_and_one_windows(self, db):
        """The number the organization's cap is checked against: another
        tenant's ingestion and last month's must both stay out of it."""
        mine, theirs = await _org(db), await _org(db)
        now = datetime.now(UTC)
        for organization_id, cost, created_at in (
            (mine.id, Decimal("1.50"), now),
            (mine.id, Decimal("0.25"), now),
            (mine.id, Decimal("99.00"), now - timedelta(days=60)),
            (theirs.id, Decimal("50.00"), now),
        ):
            db.add(
                IngestionSpend(
                    id=uuid.uuid4(),
                    organization_id=organization_id,
                    rag_document_id=None,
                    model="text-embedding-3-large",
                    input_tokens=1000,
                    cost_usd=cost,
                    cost_is_partial=False,
                    created_at=created_at,
                )
            )
        await db.flush()

        total = await ingestion_spend_repo.sum_cost_since(
            db, organization_id=mine.id, since=now - timedelta(minutes=1)
        )

        assert total == Decimal("1.75")

    async def test_deleting_a_document_keeps_the_record_of_what_indexing_it_cost(self, db):
        """SET NULL, not CASCADE: the spend still happened, and the month's
        total must not move because somebody tidied a collection."""
        org = await _org(db)
        document = RAGDocument(
            id=uuid.uuid4(),
            collection_name="docs",
            filename="handbook.pdf",
            filetype="pdf",
            organization_id=org.id,
        )
        db.add(document)
        await db.flush()

        spend = await ingestion_spend_repo.record(
            db,
            organization_id=org.id,
            rag_document_id=document.id,
            model="text-embedding-3-large",
            input_tokens=1000,
            output_tokens=0,
            cost_usd=Decimal("0.13"),
            cost_is_partial=False,
        )

        await db.delete(document)
        await db.flush()
        await db.refresh(spend)

        assert (spend.rag_document_id, spend.cost_usd) == (None, Decimal("0.13"))


class TestExposureAttribution:
    """The run keeps the record of where it came from."""

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


class TestHostedEmbedConstraints:
    """What a page is, held by the database rather than by the service alone.

    The service refuses each of these at publish time with a message somebody can
    act on. This is the other half, for a future call site that forgets to ask: a
    page's link travels in browser history, in `Referer` headers and in every chat
    client it is pasted into, so a `jwt` page would put a visitor token through all
    three (#517) - and an allow-list on a page is either dead configuration or
    somebody's belief that it is what protects the link.
    """

    @staticmethod
    def _embed(org: Organization, agent: Agent, **overrides) -> AgentEmbed:
        kind = overrides.pop("kind", "widget")
        return AgentEmbed(
            id=uuid.uuid4(),
            organization_id=org.id,
            agent_id=agent.id,
            name="Support",
            public_key=uuid.uuid4().hex,
            kind=kind,
            config={"kind": kind},
            **overrides,
        )

    async def test_a_public_page_is_accepted(self, db):
        org = await _org(db)
        agent = await _agent(db, org)

        db.add(self._embed(org, agent, kind="page", auth_mode="public"))
        await db.flush()

    async def test_a_token_page_is_refused(self, db):
        org = await _org(db)
        agent = await _agent(db, org)

        db.add(self._embed(org, agent, kind="page", auth_mode="jwt", jwt_secret_encrypted="sealed"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_page_carrying_an_allow_list_is_refused(self, db):
        """An allow-list is a rule about other people's sites, and this one is
        ours. Stored, it would read as the thing protecting the link."""
        org = await _org(db)
        agent = await _agent(db, org)

        db.add(self._embed(org, agent, kind="page", allowed_origins=["https://acme.test"]))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_kind_nothing_serves_is_refused(self, db):
        """Three surfaces exist. A fourth value would be a row every reader
        branches on and nobody renders."""
        org = await _org(db)
        agent = await _agent(db, org)

        db.add(self._embed(org, agent, kind="carrier-pigeon"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_one_visitor_key_names_one_thread_per_embed(self, db):
        """The key is what a bookmarked link resumes by. Two rows for one key
        would make "which conversation" a question with two answers."""
        org = await _org(db)
        agent = await _agent(db, org)
        embed = self._embed(org, agent, kind="page")
        db.add(embed)
        await db.flush()

        for _ in range(2):
            db.add(EmbedVisitor(id=uuid.uuid4(), embed_id=embed.id, visitor_key="v-1"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_claiming_a_key_twice_is_not_a_conflict(self, db):
        """Two tabs on one bookmarked link share a `localStorage` key.

        Read-then-write had both miss, both insert, and the second commit violate
        the constraint above - which the socket's handler turns into "Something
        went wrong" for whichever tab lost. `claim` is one statement, so the
        second sighting is an update and both tabs get the same row.
        """
        org = await _org(db)
        agent = await _agent(db, org)
        embed = self._embed(org, agent, kind="page")
        db.add(embed)
        await db.flush()

        first = await embed_visitor_repo.claim(db, embed_id=embed.id, visitor_key="v-1")
        second = await embed_visitor_repo.claim(db, embed_id=embed.id, visitor_key="v-1")

        assert first.id == second.id
        assert second.last_seen_at is not None

    async def test_a_claim_that_finds_a_thread_keeps_it(self, db):
        """The upsert touches `last_seen_at` and nothing else. Resuming a
        conversation must not be the thing that forgets which one it was."""
        org = await _org(db)
        agent = await _agent(db, org)
        embed = self._embed(org, agent, kind="page")
        conversation = Conversation(id=uuid.uuid4(), organization_id=org.id, title="t")
        db.add_all([embed, conversation])
        await db.flush()

        claimed = await embed_visitor_repo.claim(db, embed_id=embed.id, visitor_key="v-1")
        await embed_visitor_repo.link_conversation(
            db, db_visitor=claimed, conversation_id=conversation.id
        )

        again = await embed_visitor_repo.claim(db, embed_id=embed.id, visitor_key="v-1")

        assert again.conversation_id == conversation.id

    async def test_a_second_link_keeps_the_first_thread_and_returns_it(self, db):
        """The first-message race: two tabs on one key each create a thread and
        each try to link it. The second write finds the column already set, so it
        changes nothing and the caller is handed the first thread to answer into -
        rather than detaching it and stranding the visitor's history."""
        org = await _org(db)
        agent = await _agent(db, org)
        embed = self._embed(org, agent, kind="page")
        first = Conversation(id=uuid.uuid4(), organization_id=org.id, title="first")
        second = Conversation(id=uuid.uuid4(), organization_id=org.id, title="second")
        db.add_all([embed, first, second])
        await db.flush()

        claimed = await embed_visitor_repo.claim(db, embed_id=embed.id, visitor_key="v-1")
        won = await embed_visitor_repo.link_conversation(
            db, db_visitor=claimed, conversation_id=first.id
        )
        adopted = await embed_visitor_repo.link_conversation(
            db, db_visitor=claimed, conversation_id=second.id
        )

        assert won == first.id
        assert adopted == first.id
        again = await embed_visitor_repo.claim(db, embed_id=embed.id, visitor_key="v-1")
        assert again.conversation_id == first.id

    async def test_the_same_key_may_visit_two_embeds(self, db):
        """Nothing links the two: a browser holds one key per public key, and a
        collision across embeds must not be a collision at all."""
        org = await _org(db)
        agent = await _agent(db, org)
        first, second = self._embed(org, agent, kind="page"), self._embed(org, agent, kind="page")
        db.add_all([first, second])
        await db.flush()

        db.add_all(
            [
                EmbedVisitor(id=uuid.uuid4(), embed_id=first.id, visitor_key="v-1"),
                EmbedVisitor(id=uuid.uuid4(), embed_id=second.id, visitor_key="v-1"),
            ]
        )
        await db.flush()

    async def test_a_deleted_conversation_leaves_the_visitor_able_to_start_again(self, db):
        """`SET NULL`, not `CASCADE`: a retention sweep must not delete the
        visitor along with the thread it removed."""
        org = await _org(db)
        agent = await _agent(db, org)
        embed = self._embed(org, agent, kind="page")
        conversation = Conversation(id=uuid.uuid4(), organization_id=org.id, title="t")
        db.add_all([embed, conversation])
        await db.flush()

        visitor = EmbedVisitor(
            id=uuid.uuid4(),
            embed_id=embed.id,
            visitor_key="v-1",
            conversation_id=conversation.id,
        )
        db.add(visitor)
        await db.flush()

        await db.delete(conversation)
        await db.flush()
        await db.refresh(visitor)

        assert visitor.conversation_id is None
