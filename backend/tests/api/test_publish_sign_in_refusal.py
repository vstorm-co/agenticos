"""Publishing on somebody else's ChatGPT sign-in, refused through the app (#2546).

The registry decides; what is asserted here is how the refusal *arrives*: a 400
whose `problems` the Builder lists and whose `fields` name `model_profile_id`,
from the draft check and from publish alike. The registry is the real one; the
agent lookup, the profile and vault reads and `resolve_access` are stubbed, so
nothing reaches a database.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import SecretKind
from app.main import app
from app.services import agent_registry
from app.services.agent_registry import AgentRegistryService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_ORG = uuid.uuid4()
_AGENT = uuid.uuid4()
_MESSAGE = (
    "Model 'Ada's Codex' runs on somebody's own ChatGPT sign-in, which you cannot use - "
    "pick another model, or ask its owner to share the sign-in with you"
)


@pytest.fixture
def client(
    mock_db_session: Any, mock_redis: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Any]:
    user = MagicMock()
    user.id = uuid.uuid4()
    context = AuthContext(user_id=user.id, organization_id=_ORG, role=OrgRoleName.BUILDER)

    sign_in = MagicMock(id=uuid.uuid4(), organization_id=_ORG, kind=SecretKind.OPENAI_CODEX.value)
    profile = MagicMock(id=uuid.uuid4(), secret_id=sign_in.id, fallback_profile_ids=[])
    profile.label = "Ada's Codex"
    agent = MagicMock(
        id=_AGENT, draft_spec={"name": "Helpdesk", "model_profile_id": str(profile.id)}
    )

    monkeypatch.setattr(AgentRegistryService, "get", AsyncMock(return_value=agent))
    # The profile is a chat model with a key; that half of publish is not the subject.
    monkeypatch.setattr(AgentRegistryService, "model_profile_problems", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        agent_registry.credential_repo,
        "get_profiles_by_ids",
        AsyncMock(return_value={profile.id: profile}),
    )
    monkeypatch.setattr(
        agent_registry.organization_secret_repo,
        "get_many",
        AsyncMock(return_value={sign_in.id: sign_in}),
    )
    monkeypatch.setattr(agent_registry, "resolve_access", AsyncMock(return_value=False))

    app.dependency_overrides[deps.get_db_session] = lambda: mock_db_session
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_auth_context] = lambda: context

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
            yield opened

    yield open_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("path", "body"), [("validate", {}), ("publish", {"note": None})], ids=["draft", "publish"]
)
async def test_the_refusal_names_the_model_input(client, path: str, body: dict) -> None:
    async with client() as opened:
        response = await opened.post(f"{settings.API_V1_STR}/agents/{_AGENT}/{path}", json=body)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["message"] == "This agent cannot be published yet"
    assert error["details"]["problems"] == [_MESSAGE]
    assert error["details"]["fields"] == [{"field": "model_profile_id", "message": _MESSAGE}]
