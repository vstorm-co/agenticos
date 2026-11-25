"""Actual HTTP serialization must omit withheld spend, including Q&A continuations."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.api.routes.v1 import runs
from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.main import app
from app.repositories import deployment_settings_repo, member_repo, organization_repo
from app.schemas.agent import AgentRunResult
from app.schemas.conversation import ConversationCost, ConversationReadWithMessages, MessageRead

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("allowed", (True, False))
@pytest.mark.parametrize(
    "operation", ("conversation", "messages", "transcript", "add", "answers", "resume")
)
async def test_chat_responses_obey_the_readers_policy(
    monkeypatch: pytest.MonkeyPatch, allowed: bool, operation: str
) -> None:
    user = User(id=uuid4(), email="chat-cost@example.com", is_active=True, is_app_admin=False)
    org = Organization(
        id=uuid4(),
        name="Example",
        slug="cost-example",
        created_by_user_id=user.id,
        chat_cost_visibility="everyone" if allowed else "nobody",
    )
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    member = OrganizationMember(user_id=user.id, organization_id=org.id, role="owner")
    now = datetime.now(UTC)
    conversation_id = uuid4()
    message = MessageRead(
        id=uuid4(),
        conversation_id=conversation_id,
        role="assistant",
        content="Ready",
        created_at=now,
        input_tokens=10,
        output_tokens=2,
        cost_usd=Decimal("0.12"),
        cost_is_partial=True,
    )
    conversation = ConversationReadWithMessages(
        id=conversation_id,
        user_id=user.id,
        organization_id=org.id,
        created_at=now,
        messages=[message],
    )
    service = AsyncMock()
    service.get_conversation.return_value = conversation
    service.add_message.return_value = message
    service.transcript.return_value = (
        [message],
        1,
        ConversationCost(input_tokens=10, output_tokens=2, cost_usd=Decimal("0.12")),
    )
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=member))
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=org))
    monkeypatch.setattr(deployment_settings_repo, "get", AsyncMock(return_value=None))
    result = AgentRunResult(
        run_id=uuid4(),
        conversation_id=conversation_id,
        output="Ready",
        status="completed",
        cost_usd=Decimal("0.12"),
        input_tokens=10,
        output_tokens=2,
    )
    monkeypatch.setattr(runs, "run_result", AsyncMock(return_value=result))
    parked = AsyncMock()
    parked.resume.return_value = parked.answer.return_value = SimpleNamespace(
        segment=object(), continues_in_chat=True
    )
    app.dependency_overrides.update(
        {
            deps.get_current_user: lambda: user,
            deps.get_active_organization: lambda: org,
            deps.get_auth_context: lambda: ctx,
            deps.get_db_session: lambda: AsyncMock(),
            deps.get_conversation_service: lambda: service,
            deps.get_parked_run_service: lambda: parked,
            deps.get_agent_runner_service: lambda: AsyncMock(),
        }
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            if operation in {"conversation", "messages", "transcript"}:
                suffix = f"/{operation}" if operation in {"messages", "transcript"} else ""
                response = await client.get(
                    f"{settings.API_V1_STR}/conversations/{conversation_id}{suffix}"
                )
            elif operation == "add":
                response = await client.post(
                    f"{settings.API_V1_STR}/conversations/{conversation_id}/messages",
                    json={"role": "assistant", "content": "Ready"},
                )
            else:
                response = await client.post(
                    f"{settings.API_V1_STR}/runs/{result.run_id}/{operation}",
                    json={"responses": {"call-1": [{"answer": "Thursday"}]}}
                    if operation == "answers"
                    else None,
                )
        assert response.status_code == (201 if operation == "add" else 200), response.text
        body = response.json()
        data = (
            body["messages"][0]
            if operation == "conversation"
            else body["items"][0]
            if operation in {"messages", "transcript"}
            else body
        )
        assert ("cost_usd" in data) is allowed
        assert data["input_tokens"] == 10
        if operation in {"messages", "transcript"}:
            assert ("cost_usd" in body["cost"]) is allowed
        assert message.cost_usd == result.cost_usd == Decimal("0.12")
    finally:
        app.dependency_overrides.clear()
