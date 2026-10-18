"""The console's chat socket refuses an organization API key (Codex review of #2062)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes.v1.agent import agent_websocket
from app.core.permissions import AuthContext
from app.services.api_key import KeyCaller

pytestmark = pytest.mark.anyio


@pytest.mark.security
async def test_a_key_is_refused_before_the_socket_is_accepted() -> None:
    """A run on this socket is a person at the keyboard - their personal
    connections and no per-key limit - which a key is not."""
    organization_id = uuid.uuid4()
    websocket = MagicMock()
    websocket.close = AsyncMock()
    websocket.accept = AsyncMock()
    websocket.state.api_key_caller = KeyCaller(
        user=MagicMock(),
        organization=MagicMock(id=organization_id),
        context=AuthContext(user_id=uuid.uuid4(), organization_id=organization_id, role="owner"),
        api_key_id=uuid.uuid4(),
        prefix="aos_0123abcd",
    )

    await agent_websocket(websocket, MagicMock(), MagicMock())

    websocket.close.assert_awaited_once_with(
        code=4003, reason="API keys are not accepted on the chat socket"
    )
    websocket.accept.assert_not_awaited()
