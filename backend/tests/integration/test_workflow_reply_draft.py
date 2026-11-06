"""An expired verified wait prepares one saved draft; reply and provider error do not."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import ExternalServiceError
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun
from app.db.models.mcp_connection import McpConnection
from app.schemas.reply_expectation import ReplyDraftSelection, ReplyMailboxSelection
from app.schemas.workflow import WorkflowCreate
from app.services.portals.reply_metadata import ReplyMessage
from app.services.workflow_registry import WorkflowRegistryService
from tests.integration.test_workflow_agent_node import _Model, _profile, _tenant
from tests.integration.workflow_run_support import drive, seed_run

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("verdict", ["deadline", "reply", "provider_error"])
async def test_only_a_successfully_checked_deadline_prepares_one_draft(
    engine: AsyncEngine, monkeypatch, verdict: str
):
    user, org = await _tenant(engine)
    profile = await _profile(engine, org)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
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
        registry = WorkflowRegistryService(db)
        ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
        created = await registry.create(
            ctx,
            WorkflowCreate(
                name="Draft on deadline",
                template_id="awaitReply",
                reply_mailbox=ReplyMailboxSelection(provider="google", connection_id=grant.id),
                reply_draft=ReplyDraftSelection(model_profile_id=profile, max_cost_usd=0.1),
            ),
        )
        graph = (await registry.get(ctx, created.id)).draft_graph
        await db.commit()
    assert graph is not None
    draft = next(node for node in graph.nodes if node.definition_id == "agent.run")
    assert draft.config["inline"]["capabilities"] == []
    assert draft.config["inline"]["model_profile_id"] == str(profile)
    assert "email.send" not in {node.definition_id for node in graph.nodes}
    now = datetime.now(UTC)
    deadline = now - timedelta(seconds=10)
    seeded = await seed_run(
        engine,
        graph,
        member=(user, org),
        run_input={
            "thread_id": "thread",
            "expected_sender": "alice@example.com",
            "not_before": (now - timedelta(hours=1)).isoformat(),
            "deadline": deadline.isoformat(),
            "followup_context": "Ask for the revised delivery date",
        },
    )
    recorder = _Model(
        "DRAFT - NOT SENT\nSubject: Delivery update\nCould you share the revised date?"
    )
    monkeypatch.setattr(
        "app.agents.model_resolver.build_model", lambda *_args: recorder.function_model()
    )

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        async with seeded.factory() as db:
            yield db
            await db.commit()

    reply = ReplyMessage(
        message_id="r",
        thread_id="thread",
        sender="alice@example.com",
        received_at=deadline - timedelta(seconds=1),
        authenticated=True,
    )
    read = AsyncMock(return_value=(reply,) if verdict == "reply" else ())
    if verdict == "provider_error":
        read.side_effect = ExternalServiceError(message="Mailbox unavailable")
    with (
        patch("app.workflows.nodes.flow_await_reply._handler.get_worker_db_context", session),
        patch(
            "app.services.mcp_connection.McpConnectionService.reply_mailbox_token",
            AsyncMock(return_value=(grant.authorization_generation, SecretStr("token"))),
        ),
        patch("app.services.portals.reply_metadata.MailReplyMetadataClient.read", read),
    ):
        run = await drive(seeded)
        assert run.status == ("failed" if verdict == "provider_error" else "succeeded")
        await drive(seeded)
    if verdict == "deadline":
        assert run.output is not None and "DRAFT - NOT SENT" in run.output["text"]
        assert any(
            "alice@example.com" in prompt and "revised delivery" in prompt
            for prompt in recorder.prompts
        )
    else:
        assert recorder.prompts == []
    async with seeded.factory() as db:
        count = await db.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.organization_id == org.id)
        )
    assert count == (1 if verdict == "deadline" else 0)


async def test_model_selection_is_explicit_and_template_scoped():
    with pytest.raises(ValidationError):
        WorkflowCreate(
            name="Wrong template", reply_draft=ReplyDraftSelection(model_profile_id=uuid4())
        )
    with pytest.raises(ValidationError):
        ReplyDraftSelection(model_profile_id=uuid4(), max_cost_usd=0)
