"""Creating a model profile over the wire: the API choice reaches the service.

The service tests call `create_profile` directly, so a route that stopped passing
`api` along would leave every console-created profile on its provider's default -
a regional OpenAI endpoint that picked Responses quietly back on Chat Completions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.model_profile import ModelProfileRead

pytestmark = pytest.mark.anyio

_V1 = settings.API_V1_STR


@pytest.fixture
def created() -> AsyncMock:
    """The service's `create_profile`, answering with a profile on Responses."""
    create = AsyncMock(
        return_value=ModelProfileRead(
            id=uuid.uuid4(),
            label="OpenAI EU · gpt-6-luna",
            provider="openai",
            secret_id=uuid.uuid4(),
            model="gpt-6-luna",
            base_url="https://eu.api.openai.com/v1",
            api="responses",
            created_at=datetime(2026, 10, 8, tzinfo=UTC),
        )
    )
    service = MagicMock(create_profile=create)
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )
    app.dependency_overrides[deps.get_model_profile_service] = lambda: service
    yield create
    app.dependency_overrides.clear()


def _profile(**overrides: object) -> dict[str, object]:
    return {
        "label": "OpenAI EU · gpt-6-luna",
        "provider": "openai",
        "model": "gpt-6-luna",
        "secret_id": str(uuid.uuid4()),
        "base_url": "https://eu.api.openai.com/v1",
        **overrides,
    }


async def test_the_chosen_api_reaches_the_service(client: AsyncClient, created: AsyncMock):
    response = await client.post(f"{_V1}/providers/model-profiles", json=_profile(api="responses"))

    assert response.status_code == 201
    assert created.await_args.kwargs["api"] == "responses"
    assert response.json()["api"] == "responses"


async def test_an_omitted_api_is_left_for_the_service_to_default(
    client: AsyncClient, created: AsyncMock
):
    await client.post(f"{_V1}/providers/model-profiles", json=_profile())

    assert created.await_args.kwargs["api"] is None


async def test_an_api_the_platform_does_not_know_is_refused(
    client: AsyncClient, created: AsyncMock
):
    response = await client.post(f"{_V1}/providers/model-profiles", json=_profile(api="realtime"))

    assert response.status_code == 422
    created.assert_not_awaited()
