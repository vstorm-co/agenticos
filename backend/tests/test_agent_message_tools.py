"""Messaging tools bind every action to the run's agent and active member."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage

from app.agents.capabilities.agent_messages import _toolset
from app.agents.capabilities.agent_messages._capability import AgentMessages
from app.agents.deps import AgentDeps
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.agent_message import (
    AgentMessageList,
    AgentMessageReactionCreate,
    AgentMessageReactionsRead,
    AgentMessageRead,
    AgentMessageSend,
    AgentMessageThreadList,
)
from app.services.agent_messages import AgentMessageService

pytestmark = pytest.mark.anyio
ToolName = Literal["agent_send_message", "agent_read_messages", "agent_list_threads", "agent_react"]
TOOLS: tuple[ToolName, ...] = (
    "agent_send_message",
    "agent_read_messages",
    "agent_list_threads",
    "agent_react",
)
NOW = datetime(2026, 11, 14, tzinfo=UTC)


@dataclass
class ToolBoundary:
    ctx: RunContext[AgentDeps]
    auth: AuthContext
    db: MagicMock
    service: AsyncMock
    member: AsyncMock
    database: MagicMock
    factory: MagicMock
    events: list[str]
    thread_id: UUID
    message_id: UUID


@pytest.fixture
def boundary(monkeypatch: pytest.MonkeyPatch) -> ToolBoundary:
    user_id, org_id, agent_id = uuid4(), uuid4(), uuid4()
    auth = AuthContext(user_id=user_id, organization_id=org_id, role=OrgRoleName.MEMBER)
    ctx = RunContext(
        deps=AgentDeps(
            organization_id=org_id, user_id=str(user_id), run_person=user_id, agent_id=agent_id
        ),
        model=TestModel(),
        usage=RunUsage(),
    )
    db = MagicMock()
    service = AsyncMock(spec=AgentMessageService)
    member = AsyncMock(return_value=auth)
    events: list[str] = []

    @asynccontextmanager
    async def scope() -> AsyncGenerator[MagicMock]:
        events.append("opened")
        try:
            yield db
        finally:
            events.append("closed")

    database = MagicMock(side_effect=scope)
    factory = MagicMock(return_value=service)
    monkeypatch.setattr(_toolset, "get_db_context", database)
    monkeypatch.setattr(_toolset, "acting_member", member)
    monkeypatch.setattr(_toolset, "AgentMessageService", factory)
    thread_id, message_id = uuid4(), uuid4()
    message = AgentMessageRead(
        id=message_id,
        thread_id=thread_id,
        sender_agent_id=agent_id,
        sender_agent_slug="writer",
        sender_user_id=user_id,
        body="hello",
        created_at=NOW,
        updated_at=NOW,
    )
    service.send.return_value = message
    service.list_messages.return_value = AgentMessageList(items=[message], total=1)
    service.list_threads_for_agent.return_value = AgentMessageThreadList(items=[], total=0)
    service.react.return_value = AgentMessageReactionsRead(reacted=True, reactions=[])
    return ToolBoundary(
        ctx, auth, db, service, member, database, factory, events, thread_id, message_id
    )


async def invoke(
    boundary: ToolBoundary,
    tool: ToolName,
    *,
    toolset: FunctionToolset[AgentDeps] | None = None,
    body: str = "hello",
    reply: UUID | None = None,
    files: list[UUID] | None = None,
) -> str:
    toolset = toolset or AgentMessages().get_toolset()
    function = toolset.tools[tool].function
    if tool == "agent_send_message":
        return await function(
            boundary.ctx,
            "reviewer",
            body,
            reply_to_message_id=reply,
            attachment_file_ids=files,
        )
    if tool == "agent_read_messages":
        return await function(boundary.ctx, boundary.thread_id, skip=3, limit=7)
    if tool == "agent_list_threads":
        return await function(boundary.ctx, skip=3, limit=7)
    return await function(boundary.ctx, boundary.message_id, "👍")


@pytest.mark.parametrize("tool", TOOLS)
async def test_tools_use_the_verified_member_and_the_runs_agent(
    boundary: ToolBoundary,
    tool: ToolName,
) -> None:
    assert boundary.ctx.deps.agent_id is not None
    result = await invoke(boundary, tool)
    boundary.member.assert_awaited_once_with(
        boundary.db, boundary.auth.organization_id, boundary.ctx.deps.user_id
    )
    boundary.factory.assert_called_once_with(boundary.db)
    if tool == "agent_send_message":
        boundary.service.send.assert_awaited_once_with(
            boundary.auth,
            AgentMessageSend(
                sender_agent_id=boundary.ctx.deps.agent_id, recipient="reviewer", body="hello"
            ),
        )
        expected = boundary.service.send.return_value
    elif tool == "agent_read_messages":
        boundary.service.list_messages.assert_awaited_once_with(
            boundary.auth, boundary.thread_id, skip=3, limit=7
        )
        expected = boundary.service.list_messages.return_value
    elif tool == "agent_list_threads":
        boundary.service.list_threads_for_agent.assert_awaited_once_with(
            boundary.auth, agent_id=boundary.ctx.deps.agent_id, skip=3, limit=7
        )
        expected = boundary.service.list_threads_for_agent.return_value
    else:
        boundary.service.react.assert_awaited_once_with(
            boundary.auth,
            message_id=boundary.message_id,
            data=AgentMessageReactionCreate(emoji="👍", as_agent_id=boundary.ctx.deps.agent_id),
        )
        expected = boundary.service.react.return_value
    assert json.loads(result) == expected.model_dump(mode="json")
    assert boundary.events == ["opened", "closed"]


async def test_a_send_preserves_its_reply_and_explicit_files(boundary: ToolBoundary) -> None:
    assert boundary.ctx.deps.agent_id is not None
    reply, file_id = uuid4(), uuid4()
    result = await invoke(boundary, "agent_send_message", reply=reply, files=[file_id])
    boundary.service.send.assert_awaited_once_with(
        boundary.auth,
        AgentMessageSend(
            sender_agent_id=boundary.ctx.deps.agent_id,
            recipient="reviewer",
            body="hello",
            reply_to_message_id=reply,
            attachment_file_ids=[file_id],
        ),
    )
    assert json.loads(result)["id"] == str(boundary.message_id)


@pytest.mark.security
@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("preview", ["no-agent", "impersonated"])
async def test_preview_runs_cannot_open_a_messaging_transaction(
    boundary: ToolBoundary,
    tool: ToolName,
    preview: str,
) -> None:
    if preview == "no-agent":
        boundary.ctx.deps.agent_id = None
    else:
        boundary.ctx.deps.impersonated = True
    assert await invoke(boundary, tool) == (
        "Messaging needs this agent running as itself, not as a preview."
    )
    boundary.database.assert_not_called()
    boundary.member.assert_not_awaited()
    boundary.factory.assert_not_called()


@pytest.mark.security
@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("identity", ["inactive", "different-member", "no-run-person"])
async def test_unverified_members_cannot_act_in_another_agents_name(
    boundary: ToolBoundary,
    tool: ToolName,
    identity: str,
) -> None:
    if identity == "inactive":
        boundary.member.return_value = None
    elif identity == "different-member":
        boundary.ctx.deps.run_person = uuid4()
    else:
        boundary.ctx.deps.run_person = None
    assert await invoke(boundary, tool) == "Messaging needs an active organization member."
    boundary.factory.assert_not_called()
    assert boundary.events == ["opened", "closed"]


@pytest.mark.security
@pytest.mark.parametrize(
    ("body", "files", "expected"),
    [
        ("hello", None, "That message is 5 characters; this agent may send at most 4."),
        ("hi", [UUID(int=5)], "This agent may not send files with its messages."),
    ],
)
async def test_published_message_limits_refuse_before_database_access(
    boundary: ToolBoundary,
    body: str,
    files: list[UUID] | None,
    expected: str,
) -> None:
    capability = AgentMessages(max_message_chars=4, allow_attachments=False)
    assert (
        await invoke(
            boundary, "agent_send_message", toolset=capability.get_toolset(), body=body, files=files
        )
        == expected
    )
    boundary.database.assert_not_called()
    boundary.factory.assert_not_called()


@pytest.mark.security
@pytest.mark.parametrize(
    ("tool", "method"),
    [
        ("agent_send_message", "send"),
        ("agent_read_messages", "list_messages"),
        ("agent_list_threads", "list_threads_for_agent"),
        ("agent_react", "react"),
    ],
)
async def test_permission_refusals_are_reported_without_claiming_success(
    boundary: ToolBoundary,
    tool: ToolName,
    method: str,
) -> None:
    refusal = AuthorizationError(message="This grant was revoked", details={"reason": "revoked"})
    getattr(boundary.service, method).side_effect = refusal
    result = await invoke(boundary, tool)
    assert result == f"Refused ({refusal.code}): This grant was revoked"
    assert boundary.events == ["opened", "closed"]


async def test_unexpected_storage_errors_propagate_after_the_transaction_closes(
    boundary: ToolBoundary,
) -> None:
    error = RuntimeError("storage unavailable")
    boundary.service.list_messages.side_effect = error
    with pytest.raises(RuntimeError, match="storage unavailable") as raised:
        await invoke(boundary, "agent_read_messages")
    assert raised.value is error
    assert boundary.events == ["opened", "closed"]


@pytest.mark.security
def test_instructions_explain_storage_visibility_and_secret_boundaries(
    boundary: ToolBoundary,
) -> None:
    instructions = AgentMessages().get_instructions()(boundary.ctx)
    assert "does not start a run" in instructions
    assert "does not wake it up" in instructions
    assert "anyone who may run either agent" in instructions
    assert "Never send a credential, a secret" in instructions
