"""The reply preset provisions one valid private graph without reading a mailbox."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.permissions import AuthContext
from app.db.models.mcp_connection import McpConnection
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.virtual_table import VirtualTable
from app.schemas.reply_expectation import ReplyMailboxSelection
from app.schemas.workflow import WorkflowCreate
from app.services.portals.reply_metadata import ReplyMessage
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.graph.errors import GraphValidationError
from tests.integration.workflow_run_support import drive, seed_member, seed_run

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("provider", ["google", "outlook"])
async def test_reply_preset_is_private_valid_and_has_no_table_or_outbound_send(
    db: AsyncSession, provider: str
):
    user, org = await seed_member(db)
    grant = McpConnection(
        id=uuid4(),
        organization_id=org.id,
        created_by_user_id=user.id,
        scope="org",
        purpose="portal",
        portal_key="google" if provider == "google" else "microsoft",
        name="Mailbox",
        url="https://mail.example.com",
        auth_type="oauth",
        is_enabled=True,
    )
    db.add(grant)
    await db.flush()
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    service = WorkflowRegistryService(db)
    source = ReplyMailboxSelection.model_validate(
        {
            "provider": provider,
            "connection_id": grant.id,
            "mailbox": "shared@example.com" if provider == "outlook" else None,
        }
    )
    with patch("app.services.mcp_connection._oauth_access_token", AsyncMock()) as token:
        created = await service.create(
            ctx, WorkflowCreate(name="Await reply", template_id="awaitReply", reply_mailbox=source)
        )
        detail = await service.get(ctx, created.id)
    token.assert_not_awaited()
    assert created.visibility == "private" and created.status == "draft"
    assert detail.draft_graph is not None and len(detail.draft_graph.nodes) == 5
    types = {node.definition_id for node in detail.draft_graph.nodes}
    assert types == {"trigger.manual", "flow.await_reply", "core.output", "notification.send"}
    notify = next(
        node for node in detail.draft_graph.nodes if node.definition_id == "notification.send"
    )
    assert notify.config["recipients"] == [str(user.id)]
    assert await db.scalar(select(func.count()).select_from(VirtualTable)) == 0


async def test_reply_preset_cannot_borrow_another_organizations_mailbox(db: AsyncSession):
    user, org = await seed_member(db)
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    with pytest.raises(GraphValidationError):
        await WorkflowRegistryService(db).create(
            ctx,
            WorkflowCreate(
                name="Wrong mailbox",
                template_id="awaitReply",
                reply_mailbox=ReplyMailboxSelection(provider="google", connection_id=uuid4()),
            ),
        )


def test_only_the_reply_preset_accepts_mailbox_configuration():
    with pytest.raises(ValidationError):
        WorkflowCreate(name="Missing source", template_id="awaitReply")
    with pytest.raises(ValidationError):
        WorkflowCreate(
            name="Wrong template",
            template_id="markdownNotes",
            reply_mailbox=ReplyMailboxSelection(provider="google", connection_id=uuid4()),
        )


@pytest.mark.parametrize("replied", [False, True])
async def test_prepared_preset_runs_both_branches_without_duplicate_reminders(
    engine: AsyncEngine, replied: bool
):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        user, org = await seed_member(db)
        grant = McpConnection(
            id=uuid4(),
            organization_id=org.id,
            created_by_user_id=user.id,
            scope="org",
            purpose="portal",
            portal_key="google",
            name="Mailbox",
            url="https://gmail.googleapis.com",
            is_enabled=True,
        )
        db.add(grant)
        await db.flush()
        ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
        registry = WorkflowRegistryService(db)
        created = await registry.create(
            ctx,
            WorkflowCreate(
                name="Follow-up",
                template_id="awaitReply",
                reply_mailbox=ReplyMailboxSelection(provider="google", connection_id=grant.id),
            ),
        )
        graph = (await registry.get(ctx, created.id)).draft_graph
        await db.commit()
    assert graph is not None
    now = datetime.now(UTC)
    deadline = now - timedelta(seconds=10)
    seeded = await seed_run(
        engine,
        graph,
        member=(user, org),
        run_input={
            "thread_id": "original-thread",
            "expected_sender": "alice@example.com",
            "not_before": (now - timedelta(hours=1)).isoformat(),
            "deadline": deadline.isoformat(),
        },
    )

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        async with seeded.factory() as db:
            yield db
            await db.commit()

    reply = ReplyMessage(
        message_id="reply",
        thread_id="original-thread",
        sender="alice@example.com",
        received_at=deadline - timedelta(seconds=1),
        authenticated=True,
    )
    with (
        patch("app.workflows.nodes.flow_await_reply._handler.get_worker_db_context", session),
        patch(
            "app.services.mcp_connection.McpConnectionService.reply_mailbox_token",
            AsyncMock(return_value=(grant.authorization_generation, SecretStr("token"))),
        ),
        patch(
            "app.services.portals.reply_metadata.MailReplyMetadataClient.read",
            AsyncMock(return_value=(reply,) if replied else ()),
        ),
    ):
        assert (await drive(seeded)).status == "succeeded"
        assert (await drive(seeded)).status == "succeeded"
    async with seeded.factory() as db:
        notices = list(
            await db.scalars(
                select(Notification).where(
                    Notification.organization_id == org.id,
                    Notification.event_type == NotificationEventType.WORKFLOW_NOTIFICATION.value,
                )
            )
        )
    assert len(notices) == (0 if replied else 1)
    if notices:
        assert "original-thread" in notices[0].summary and "alice@example.com" in notices[0].summary
        assert "No follow-up has been sent" in notices[0].summary
