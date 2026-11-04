"""Requests to bind an agent to a public line, on real rows (#2076).

A Builder who may publish an agent cannot decide who answers customers of a bot that
takes people with no account, so they ask. These prove what only a database can: the one
pending request per person and bot the partial unique index holds, a newer request
replacing an older one under the bot's lock, two people filing at once, a request decided
once, the cascades, and that one organization never reaches another's requests.
"""

import asyncio
import contextlib
import uuid
from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.spec import AgentSpec
from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
    RateLimitError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_exposure import AgentExposure
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.channel_binding_request import (
    BindingRequestKind,
    BindingRequestStatus,
    BindingVoidReason,
    ChannelBindingRequest,
)
from app.db.models.channel_bot import ChannelBot
from app.db.models.notification import Notification
from app.db.models.organization import OrganizationMember
from app.repositories import channel_binding_request_repo
from app.schemas.agent_environment import EnvironmentCreate
from app.services.agent_environment import AgentEnvironmentService
from app.services.channel_binding_requests import (
    ChannelBindingRequestService,
    deciders,
    file_request,
    void_for_closed_line,
    void_for_taken_bot,
)
from tests.integration.test_platform_flows import (
    Tenant,
    _join,
    _keyed_model_profile,
    _published_agent,
    _tenant,
)
from tests.integration.test_public_line_ceilings import OPEN, _bot, _bound

pytestmark = pytest.mark.anyio

NOTE = "The front desk needs this before Monday."


@dataclass
class World:
    """One organization with its owner, an admin, two builders, a bot and an agent."""

    db: AsyncSession
    tenant: Tenant
    admin: AuthContext
    builder: AuthContext
    other_builder: AuthContext
    bot: ChannelBot
    agent: Agent

    @property
    def owner(self) -> AuthContext:
        return self.tenant.ctx

    @property
    def requests(self) -> ChannelBindingRequestService:
        return ChannelBindingRequestService(self.db)

    async def file(
        self,
        who: AuthContext | None = None,
        *,
        kind: BindingRequestKind = BindingRequestKind.BIND,
        exposure_id: uuid.UUID | None = None,
        environment_id: uuid.UUID | None = None,
        note: str | None = None,
        agent: Agent | None = None,
    ) -> ChannelBindingRequest:
        return await file_request(
            self.db,
            who or self.builder,
            bot_id=self.bot.id,
            agent_id=(agent or self.agent).id,
            kind=kind,
            exposure_id=exposure_id,
            environment_id=environment_id,
            note=note,
        )

    async def all(self) -> list[ChannelBindingRequest]:
        rows = await self.db.execute(
            select(ChannelBindingRequest)
            .where(ChannelBindingRequest.organization_id == self.tenant.organization.id)
            .order_by(ChannelBindingRequest.created_at, ChannelBindingRequest.id)
        )
        return list(rows.scalars())

    async def pending(self) -> list[ChannelBindingRequest]:
        return [r for r in await self.all() if r.status == "pending"]

    async def exposures(self) -> list[AgentExposure]:
        rows = await self.db.execute(
            select(AgentExposure).where(AgentExposure.channel_bot_id == self.bot.id)
        )
        return list(rows.scalars())

    async def audits(self, action: str) -> list[AppAdminAuditLog]:
        rows = await self.db.execute(
            select(AppAdminAuditLog).where(
                AppAdminAuditLog.organization_id == self.tenant.organization.id,
                AppAdminAuditLog.action == action,
            )
        )
        return list(rows.scalars())

    async def told(self, event_type: str) -> list[Notification]:
        rows = await self.db.execute(
            select(Notification).where(
                Notification.event_type == event_type,
                Notification.organization_id == self.tenant.organization.id,
            )
        )
        return list(rows.scalars())


async def _world(
    db: AsyncSession,
    *,
    policy: dict | None = None,
    cap: str | None = "50",
    budget: float | None = None,
) -> World:
    tenant = await _tenant(
        db, name="Shop", monthly_budget_usd=None if cap is None else Decimal(cap)
    )
    await _keyed_model_profile(db, tenant)
    spec = AgentSpec(
        name=f"Support {uuid.uuid4().hex[:6]}",
        budget=None if budget is None else {"monthly_usd": budget},
    )
    return World(
        db=db,
        tenant=tenant,
        admin=await _join(db, tenant, OrgRoleName.ADMIN),
        builder=await _join(db, tenant, OrgRoleName.BUILDER),
        other_builder=await _join(db, tenant, OrgRoleName.BUILDER),
        bot=await _bot(db, tenant, policy=policy),
        agent=await _published_agent(db, tenant, spec=spec),
    )


async def _binding(world: World, *, paused: bool = False, environment=None) -> AgentExposure:
    exposure = _bound(world.tenant, world.agent, world.bot, paused=paused, environment=environment)
    world.db.add(exposure)
    await world.db.flush()
    return exposure


class TestTheTable:
    async def test_a_request_round_trips(self, db: AsyncSession) -> None:
        world = await _world(db)

        request = await world.file(note=NOTE)

        await db.refresh(request)
        assert (request.kind, request.status, request.note) == ("bind", "pending", NOTE)
        assert request.organization_id == world.tenant.organization.id
        assert request.channel_bot_id == world.bot.id and request.agent_id == world.agent.id
        assert request.exposure_id is None and request.environment_id is None
        assert request.requester_user_id == world.builder.user_id
        assert request.void_reason is None and request.decided_at is None

    async def test_a_second_pending_request_by_the_same_person_is_refused_by_the_index(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        await world.file()

        with pytest.raises(IntegrityError, match="uq_channel_binding_request_pending"):
            async with db.begin_nested():
                await channel_binding_request_repo.create(
                    db,
                    organization_id=world.tenant.organization.id,
                    channel_bot_id=world.bot.id,
                    agent_id=world.agent.id,
                    kind="bind",
                    requester_user_id=world.builder.user_id,
                )

    async def test_another_person_or_a_settled_request_does_not_block_a_new_one(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        first = await world.file()
        await channel_binding_request_repo.settle(
            db, first, status=BindingRequestStatus.DECLINED, decided_by_user_id=world.admin.user_id
        )

        again = await world.file()
        other = await world.file(world.other_builder)

        assert {r.id for r in await world.pending()} == {again.id, other.id}

    @pytest.mark.parametrize("parent", ["bot", "agent", "exposure"])
    async def test_deleting_what_it_is_about_removes_it(
        self, db: AsyncSession, parent: str
    ) -> None:
        world = await _world(db)
        exposure = await _binding(world, paused=True)
        await world.file(kind=BindingRequestKind.RESUME, exposure_id=exposure.id)
        target = {"bot": ChannelBot, "agent": Agent, "exposure": AgentExposure}[parent]
        target_id = {"bot": world.bot.id, "agent": world.agent.id, "exposure": exposure.id}[parent]

        await db.execute(delete(target).where(target.id == target_id))

        assert await world.all() == []

    async def test_deleting_the_environment_removes_the_request(self, db: AsyncSession) -> None:
        world = await _world(db)
        agent_version = await db.scalar(
            select(Agent.current_version_id).where(Agent.id == world.agent.id)
        )
        environment = await AgentEnvironmentService(db).create(
            world.owner, world.agent.id, EnvironmentCreate(name="staging", version_id=agent_version)
        )
        await world.file(environment_id=environment.id)

        await db.execute(delete(type(environment)).where(type(environment).id == environment.id))

        assert await world.all() == []

    async def test_a_note_past_the_cap_is_refused_by_the_table(self, db: AsyncSession) -> None:
        world = await _world(db)

        with pytest.raises(IntegrityError, match="ck_channel_binding_request_note"):
            async with db.begin_nested():
                await world.file(note="x" * 501)

        assert (await world.file(note="x" * 500)).note == "x" * 500

    @pytest.mark.security
    async def test_a_request_is_read_and_listed_inside_its_own_organization_only(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        request = await world.file()
        elsewhere = await _tenant(db, name="Elsewhere")

        assert (
            await channel_binding_request_repo.get(
                db, request.id, organization_id=elsewhere.organization.id
            )
            is None
        )
        assert (
            await channel_binding_request_repo.lock(
                db, request.id, organization_id=elsewhere.organization.id
            )
            is None
        )
        assert await channel_binding_request_repo.list_pending(
            db, organization_id=elsewhere.organization.id, skip=0, limit=50
        ) == ([], 0)
        assert (
            await channel_binding_request_repo.list_for_agent(
                db, organization_id=elsewhere.organization.id, agent_id=world.agent.id
            )
            == []
        )
        listed, total = await channel_binding_request_repo.list_pending(
            db, organization_id=world.tenant.organization.id, skip=0, limit=50
        )
        assert ([r.id for r in listed], total) == ([request.id], 1)
        assert [
            r.id
            for r in await channel_binding_request_repo.list_for_agent(
                db, organization_id=world.tenant.organization.id, agent_id=world.agent.id
            )
        ] == [request.id]

    @pytest.mark.security
    async def test_voiding_a_bots_requests_stays_inside_the_organization(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        request = await world.file()
        elsewhere = await _tenant(db, name="Elsewhere")

        none = await channel_binding_request_repo.void_pending_for_bot(
            db,
            organization_id=elsewhere.organization.id,
            channel_bot_id=world.bot.id,
            reason=BindingVoidReason.LINE_CLOSED,
        )
        some = await channel_binding_request_repo.void_pending_for_bot(
            db,
            organization_id=world.tenant.organization.id,
            channel_bot_id=world.bot.id,
            reason=BindingVoidReason.LINE_CLOSED,
        )

        await db.refresh(request)
        assert (none, some) == (0, 1)
        assert (request.status, request.void_reason) == ("voided", "line_closed")

    async def test_the_pagination_of_the_pending_list(self, db: AsyncSession) -> None:
        world = await _world(db)
        await world.file()
        await world.file(world.other_builder)

        page, total = await channel_binding_request_repo.list_pending(
            db, organization_id=world.tenant.organization.id, skip=1, limit=1
        )

        assert (len(page), total) == (1, 2)


class TestFiling:
    @pytest.mark.security
    async def test_it_writes_the_row_audits_it_and_tells_the_deciders_only(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        elsewhere = await _tenant(db, name="Elsewhere")

        request = await world.file(note=NOTE)

        membership = await db.scalar(
            select(OrganizationMember.id).where(
                OrganizationMember.user_id == world.builder.user_id,
                OrganizationMember.organization_id == world.tenant.organization.id,
            )
        )
        assert request.requester_membership_id == membership
        [audit] = await world.audits("channel.binding_requested")
        assert audit.actor_user_id == world.builder.user_id
        assert audit.details == {
            "request_id": str(request.id),
            "kind": "bind",
            "agent_id": str(world.agent.id),
            "channel_bot_id": str(world.bot.id),
        }
        told = await world.told("channel_binding_requested")
        assert {row.recipient_user_id for row in told} == {
            world.owner.user_id,
            world.admin.user_id,
        }
        assert elsewhere.user.id not in {row.recipient_user_id for row in told}
        for row in told:
            assert world.agent.name in row.summary and world.bot.name in row.summary
            assert NOTE not in row.summary and NOTE not in str(row.render_context)
            assert row.occurrence_id == str(request.id)

    async def test_the_deciders_are_the_owners_and_admins_of_the_organization(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        await _tenant(db, name="Elsewhere")

        found = await deciders(db, world.tenant.organization.id)

        assert set(found) == {world.owner.user_id, world.admin.user_id}

    async def test_a_decider_who_files_is_not_told_of_their_own_request(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)

        await world.file(world.admin)

        told = await world.told("channel_binding_requested")
        assert {row.recipient_user_id for row in told} == {world.owner.user_id}

    async def test_a_lone_decider_who_files_tells_nobody(self, db: AsyncSession) -> None:
        world = await _world(db)
        await db.execute(
            update(OrganizationMember)
            .where(OrganizationMember.user_id == world.admin.user_id)
            .values(role="builder")
        )

        request = await world.file(world.owner)

        assert [r.id for r in await world.pending()] == [request.id]
        assert await world.told("channel_binding_requested") == []

    async def test_a_second_filing_replaces_the_first(self, db: AsyncSession) -> None:
        world = await _world(db)
        first = await world.file(note="first")

        second = await world.file(note="second")

        await db.refresh(first)
        assert (first.status, first.void_reason) == ("voided", "replaced")
        assert first.decided_at is not None and first.decided_by_user_id is None
        assert [r.id for r in await world.pending()] == [second.id]

    async def test_another_persons_pending_request_is_kept(self, db: AsyncSession) -> None:
        world = await _world(db)
        mine = await world.file()

        theirs = await world.file(world.other_builder)

        assert {r.id for r in await world.pending()} == {mine.id, theirs.id}

    @pytest.mark.security
    async def test_past_the_hourly_allowance_it_is_refused_and_the_earlier_one_stands(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "RATE_LIMIT_ARTIFACT_SHARE_REQUESTS_PER_HOUR", 1)
        world = await _world(db)
        first = await world.file()

        with pytest.raises(RateLimitError):
            await world.file(note="again")

        assert [r.id for r in await world.pending()] == [first.id]

    @pytest.mark.security
    async def test_a_bot_agent_exposure_or_environment_of_another_organization_is_not_found(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        elsewhere = await _world(db)
        foreign_exposure = await _binding(elsewhere)
        foreign_version = await db.scalar(
            select(Agent.current_version_id).where(Agent.id == elsewhere.agent.id)
        )
        foreign_environment = await AgentEnvironmentService(db).create(
            elsewhere.owner,
            elsewhere.agent.id,
            EnvironmentCreate(name="staging", version_id=foreign_version),
        )

        with pytest.raises(NotFoundError):
            await file_request(
                db,
                world.builder,
                bot_id=elsewhere.bot.id,
                agent_id=world.agent.id,
                kind=BindingRequestKind.BIND,
            )
        with pytest.raises(NotFoundError):
            await world.file(agent=elsewhere.agent)
        with pytest.raises(NotFoundError):
            await world.file(kind=BindingRequestKind.RESUME, exposure_id=foreign_exposure.id)
        with pytest.raises(NotFoundError):
            await world.file(environment_id=foreign_environment.id)

        assert await world.all() == []
        assert await world.told("channel_binding_requested") == []

    async def test_an_exposure_of_another_bot_is_not_found(self, db: AsyncSession) -> None:
        world = await _world(db)
        other_bot = await _bot(db, world.tenant)
        elsewhere_binding = _bound(world.tenant, world.agent, other_bot, paused=True)
        db.add(elsewhere_binding)
        await db.flush()

        with pytest.raises(NotFoundError):
            await world.file(kind=BindingRequestKind.RESUME, exposure_id=elsewhere_binding.id)

    async def test_an_environment_of_another_agent_is_not_found(self, db: AsyncSession) -> None:
        world = await _world(db)
        rival = await _published_agent(db, world.tenant, spec=AgentSpec(name="Rival"))
        version = await db.scalar(select(Agent.current_version_id).where(Agent.id == rival.id))
        theirs = await AgentEnvironmentService(db).create(
            world.owner, rival.id, EnvironmentCreate(name="staging", version_id=version)
        )

        with pytest.raises(NotFoundError):
            await world.file(environment_id=theirs.id)

    @pytest.mark.parametrize(
        "fields",
        [
            {"kind": BindingRequestKind.ENVIRONMENT},
            {"kind": BindingRequestKind.RESUME},
            {"kind": BindingRequestKind.BIND, "with_exposure": True},
            {"kind": BindingRequestKind.RESUME, "with_exposure": True, "with_environment": True},
        ],
    )
    async def test_a_kind_that_does_not_match_its_ids_is_refused_before_the_allowance_is_spent(
        self, db: AsyncSession, monkeypatch: pytest.MonkeyPatch, fields: dict
    ) -> None:
        monkeypatch.setattr(settings, "RATE_LIMIT_ARTIFACT_SHARE_REQUESTS_PER_HOUR", 1)
        world = await _world(db)
        exposure = await _binding(world, paused=True)
        version = await db.scalar(
            select(Agent.current_version_id).where(Agent.id == world.agent.id)
        )
        staging = await AgentEnvironmentService(db).create(
            world.owner, world.agent.id, EnvironmentCreate(name="staging", version_id=version)
        )

        with pytest.raises(BadRequestError) as refused:
            await world.file(
                kind=fields["kind"],
                exposure_id=exposure.id if fields.get("with_exposure") else None,
                environment_id=staging.id if fields.get("with_environment") else None,
            )

        assert refused.value.details["kind"] == fields["kind"].value
        assert await world.all() == []
        assert (await world.file(kind=BindingRequestKind.RESUME, exposure_id=exposure.id)).id


class TestFilingAtOnce:
    async def test_two_filings_at_once_leave_one_pending(
        self, db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = await _world(db)
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        reached = asyncio.Event()
        arrivals: list[None] = []
        original = channel_binding_request_repo.pending_for

        async def meeting(*args, **kwargs):
            """Hold each filing where it reads the earlier request until the other has
            read too; held back by the bot's lock, the second never arrives, and the
            first goes on after a moment."""
            arrivals.append(None)
            if len(arrivals) == 2:
                reached.set()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(reached.wait(), timeout=0.5)
            return await original(*args, **kwargs)

        monkeypatch.setattr(channel_binding_request_repo, "pending_for", meeting)

        async def file(note: str) -> uuid.UUID:
            async with factory() as session:
                request = await file_request(
                    session,
                    world.builder,
                    bot_id=world.bot.id,
                    agent_id=world.agent.id,
                    kind=BindingRequestKind.BIND,
                    note=note,
                )
                await session.commit()
                return request.id

        async with asyncio.timeout(20):
            first, second = await asyncio.gather(file("a"), file("b"))

        rows = (
            (
                await db.execute(
                    select(ChannelBindingRequest)
                    .where(ChannelBindingRequest.channel_bot_id == world.bot.id)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        assert {r.id for r in rows} == {first, second}
        assert sorted(r.status for r in rows) == ["pending", "voided"]
        [voided] = [r for r in rows if r.status == "voided"]
        assert voided.void_reason == "replaced"


class TestApprovingAtOnce:
    async def test_two_managers_approving_one_request_at_once_apply_it_once(
        self, db: AsyncSession, engine: AsyncEngine
    ) -> None:
        world = await _world(db)
        exposure = await _binding(world, paused=True)
        request = await world.file(kind=BindingRequestKind.RESUME, exposure_id=exposure.id)
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        first_has_read = asyncio.Event()
        second_may_go = asyncio.Event()
        original = channel_binding_request_repo.get
        reads = 0

        async def staggered(*args, **kwargs):
            """Let the second approval read the request as pending before the first one
            has decided it, so only a re-read under the lock can tell them apart."""
            nonlocal reads
            reads += 1
            mine = reads
            found = await original(*args, **kwargs)
            if mine == 1:
                first_has_read.set()
            else:
                await first_has_read.wait()
                await asyncio.sleep(0.3)
                second_may_go.set()
            return found

        async def approve(who: AuthContext):
            async with factory() as session:
                try:
                    settled = await ChannelBindingRequestService(session).approve(who, request.id)
                    await session.commit()
                    return settled.id
                except ConcurrentChangeError as refused:
                    await session.rollback()
                    return refused

        with patch.object(channel_binding_request_repo, "get", staggered):
            async with asyncio.timeout(20):
                outcomes = await asyncio.gather(approve(world.admin), approve(world.owner))

        done = [o for o in outcomes if isinstance(o, uuid.UUID)]
        refused = [o for o in outcomes if isinstance(o, ConcurrentChangeError)]
        assert (len(done), len(refused)) == (1, 1)
        await db.rollback()
        assert len(await world.audits("channel.binding_request_approved")) == 1
        assert len(await world.told("channel_binding_decided")) == 1
        statuses = await db.scalars(
            select(ChannelBindingRequest.status).where(ChannelBindingRequest.id == request.id)
        )
        assert list(statuses) == ["approved"]


class TestApproving:
    async def test_a_binding_is_applied_as_the_approver(self, db: AsyncSession) -> None:
        world = await _world(db)
        request = await world.file()

        settled = await world.requests.approve(world.admin, request.id)

        [exposure] = await world.exposures()
        assert exposure.agent_id == world.agent.id
        assert exposure.created_by_user_id == world.admin.user_id
        assert exposure.is_active is True and exposure.environment_id is None
        assert (settled.status, settled.decided_by_user_id) == ("approved", world.admin.user_id)
        assert settled.decided_at is not None
        [audit] = await world.audits("channel.binding_request_approved")
        assert audit.actor_user_id == world.admin.user_id
        assert audit.details == {
            "request_id": str(request.id),
            "kind": "bind",
            "requester": str(world.builder.user_id),
            "agent_id": str(world.agent.id),
            "channel_bot_id": str(world.bot.id),
        }
        [exposed] = await world.audits("agent.exposed")
        assert exposed.actor_user_id == world.admin.user_id
        [told] = await world.told("channel_binding_decided")
        assert told.recipient_user_id == world.builder.user_id
        assert world.agent.name in told.summary and world.bot.name in told.summary
        assert "approved" in told.summary

    async def test_a_binding_request_with_an_environment_binds_to_it(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        version = await db.scalar(
            select(Agent.current_version_id).where(Agent.id == world.agent.id)
        )
        staging = await AgentEnvironmentService(db).create(
            world.owner, world.agent.id, EnvironmentCreate(name="staging", version_id=version)
        )
        request = await world.file(environment_id=staging.id)

        await world.requests.approve(world.owner, request.id)

        [exposure] = await world.exposures()
        assert exposure.environment_id == staging.id

    async def test_an_environment_change_is_applied_and_keeps_the_original_creator(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        exposure = await _binding(world)
        version = await db.scalar(
            select(Agent.current_version_id).where(Agent.id == world.agent.id)
        )
        staging = await AgentEnvironmentService(db).create(
            world.owner, world.agent.id, EnvironmentCreate(name="staging", version_id=version)
        )
        request = await world.file(
            kind=BindingRequestKind.ENVIRONMENT,
            exposure_id=exposure.id,
            environment_id=staging.id,
        )

        await world.requests.approve(world.admin, request.id)

        await db.refresh(exposure)
        assert exposure.environment_id == staging.id
        assert exposure.created_by_user_id == world.owner.user_id

    async def test_a_change_back_to_the_default_environment_is_applied(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        version = await db.scalar(
            select(Agent.current_version_id).where(Agent.id == world.agent.id)
        )
        staging = await AgentEnvironmentService(db).create(
            world.owner, world.agent.id, EnvironmentCreate(name="staging", version_id=version)
        )
        exposure = await _binding(world, environment=staging)
        request = await world.file(
            kind=BindingRequestKind.ENVIRONMENT, exposure_id=exposure.id, environment_id=None
        )

        await world.requests.approve(world.admin, request.id)

        await db.refresh(exposure)
        assert exposure.environment_id is None

    async def test_a_paused_binding_is_resumed(self, db: AsyncSession) -> None:
        world = await _world(db)
        exposure = await _binding(world, paused=True)
        request = await world.file(kind=BindingRequestKind.RESUME, exposure_id=exposure.id)

        await world.requests.approve(world.admin, request.id)

        await db.refresh(exposure)
        assert exposure.is_active is True

    @pytest.mark.security
    async def test_it_is_refused_like_the_binding_itself_when_no_spending_limit_exists(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db, policy=OPEN, cap=None, budget=None)
        request = await world.file()

        with pytest.raises(BadRequestError) as refused:
            await world.requests.approve(world.admin, request.id)

        assert "needs a spending limit" in refused.value.message
        assert await world.exposures() == []
        assert [r.id for r in await world.pending()] == [request.id]
        assert await world.told("channel_binding_decided") == []
        assert await world.audits("channel.binding_request_approved") == []

    @pytest.mark.security
    async def test_a_second_approve_of_the_same_request_is_refused(self, db: AsyncSession) -> None:
        world = await _world(db)
        request = await world.file()
        await world.requests.approve(world.admin, request.id)

        with pytest.raises(ConcurrentChangeError):
            await world.requests.approve(world.owner, request.id)

        assert len(await world.exposures()) == 1
        assert len(await world.told("channel_binding_decided")) == 1

    @pytest.mark.security
    async def test_a_declined_request_cannot_be_approved_and_an_approved_one_cannot_be_declined(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        declined = await world.file()
        approved = await world.file(world.other_builder)
        await world.requests.decline(world.admin, declined.id)
        await world.requests.approve(world.admin, approved.id)

        with pytest.raises(ConcurrentChangeError):
            await world.requests.approve(world.admin, declined.id)
        with pytest.raises(ConcurrentChangeError):
            await world.requests.decline(world.admin, approved.id)

    @pytest.mark.security
    async def test_a_requester_whose_membership_changed_since_is_refused_and_nothing_applies(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        request = await world.file()
        await db.execute(
            delete(OrganizationMember).where(
                OrganizationMember.user_id == world.builder.user_id,
                OrganizationMember.organization_id == world.tenant.organization.id,
            )
        )
        db.add(
            OrganizationMember(
                id=uuid.uuid4(),
                organization_id=world.tenant.organization.id,
                user_id=world.builder.user_id,
                role="builder",
            )
        )
        await db.flush()

        with pytest.raises(ConcurrentChangeError):
            await world.requests.approve(world.admin, request.id)

        assert await world.exposures() == []
        assert [r.id for r in await world.pending()] == [request.id]

    @pytest.mark.security
    async def test_a_requester_who_left_is_refused(self, db: AsyncSession) -> None:
        world = await _world(db)
        request = await world.file()
        await db.execute(
            delete(OrganizationMember).where(
                OrganizationMember.user_id == world.builder.user_id,
                OrganizationMember.organization_id == world.tenant.organization.id,
            )
        )

        with pytest.raises(ConcurrentChangeError):
            await world.requests.approve(world.admin, request.id)

        assert await world.exposures() == []

    @pytest.mark.security
    async def test_a_bot_taken_by_another_agent_is_refused_and_nothing_commits(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        request = await world.file()
        rival = await _published_agent(db, world.tenant, spec=AgentSpec(name="Rival"))
        taken = _bound(world.tenant, rival, world.bot)
        db.add(taken)
        await db.flush()

        with pytest.raises(ConcurrentChangeError):
            async with db.begin_nested():
                await world.requests.approve(world.admin, request.id)

        await db.refresh(request)
        assert request.status == "pending"
        assert [e.agent_id for e in await world.exposures()] == [rival.id]
        assert await world.told("channel_binding_decided") == []
        assert await world.audits("channel.binding_request_approved") == []

    async def test_approving_a_binding_voids_the_other_requests_for_the_bot(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        rival = await _published_agent(db, world.tenant, spec=AgentSpec(name="Rival"))
        chosen = await world.file()
        others = await world.file(world.other_builder, agent=rival)

        await world.requests.approve(world.admin, chosen.id)

        await db.refresh(others)
        assert (others.status, others.void_reason) == ("voided", "bot_taken")

    @pytest.mark.security
    async def test_a_request_of_another_organization_is_not_found(self, db: AsyncSession) -> None:
        world = await _world(db)
        elsewhere = await _world(db)
        request = await world.file()

        with pytest.raises(NotFoundError):
            await elsewhere.requests.approve(elsewhere.admin, request.id)
        with pytest.raises(NotFoundError):
            await elsewhere.requests.decline(elsewhere.admin, request.id)

        await db.refresh(request)
        assert request.status == "pending"
        assert await world.exposures() == []
        listed, total = await elsewhere.requests.list_pending(elsewhere.admin, 0, 50)
        assert (listed, total) == ([], 0)

    @pytest.mark.security
    async def test_only_a_channels_manager_decides(self, db: AsyncSession) -> None:
        world = await _world(db)
        request = await world.file()

        for refused in (
            world.requests.approve(world.builder, request.id),
            world.requests.decline(world.builder, request.id),
            world.requests.approve(world.other_builder, request.id),
            world.requests.list_pending(world.builder, 0, 50),
        ):
            with pytest.raises(AuthorizationError):
                await refused

        await db.refresh(request)
        assert request.status == "pending"
        assert await world.exposures() == []


class TestDeclining:
    async def test_it_settles_audits_tells_the_requester_and_applies_nothing(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        request = await world.file()

        settled = await world.requests.decline(world.admin, request.id)

        assert (settled.status, settled.decided_by_user_id) == ("declined", world.admin.user_id)
        assert await world.exposures() == []
        [audit] = await world.audits("channel.binding_request_declined")
        assert audit.actor_user_id == world.admin.user_id
        assert audit.details["request_id"] == str(request.id)
        [told] = await world.told("channel_binding_decided")
        assert told.recipient_user_id == world.builder.user_id
        assert "declined" in told.summary
        assert world.agent.name in told.summary and world.bot.name in told.summary


class TestListing:
    async def test_a_manager_sees_the_pending_requests_with_their_notes(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        request = await world.file(note=NOTE)
        settled = await world.file(world.other_builder)
        await world.requests.decline(world.admin, settled.id)

        listed, total = await world.requests.list_pending(world.admin, 0, 50)

        assert ([r.id for r in listed], total) == ([request.id], 1)
        assert listed[0].note == NOTE

    async def test_the_requests_of_an_agent_need_the_right_to_see_it(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        request = await world.file()
        elsewhere = await _world(db)

        mine = await world.requests.list_for_agent(world.builder, world.agent.id)

        assert [r.id for r in mine] == [request.id]
        with pytest.raises(NotFoundError):
            await elsewhere.requests.list_for_agent(elsewhere.builder, world.agent.id)

    @pytest.mark.security
    async def test_a_member_who_can_see_the_agent_sees_only_their_own_requests(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        mine = await world.file(world.builder, note="mine")
        theirs = await world.file(world.other_builder, note="theirs")

        seen_by_builder = await world.requests.list_for_agent(world.builder, world.agent.id)
        seen_by_other = await world.requests.list_for_agent(world.other_builder, world.agent.id)
        seen_by_manager = await world.requests.list_for_agent(world.admin, world.agent.id)

        assert [r.id for r in seen_by_builder] == [mine.id]
        assert [r.id for r in seen_by_other] == [theirs.id]
        assert {r.id for r in seen_by_manager} == {mine.id, theirs.id}


class TestVoiding:
    async def test_a_closing_line_voids_what_waits_for_it(self, db: AsyncSession) -> None:
        world = await _world(db)
        first = await world.file()
        second = await world.file(world.other_builder)
        settled = await world.file(world.owner)
        await world.requests.decline(world.admin, settled.id)

        count = await void_for_closed_line(
            db, organization_id=world.tenant.organization.id, channel_bot_id=world.bot.id
        )

        assert count == 2
        for request in (first, second):
            await db.refresh(request)
            assert (request.status, request.void_reason) == ("voided", "line_closed")
        await db.refresh(settled)
        assert settled.status == "declined"

    async def test_another_agent_taking_the_bot_voids_what_waits(self, db: AsyncSession) -> None:
        world = await _world(db)
        request = await world.file()

        count = await void_for_taken_bot(
            db, organization_id=world.tenant.organization.id, channel_bot_id=world.bot.id
        )

        await db.refresh(request)
        assert count == 1
        assert (request.status, request.void_reason) == ("voided", "bot_taken")
