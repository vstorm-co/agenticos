"""Creating and changing a bot names who did it, for the audit of opening a public line."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.channel_bot import ChannelBotRead
from tests.test_whatsapp_bot import _row, _whatsapp

pytestmark = pytest.mark.anyio


async def _call(method: str, path: str, body: dict, *, role: str = OrgRoleName.ADMIN):
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)
    bot = ChannelBotRead.model_validate(_row(), from_attributes=True)
    service = AsyncMock()
    service.create.return_value = bot
    service.update.return_value = bot
    app.dependency_overrides[deps.get_org_channel_bot_service] = lambda: service
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            answer = await http.request(
                method, f"{settings.API_V1_STR}/channels/bots{path}", json=body
            )
    finally:
        app.dependency_overrides.clear()
    return answer.status_code, service, ctx


@pytest.mark.security
async def test_a_created_bot_is_attributed_to_the_caller() -> None:
    status, service, ctx = await _call("POST", "", _whatsapp())

    assert status == 201
    assert service.create.await_args.kwargs == {"actor_user_id": ctx.subject_id}


@pytest.mark.security
async def test_an_updated_bot_is_attributed_to_the_caller() -> None:
    bot_id = uuid.uuid4()

    status, service, ctx = await _call(
        "PATCH", f"/{bot_id}", {"access_policy": {"answer_unlinked_direct": False}}
    )

    assert status == 200
    assert service.update.await_args.args[0] == bot_id
    assert service.update.await_args.kwargs == {"actor_user_id": ctx.subject_id}
