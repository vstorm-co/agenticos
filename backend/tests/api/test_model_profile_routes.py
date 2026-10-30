"""Creating a model profile over the wire: the API choice reaches the service.

The service tests call `create_profile` directly, so a route that stopped passing
`api` along would leave every console-created profile on its provider's default -
a regional OpenAI endpoint that picked Responses quietly back on Chat Completions.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api import deps
from app.api.routes.v1 import model_providers
from app.core.config import settings
from app.core.exceptions import InUseError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.model_profile import ModelProfileRead
from app.services.model_catalog import CatalogModel

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


@pytest.fixture
def owner() -> Iterator[None]:
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=OrgRoleName.OWNER.value,
        is_app_admin=False,
    )
    yield
    app.dependency_overrides.clear()


def _stored(model: str) -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(),
        label=f"OpenAI · {model}",
        provider="openai",
        secret_id=uuid.uuid4(),
        model=model,
        base_url=None,
        api="responses",
        params={},
        fallback_profile_ids=[],
        context_length=None,
        runs_without_key=False,
        created_at=datetime(2026, 10, 26, tzinfo=UTC),
        updated_at=None,
    )


async def test_the_listing_keeps_a_speech_model_and_says_an_agent_cannot_run_on_it(
    client: AsyncClient, owner: None
):
    # Every profile is listed - text to speech runs on the speech one - and each
    # says whether an agent can, so pickers filter without a second request (#2487).
    service = MagicMock(
        list_profiles=AsyncMock(return_value=[_stored("gpt-4.1"), _stored("gpt-4o-mini-tts")])
    )
    app.dependency_overrides[deps.get_model_profile_service] = lambda: service

    response = await client.get(f"{_V1}/providers/model-profiles")

    assert response.status_code == 200
    assert [
        (item["model"], item["chat_capable"], item["output_modalities"])
        for item in response.json()["items"]
    ] == [("gpt-4.1", True, []), ("gpt-4o-mini-tts", False, ["audio"])]


async def test_a_providers_models_say_which_an_agent_can_run_on(
    client: AsyncClient, owner: None, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        model_providers,
        "models_for",
        AsyncMock(
            return_value=(
                [
                    CatalogModel(id="gpt-4.1", name="GPT-4.1"),
                    CatalogModel(id="gpt-4o-mini-tts", name="gpt-4o-mini-tts"),
                ],
                "live",
            )
        ),
    )
    app.dependency_overrides[deps.get_secret_service] = lambda: MagicMock(
        listing_key=AsyncMock(return_value="sk-test")
    )

    response = await client.get(f"{_V1}/providers/openai/models")

    assert response.status_code == 200
    assert {item["id"]: item["chat_capable"] for item in response.json()["items"]} == {
        "gpt-4.1": True,
        "gpt-4o-mini-tts": False,
    }


async def test_an_edit_reaches_the_service_with_only_what_was_sent(
    client: AsyncClient, owner: None
):
    stored = _stored("gpt-4.1")
    stored.secret_id = None
    update = AsyncMock(return_value=stored)
    app.dependency_overrides[deps.get_model_profile_service] = lambda: MagicMock(
        update_profile=update
    )
    secret_id = uuid.uuid4()

    response = await client.patch(
        f"{_V1}/providers/model-profiles/{stored.id}", json={"secret_id": str(secret_id)}
    )

    assert response.status_code == 200
    _, profile_id, changes = update.await_args.args
    assert profile_id == stored.id
    # What was not sent stays unset, so the service leaves it as it is.
    assert changes.model_fields_set == {"secret_id"}
    assert changes.secret_id == secret_id
    body = response.json()
    assert body["id"] == str(stored.id)
    # A profile on OpenAI's own API with no key cannot run, and says so (#2478).
    assert body["missing_key"] is True


async def test_an_edit_that_sends_an_unknown_api_is_refused(client: AsyncClient, owner: None):
    update = AsyncMock()
    app.dependency_overrides[deps.get_model_profile_service] = lambda: MagicMock(
        update_profile=update
    )

    response = await client.patch(
        f"{_V1}/providers/model-profiles/{uuid.uuid4()}", json={"api": "realtime"}
    )

    assert response.status_code == 422
    update.assert_not_awaited()


async def test_a_model_in_use_answers_409_naming_its_agents(client: AsyncClient, owner: None):
    agent_id = uuid.uuid4()
    refusal = InUseError(
        message="Model 'X' is used by 1 agent: Helpdesk.",
        details={"agents": [{"id": agent_id, "name": "Helpdesk"}], "hidden_agents": 0},
    )
    app.dependency_overrides[deps.get_model_profile_service] = lambda: MagicMock(
        delete_profile=AsyncMock(side_effect=refusal)
    )

    response = await client.delete(f"{_V1}/providers/model-profiles/{uuid.uuid4()}")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "IN_USE"
    assert error["details"]["agents"] == [{"id": str(agent_id), "name": "Helpdesk"}]
