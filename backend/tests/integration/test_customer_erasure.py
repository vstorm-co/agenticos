"""Erasing a WhatsApp customer, against Postgres (#2076).

A customer is the business-scoped id Meta gave one organization's bots. Every
store that holds something about them goes, in one transaction; the runs stay as
accounting with the link to the customer cut.
"""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.background_job import BackgroundJob
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_link_request import ChannelLinkRequest
from app.db.models.channel_prompt import ChannelPrompt
from app.db.models.channel_session import ChannelSession
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Conversation, Message
from app.db.models.notification import Notification
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.run_manifest import RunManifest
from app.db.models.user import User
from app.db.models.whatsapp_customer import WhatsAppCustomer, WhatsAppHeldRun
from app.repositories import (
    channel_identity_repo,
    customer_erasure_repo,
    whatsapp_customer_repo,
)
from app.services.agent_runner import AgentRunnerService
from app.services.channels.whatsapp_erasure import WhatsAppErasureService
from app.services.channels.whatsapp_payload import platform_user_id_for
from app.services.notifications import approval_occurrence_id

pytestmark = [pytest.mark.anyio, pytest.mark.security]

BSUID = "US.111"
PHONE = "48600700800"
NAME = "Ana Customer"
NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


async def _user(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _org(db: AsyncSession) -> tuple[Organization, User]:
    owner = await _user(db)
    org = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"))
    await db.flush()
    return org, owner


async def _bot(db: AsyncSession, org: Organization, platform: str = "whatsapp") -> ChannelBot:
    bot = ChannelBot(
        organization_id=org.id,
        platform=platform,
        name=f"Line {uuid.uuid4().hex[:4]}",
        token_encrypted="x",
        whatsapp_phone_number_id=uuid.uuid4().hex[:10],
        whatsapp_account_id=uuid.uuid4().hex[:10],
    )
    db.add(bot)
    await db.flush()
    return bot


async def _run(
    db: AsyncSession,
    org: Organization,
    agent: Agent,
    identity: ChannelIdentity,
    *,
    user_id: uuid.UUID | None = None,
    stranger: bool = True,
    parked: bool = False,
    conversation: Conversation | None = None,
) -> AgentRun:
    run = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        user_id=user_id,
        status=RunStatus.AWAITING_APPROVAL.value if parked else RunStatus.COMPLETED.value,
        surface="whatsapp",
        started_at=NOW,
        cost_usd=Decimal("1.25"),
        input_tokens=5,
        output_tokens=3,
        initiated_by_publisher_fallback=stranger,
        channel_identity_id=identity.id,
        conversation_id=conversation.id if conversation else None,
        paused_state={"messages": []} if parked else None,
    )
    db.add(run)
    await db.flush()
    return run


async def _approval(db: AsyncSession, org: Organization, run: AgentRun) -> ToolApproval:
    approval = ToolApproval(
        organization_id=org.id,
        run_id=run.id,
        agent_id=run.agent_id,
        tool_id="send_email",
        tool_args={"to": "ana@example.com"},
        context={"view": "Ana's orders"},
        note="for Ana",
        status=ApprovalStatus.PENDING.value,
    )
    db.add(approval)
    await db.flush()
    return approval


async def _conversation(
    db: AsyncSession, org: Organization, identity: ChannelIdentity, *, owner: User | None = None
) -> Conversation:
    conversation = Conversation(organization_id=org.id, user_id=owner.id if owner else None)
    db.add(conversation)
    await db.flush()
    db.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content="my number is 600 700 800",
            channel_identity_id=identity.id,
        )
    )
    await db.flush()
    return conversation


class World(SimpleNamespace):
    """One organization's customer, spread over every store that holds something about them."""


async def _world(db: AsyncSession) -> World:
    org, owner = await _org(db)
    first, second = await _bot(db, org), await _bot(db, org)
    agent = Agent(organization_id=org.id, slug=f"a-{uuid.uuid4().hex[:6]}", name="A", draft_spec={})
    db.add(agent)
    await db.flush()
    puid = platform_user_id_for(org.id, BSUID)
    identity = ChannelIdentity(
        platform="whatsapp", platform_user_id=puid, platform_display_name=NAME,
        platform_username="•••• 0800",
    )  # fmt: skip
    db.add(identity)
    await db.flush()
    current = await _conversation(db, org, identity)
    orphan = await _conversation(db, org, identity)
    sessions = [
        ChannelSession(bot_id=first.id, identity_id=identity.id, platform_chat_id=BSUID,
                       conversation_id=current.id),
        ChannelSession(bot_id=second.id, identity_id=identity.id, platform_chat_id=BSUID),
    ]  # fmt: skip
    db.add_all(sessions)
    message = (
        await db.execute(select(Message).where(Message.conversation_id == orphan.id))
    ).scalar_one()
    db.add(
        ChatFile(
            user_id=owner.id, message_id=message.id, filename="id.png", mime_type="image/png",
            size=3, storage_path="chat/id.png", file_type="image",
        )
    )  # fmt: skip
    customers = [
        await whatsapp_customer_repo.lock(db, organization_id=org.id, bot_id=bot.id, bsuid=BSUID)
        for bot in (first, second)
    ]
    for customer in customers:
        customer.phone = PHONE
    parked = await _run(db, org, agent, identity, parked=True, conversation=current)
    done = await _run(db, org, agent, identity, conversation=orphan)
    approvals = [await _approval(db, org, parked), await _approval(db, org, parked)]
    db.add(RunManifest(run_id=parked.id, organization_id=org.id, payload={"m": "Ana"}))
    db.add(WhatsAppHeldRun(organization_id=org.id, customer_id=customers[0].id, run_id=done.id))
    db.add(
        ChannelLinkRequest(
            token=uuid.uuid4().hex, platform="whatsapp", platform_user_id=puid,
            platform_display_name=NAME, expires_at=NOW,
        )
    )  # fmt: skip
    db.add(
        ChannelPrompt(
            organization_id=org.id, bot_id=first.id, run_id=parked.id, platform_chat_id=BSUID,
            kind="approval", approval_id=approvals[0].id, choices=["yes", "no"],
        )
    )  # fmt: skip
    for bot in (first, second):
        db.add(
            BackgroundJob(
                kind="deliver_channel_handback", pool="system", organization_id=org.id,
                max_attempts=1, payload={"output": "hi Ana"}, status="queued",
                concurrency_key=f"channel-handback:{bot.id}:{BSUID}",
            )
        )  # fmt: skip
    notification = Notification(
        organization_id=org.id, recipient_user_id=owner.id, event_type="approval_requested",
        occurrence_id=approval_occurrence_id(a.id for a in approvals), summary="Ana asked",
    )  # fmt: skip
    db.add(notification)
    await db.flush()
    return World(
        org=org, owner=owner, bots=[first, second], agent=agent, identity=identity, puid=puid,
        conversations=[current, orphan], customers=customers, parked=parked, done=done,
        approvals=approvals, notification=notification,
    )  # fmt: skip


def _forget(db: AsyncSession, world: World, *, via: str = "console"):
    return WhatsAppErasureService(db).forget(
        world.bots[0], bsuid=BSUID, named_by="bsuid", actor_user_id=world.owner.id, via=via
    )


async def _count(db: AsyncSession, model, *where) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*where)) or 0


@pytest.fixture(autouse=True)
def _after_commit():
    """The byte deletions and sandbox destroys are scheduled after the commit; none runs here."""
    with patch("app.services.conversation.spawn_after_commit") as spawned:
        spawned.side_effect = lambda _db, coro, **_: coro.close()
        yield spawned


async def test_every_store_of_the_customer_is_gone(db: AsyncSession) -> None:
    world = await _world(db)
    org = world.org.id
    approval_ids = [a.id for a in world.approvals]

    counts = await _forget(db, world)

    assert await _count(db, ChannelIdentity, ChannelIdentity.id == world.identity.id) == 0
    assert await _count(db, ChannelSession, ChannelSession.identity_id == world.identity.id) == 0
    assert await _count(db, WhatsAppCustomer, WhatsAppCustomer.organization_id == org) == 0
    assert await _count(db, WhatsAppHeldRun, WhatsAppHeldRun.organization_id == org) == 0
    assert await _count(db, Conversation, Conversation.organization_id == org) == 0
    assert await _count(db, Message, Message.channel_identity_id.is_not(None)) == 0
    assert await _count(db, ChatFile, ChatFile.storage_path == "chat/id.png") == 0
    assert (
        await _count(db, ChannelLinkRequest, ChannelLinkRequest.platform_user_id == world.puid) == 0
    )
    assert await _count(db, ChannelPrompt, ChannelPrompt.organization_id == org) == 0
    assert await _count(db, RunManifest, RunManifest.organization_id == org) == 0
    assert await _count(db, Notification, Notification.organization_id == org) == 0
    assert await _count(db, BackgroundJob, BackgroundJob.organization_id == org) == 0
    rows = (
        (await db.execute(select(ToolApproval).where(ToolApproval.id.in_(approval_ids))))
        .scalars()
        .all()
    )
    assert [(r.tool_args, r.context, r.note) for r in rows] == [
        ({"redacted": True}, None, None)
    ] * 2
    assert (counts.identities, counts.sessions, counts.customers, counts.conversations) == (
        1,
        2,
        2,
        2,
    )
    assert (counts.approvals_redacted, counts.approvals_ended, counts.manifests) == (2, 2, 1)
    assert (counts.notifications, counts.handback_jobs, counts.prompts) == (1, 2, 1)
    assert (counts.link_requests, counts.runs_ended, counts.handback_jobs_running) == (1, 1, 0)


async def test_runs_stay_as_accounting(db: AsyncSession) -> None:
    world = await _world(db)

    await _forget(db, world)

    for run in (world.parked, world.done):
        await db.refresh(run)
        assert (run.channel_identity_id, run.paused_state, run.cost_usd) == (
            None, None, Decimal("1.25"),
        )  # fmt: skip
        assert run.conversation_id is None


async def test_a_parked_run_is_ended_and_cannot_be_resumed(db: AsyncSession) -> None:
    world = await _world(db)

    await _forget(db, world)

    await db.refresh(world.parked)
    assert world.parked.status == RunStatus.CANCELLED.value
    assert world.parked.error == "The customer's data was erased."
    for approval in world.approvals:
        await db.refresh(approval)
        assert approval.status == ApprovalStatus.EXPIRED.value
        assert approval.decided_by_user_id is None
    ctx = AuthContext(user_id=world.owner.id, organization_id=world.org.id, role=OrgRoleName.OWNER)
    with pytest.raises(BadRequestError):
        await AgentRunnerService(db).resume(ctx, world.parked.id)


async def test_another_organizations_same_customer_is_untouched(db: AsyncSession) -> None:
    world = await _world(db)
    other = await _world(db)

    await _forget(db, world)

    assert await _count(db, ChannelIdentity, ChannelIdentity.id == other.identity.id) == 1
    assert await _count(db, WhatsAppCustomer, WhatsAppCustomer.organization_id == other.org.id) == 2
    assert await _count(db, Conversation, Conversation.organization_id == other.org.id) == 2
    assert await _count(db, BackgroundJob, BackgroundJob.organization_id == other.org.id) == 2
    assert await _count(db, Notification, Notification.organization_id == other.org.id) == 1
    await db.refresh(other.parked)
    assert other.parked.status == RunStatus.AWAITING_APPROVAL.value
    await db.refresh(other.approvals[0])
    assert other.approvals[0].tool_args == {"to": "ana@example.com"}


async def test_a_linked_customer_is_refused(db: AsyncSession) -> None:
    world = await _world(db)
    world.identity.user_id = world.owner.id
    await db.flush()

    with pytest.raises(ConflictError) as refused:
        await _forget(db, world)

    assert "linked to a member account" in refused.value.message
    assert await _count(db, WhatsAppCustomer, WhatsAppCustomer.organization_id == world.org.id) == 2
    assert await _count(db, Conversation, Conversation.organization_id == world.org.id) == 2
    assert (
        await _count(db, AppAdminAuditLog, AppAdminAuditLog.action == "channel.customer.forgotten")
        == 0
    )


async def test_a_bot_of_another_platform_is_refused(db: AsyncSession) -> None:
    world = await _world(db)
    telegram = await _bot(db, world.org, "telegram")

    with pytest.raises(BadRequestError):
        await WhatsAppErasureService(db).forget(
            telegram, bsuid=BSUID, named_by="bsuid", actor_user_id=None, via="cli"
        )


async def test_the_audit_row_names_nobody(db: AsyncSession) -> None:
    world = await _world(db)

    await _forget(db, world)

    entry = (
        await db.execute(
            select(AppAdminAuditLog).where(AppAdminAuditLog.action == "channel.customer.forgotten")
        )
    ).scalar_one()
    rendered = json.dumps(entry.details) + str(entry.target_id) + str(entry.target_type)
    secrets = [BSUID, PHONE, "600", NAME, "Ana", str(world.identity.id), world.puid]
    secrets += [str(c.id) for c in world.conversations]
    assert not [s for s in secrets if s in rendered]
    assert entry.target_id == str(world.bots[0].id)
    assert entry.details["named_by"] == "bsuid"
    assert entry.details["via"] == "console"
    assert entry.details["conversations"] == 2


async def test_a_members_own_runs_from_a_linked_period_are_kept(db: AsyncSession) -> None:
    world = await _world(db)
    owned = await _conversation(db, world.org, world.identity, owner=world.owner)
    member_run = await _run(
        db, world.org, world.agent, world.identity, user_id=world.owner.id, stranger=False,
        parked=True, conversation=owned,
    )  # fmt: skip
    approval = await _approval(db, world.org, member_run)
    db.add(RunManifest(run_id=member_run.id, organization_id=world.org.id, payload={"m": "x"}))
    await db.flush()

    await _forget(db, world)

    await db.refresh(member_run)
    await db.refresh(approval)
    assert member_run.status == RunStatus.AWAITING_APPROVAL.value
    assert member_run.paused_state == {"messages": []}
    assert member_run.channel_identity_id is None
    assert (approval.status, approval.tool_args) == ("pending", {"to": "ana@example.com"})
    assert await _count(db, RunManifest, RunManifest.run_id == member_run.id) == 1
    assert await _count(db, Conversation, Conversation.id == owned.id) == 1


async def test_locking_creates_no_customer_rows(db: AsyncSession) -> None:
    world = await _world(db)
    third = await _bot(db, world.org)
    before = await _count(db, WhatsAppCustomer)

    locked = await whatsapp_customer_repo.lock_existing(
        db, organization_id=world.org.id, bsuid=BSUID
    )
    nothing = await whatsapp_customer_repo.lock_existing(
        db, organization_id=world.org.id, bsuid="US.never"
    )

    assert sorted(c.bot_id for c in locked) == sorted(b.id for b in world.bots)
    assert nothing == []
    assert await _count(db, WhatsAppCustomer) == before
    assert await _count(db, WhatsAppCustomer, WhatsAppCustomer.bot_id == third.id) == 0


async def test_the_purge_is_made_per_conversation_as_an_anonymous_context(db: AsyncSession) -> None:
    world = await _world(db)
    purge = AsyncMock(return_value=1)

    with patch("app.services.channels.whatsapp_erasure.SandboxWorkspaceService") as service:
        service.return_value.purge_for_conversation = purge
        counts = await _forget(db, world)

    assert counts.workspaces == 2
    assert {c.kwargs["conversation_id"] for c in purge.await_args_list} == {
        c.id for c in world.conversations
    }
    for call in purge.await_args_list:
        ctx = call.args[0]
        assert (ctx.user_id, ctx.organization_id) == (None, world.org.id)


async def test_a_second_erasure_finds_nothing_and_is_audited_again(db: AsyncSession) -> None:
    world = await _world(db)
    await _forget(db, world)

    counts = await _forget(db, world)

    assert (counts.identities, counts.customers, counts.conversations, counts.runs_ended) == (
        0,
        0,
        0,
        0,
    )
    assert (
        await _count(db, AppAdminAuditLog, AppAdminAuditLog.action == "channel.customer.forgotten")
        == 2
    )


async def test_a_running_handback_job_is_left_and_counted(db: AsyncSession) -> None:
    world = await _world(db)
    job = (
        await db.execute(
            select(BackgroundJob).where(
                BackgroundJob.concurrency_key == f"channel-handback:{world.bots[0].id}:{BSUID}"
            )
        )
    ).scalar_one()
    job.status = "running"
    await db.flush()

    counts = await _forget(db, world)

    assert (counts.handback_jobs, counts.handback_jobs_running) == (1, 1)
    assert await _count(db, BackgroundJob, BackgroundJob.id == job.id) == 1


async def test_only_this_customers_stranger_runs_and_other_customers_are_untouched(
    db: AsyncSession,
) -> None:
    world = await _world(db)
    bystander = ChannelIdentity(
        platform="whatsapp", platform_user_id=platform_user_id_for(world.org.id, "US.999")
    )
    db.add(bystander)
    await db.flush()
    other_run = await _run(db, world.org, world.agent, bystander, parked=True)
    await _approval(db, world.org, other_run)

    await _forget(db, world)

    await db.refresh(other_run)
    assert (other_run.status, other_run.channel_identity_id) == (
        RunStatus.AWAITING_APPROVAL.value,
        bystander.id,
    )


async def test_the_repository_reads_only_the_organizations_own_rows(db: AsyncSession) -> None:
    world = await _world(db)
    other = await _world(db)
    org = world.org.id

    assert sorted(await customer_erasure_repo.whatsapp_bot_ids(db, organization_id=org)) == sorted(
        b.id for b in world.bots
    )
    runs = await customer_erasure_repo.stranger_runs_of_identity(
        db, organization_id=org, identity_id=world.identity.id
    )
    assert {r.id for r in runs} == {world.parked.id, world.done.id}
    assert not await customer_erasure_repo.stranger_runs_of_identity(
        db, organization_id=org, identity_id=other.identity.id
    )
    assert set(
        await customer_erasure_repo.conversation_ids(
            db, organization_id=org, identity_id=world.identity.id
        )
    ) == {c.id for c in world.conversations}
    assert not await customer_erasure_repo.conversation_ids(
        db, organization_id=org, identity_id=other.identity.id
    )
    run_ids = [world.parked.id]
    assert (
        await customer_erasure_repo.delete_manifests(
            db, organization_id=other.org.id, run_ids=run_ids
        )
        == 0
    )
    assert (
        await customer_erasure_repo.redact_approvals(
            db, organization_id=other.org.id, run_ids=run_ids
        )
        == 0
    )
    assert (
        await customer_erasure_repo.end_pending_approvals(
            db, organization_id=other.org.id, run_ids=run_ids, at=NOW
        )
        == 0
    )
    assert (
        await customer_erasure_repo.delete_customers(
            db, organization_id=other.org.id, bot_ids=[b.id for b in world.bots], bsuid=BSUID
        )
        == 0
    )
    assert (
        await customer_erasure_repo.delete_prompts(
            db,
            organization_id=other.org.id,
            bot_ids=[b.id for b in world.bots],
            platform_chat_id=BSUID,
        )
        == 0
    )
    assert await customer_erasure_repo.delete_handback_jobs(
        db, organization_id=other.org.id,
        concurrency_keys=[f"channel-handback:{world.bots[0].id}:{BSUID}"],
    ) == (0, 0)  # fmt: skip
    assert await customer_erasure_repo.delete_notifications(
        db, organization_id=other.org.id, event_type="approval_requested",
        occurrence_ids=[world.notification.occurrence_id],
    ) == 0  # fmt: skip


async def test_two_parked_calls_are_two_occurrences_by_their_creation_time(
    db: AsyncSession,
) -> None:
    world = await _world(db)
    again = await _approval(db, world.org, world.parked)
    notification = Notification(
        organization_id=world.org.id, recipient_user_id=world.owner.id,
        event_type="approval_requested", occurrence_id=approval_occurrence_id([again.id]),
        summary="again",
    )  # fmt: skip
    db.add(notification)
    await db.flush()
    await db.execute(
        ToolApproval.__table__.update()
        .where(ToolApproval.id == again.id)
        .values(created_at=datetime(2026, 11, 5, tzinfo=UTC))
    )
    await db.refresh(again)

    counts = await _forget(db, world)

    assert counts.notifications == 2
    assert await _count(db, Notification, Notification.organization_id == world.org.id) == 0


async def test_the_identity_is_read_under_a_lock(db: AsyncSession) -> None:
    world = await _world(db)
    seen = []
    real = channel_identity_repo.get_by_platform_user

    async def spy(*args, **kwargs):
        seen.append(kwargs.get("for_update"))
        return await real(*args, **kwargs)

    with patch(
        "app.services.channels.whatsapp_erasure.channel_identity_repo.get_by_platform_user", spy
    ):
        await _forget(db, world)

    assert seen == [True]


async def test_a_customer_of_another_bot_or_organization_is_not_found_by_id(
    db: AsyncSession,
) -> None:
    world = await _world(db)
    other = await _world(db)
    mine = world.customers[0]

    found = await whatsapp_customer_repo.get_in_bot(
        db, organization_id=world.org.id, bot_id=world.bots[0].id, customer_id=mine.id
    )
    assert found is not None and found.id == mine.id
    for bot_id, org_id in (
        (world.bots[1].id, world.org.id),
        (world.bots[0].id, other.org.id),
        (other.bots[0].id, world.org.id),
    ):
        assert (
            await whatsapp_customer_repo.get_in_bot(
                db, organization_id=org_id, bot_id=bot_id, customer_id=mine.id
            )
            is None
        )
