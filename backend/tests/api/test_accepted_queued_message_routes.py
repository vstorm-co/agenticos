"""The personal queue API carries its source and owner through each route."""

from datetime import UTC, datetime
from typing import Literal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.api.routes.v1 import accepted_queued_messages as routes
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.accepted_queued_message import (
    AcceptedQueuedMessageCreate,
    AcceptedQueuedMessageList,
    AcceptedQueuedMessageRead,
)
from app.schemas.conversation_task import ConversationTaskRead

pytestmark = pytest.mark.anyio

_NOW = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)


@pytest.fixture
def caller(monkeypatch: pytest.MonkeyPatch) -> AuthContext:
    """A signed-in owner whose context must reach every personal queue operation."""
    ctx = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )
    monkeypatch.setitem(app.dependency_overrides, deps.get_auth_context, lambda: ctx)
    return ctx


@pytest.fixture
def accepted_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub the route's service boundary while keeping the request path real."""
    service = MagicMock(
        accept=AsyncMock(),
        list_pending=AsyncMock(),
        get_for_owner=AsyncMock(),
        cancel=AsyncMock(),
        run_as_task=AsyncMock(),
    )
    monkeypatch.setattr(
        routes,
        "AcceptedQueuedMessageService",
        MagicMock(return_value=service),
    )
    return service


def _url(conversation_id: UUID) -> str:
    return f"{settings.API_V1_STR}/conversations/{conversation_id}/queued-messages"


def _create_body() -> AcceptedQueuedMessageCreate:
    return AcceptedQueuedMessageCreate(
        client_queue_id=uuid4(),
        agent_id=uuid4(),
        content="Check the revised forecast",
    )


def _receipt_read(
    conversation_id: UUID,
    *,
    state: Literal["pending", "steering", "steered", "sent", "task", "cancelled"] = "pending",
    client_queue_id: UUID | None = None,
    agent_id: UUID | None = None,
    content: str = "Check the revised forecast",
    task_id: UUID | None = None,
    task_conversation_id: UUID | None = None,
) -> AcceptedQueuedMessageRead:
    return AcceptedQueuedMessageRead(
        id=uuid4(),
        conversation_id=conversation_id,
        client_queue_id=client_queue_id or uuid4(),
        agent_id=agent_id or uuid4(),
        content=content,
        file_ids=[],
        mentions=[],
        reply_to_message_id=None,
        reply_to_excerpt=None,
        page_context=None,
        local_target=None,
        state=state,
        message_id=uuid4(),
        task_id=task_id,
        task_conversation_id=task_conversation_id,
        steering_run_id=None,
        created_at=_NOW,
    )


def _task_read(*, source_conversation_id: UUID, conversation_id: UUID) -> ConversationTaskRead:
    return ConversationTaskRead(
        id=uuid4(),
        source_conversation_id=source_conversation_id,
        conversation_id=conversation_id,
        agent_id=uuid4(),
        title="Check the revised forecast",
        status="queued",
        delivery="pending",
        run_id=None,
        return_run_id=None,
        outcome=None,
        created_at=_NOW,
    )


async def test_accepting_a_queue_item_returns_its_durable_receipt(
    client: AsyncClient, caller: AuthContext, accepted_service: MagicMock
) -> None:
    conversation_id = uuid4()
    body = _create_body()
    receipt = _receipt_read(
        conversation_id,
        client_queue_id=body.client_queue_id,
        agent_id=body.agent_id,
        content=body.content,
    )
    accepted_service.accept.return_value = receipt

    response = await client.post(_url(conversation_id), json=body.model_dump(mode="json"))

    assert response.status_code == 201
    assert response.json()["id"] == str(receipt.id)
    assert response.json()["client_queue_id"] == str(body.client_queue_id)
    accepted_service.accept.assert_awaited_once_with(caller, conversation_id, body)


async def test_listing_passes_the_cursor_and_keeps_receipt_fields(
    client: AsyncClient, caller: AuthContext, accepted_service: MagicMock
) -> None:
    conversation_id, cursor = uuid4(), uuid4()
    receipt = _receipt_read(conversation_id, state="steering")
    accepted_service.list_pending.return_value = AcceptedQueuedMessageList(
        items=[receipt], next_cursor=cursor
    )

    response = await client.get(_url(conversation_id), params={"cursor": str(cursor)})

    assert response.status_code == 200
    assert response.json()["next_cursor"] == str(cursor)
    assert response.json()["items"][0]["id"] == str(receipt.id)
    assert response.json()["items"][0]["state"] == "steering"
    accepted_service.list_pending.assert_awaited_once_with(caller, conversation_id, cursor)


@pytest.mark.security
async def test_an_invalid_list_cursor_is_rejected_before_the_service(
    client: AsyncClient, caller: AuthContext, accepted_service: MagicMock
) -> None:
    response = await client.get(_url(uuid4()), params={"cursor": "not-a-uuid"})

    assert response.status_code == 422
    accepted_service.list_pending.assert_not_awaited()


async def test_reading_a_task_receipt_exposes_its_private_task_conversation(
    client: AsyncClient, caller: AuthContext, accepted_service: MagicMock
) -> None:
    source_conversation_id, task_conversation_id, task_id = uuid4(), uuid4(), uuid4()
    receipt = _receipt_read(
        source_conversation_id,
        state="task",
        task_id=task_id,
        task_conversation_id=task_conversation_id,
    )
    accepted_service.get_for_owner.return_value = receipt

    response = await client.get(f"{_url(source_conversation_id)}/{receipt.id}")

    assert response.status_code == 200
    assert response.json()["state"] == "task"
    assert response.json()["task_id"] == str(task_id)
    assert response.json()["task_conversation_id"] == str(task_conversation_id)
    accepted_service.get_for_owner.assert_awaited_once_with(
        caller, source_conversation_id, receipt.id
    )


@pytest.mark.security
async def test_a_receipt_from_another_owner_or_source_is_reported_as_missing(
    client: AsyncClient, caller: AuthContext, accepted_service: MagicMock
) -> None:
    """The service hides cross-owner/source receipts behind the same 404 as a miss."""
    conversation_id, receipt_id = uuid4(), uuid4()
    accepted_service.get_for_owner.side_effect = NotFoundError(message="Queue item not found")

    response = await client.get(f"{_url(conversation_id)}/{receipt_id}")

    assert response.status_code == 404
    accepted_service.get_for_owner.assert_awaited_once_with(caller, conversation_id, receipt_id)


async def test_cancelling_returns_the_terminal_receipt(
    client: AsyncClient, caller: AuthContext, accepted_service: MagicMock
) -> None:
    conversation_id = uuid4()
    receipt = _receipt_read(conversation_id, state="cancelled")
    accepted_service.cancel.return_value = receipt

    response = await client.delete(f"{_url(conversation_id)}/{receipt.id}")

    assert response.status_code == 200
    assert response.json()["state"] == "cancelled"
    assert response.json()["id"] == str(receipt.id)
    accepted_service.cancel.assert_awaited_once_with(caller, conversation_id, receipt.id)


async def test_run_as_task_returns_the_server_created_private_topic(
    client: AsyncClient, caller: AuthContext, accepted_service: MagicMock
) -> None:
    source_conversation_id, receipt_id, task_conversation_id = uuid4(), uuid4(), uuid4()
    task = _task_read(
        source_conversation_id=source_conversation_id,
        conversation_id=task_conversation_id,
    )
    accepted_service.run_as_task.return_value = task

    response = await client.post(f"{_url(source_conversation_id)}/{receipt_id}/run-as-task")

    assert response.status_code == 200
    assert response.json()["id"] == str(task.id)
    assert response.json()["source_conversation_id"] == str(source_conversation_id)
    assert response.json()["conversation_id"] == str(task_conversation_id)
    accepted_service.run_as_task.assert_awaited_once_with(
        caller, source_conversation_id, receipt_id
    )


@pytest.mark.security
async def test_personal_queue_requires_a_session_and_refuses_organization_keys(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A private personal queue is not reachable with an org API key."""
    api_keys = MagicMock(authenticate=AsyncMock())
    monkeypatch.setitem(app.dependency_overrides, deps.get_api_key_service, lambda: api_keys)

    signed_out = await client.get(_url(uuid4()))
    organization_key = await client.get(
        _url(uuid4()), headers={"Authorization": "Bearer aos_test-only-key"}
    )

    assert signed_out.status_code == 401
    assert organization_key.status_code == 403
    api_keys.authenticate.assert_not_awaited()
