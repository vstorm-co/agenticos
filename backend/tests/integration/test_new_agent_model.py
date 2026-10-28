"""The model a new agent starts on, read from Postgres and sent through the app (#2483).

The choice is a count over the organization's own profiles, so the part a mock
cannot vouch for is whose profiles are counted: another tenant's must never be
seen, let alone written into somebody's draft. The API half is the promise the
issue makes - an organization with one usable model creates agents that publish
without anybody touching Model, and one with none or several is told where Model is.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.main import app
from app.schemas.api_key import ApiKeyCreate
from app.services.agent_registry import NO_MODEL, AgentRegistryService
from app.services.api_key import ApiKeyService
from tests.integration._keys import chatgpt_sign_in, provider_key

pytestmark = pytest.mark.anyio

Client = Callable[[], AbstractAsyncContextManager[AsyncClient]]


@pytest.fixture
def client(db: AsyncSession) -> AsyncIterator[Client]:
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_redis] = lambda: MagicMock()

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            yield http

    yield open_client
    app.dependency_overrides.clear()


async def _organization(db: AsyncSession) -> tuple[Organization, AuthContext]:
    owner = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(owner)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return organization, AuthContext(
        user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER
    )


async def _profile(
    db: AsyncSession,
    organization: Organization,
    *,
    label: str = "openai default",
    model: str = "gpt-5.4",
    keyed: bool = True,
) -> ModelProfile:
    profile = ModelProfile(
        organization_id=organization.id,
        label=label,
        provider="openai",
        model=model,
        secret_id=await provider_key(db, organization.id) if keyed else None,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _created_model(db: AsyncSession, ctx: AuthContext) -> uuid.UUID | None:
    agent = await AgentRegistryService(db).create(
        ctx, AgentSpec(name=f"Bot {uuid.uuid4().hex[:6]}")
    )
    return AgentSpec.model_validate(agent.draft_spec).model_profile_id


async def test_the_organizations_only_model_is_written_into_a_new_draft(db: AsyncSession) -> None:
    organization, ctx = await _organization(db)
    only = await _profile(db, organization)
    # A speech model and a keyless one are not models an agent can run on.
    await _profile(db, organization, label="speech", model="gpt-4o-mini-tts")
    await _profile(db, organization, label="no key", keyed=False)

    assert await _created_model(db, ctx) == only.id


async def test_a_self_hosted_model_saved_without_a_key_is_one(db: AsyncSession) -> None:
    """No key on purpose is not a missing key (#2478), so it can be the only model."""
    organization, ctx = await _organization(db)
    local = ModelProfile(
        organization_id=organization.id,
        label="Ollama · llama4",
        provider="ollama",
        model="llama4",
        secret_id=None,
        base_url="http://ollama:11434/v1",
        runs_without_key=True,
    )
    db.add(local)
    await db.flush()

    assert await _created_model(db, ctx) == local.id


@pytest.mark.parametrize(
    "shape",
    [
        pytest.param([{}, {"label": "second"}], id="two"),
        pytest.param([{"keyed": False}], id="only-keyless"),
        pytest.param([{"model": "gpt-4o-mini-tts"}], id="only-text-to-speech"),
    ],
)
async def test_with_none_or_several_the_draft_has_no_model(
    db: AsyncSession, shape: list[dict]
) -> None:
    organization, ctx = await _organization(db)
    for fields in shape:
        await _profile(db, organization, **fields)

    assert await _created_model(db, ctx) is None


@pytest.mark.security
async def test_a_model_that_falls_back_to_a_chatgpt_sign_in_is_never_chosen(
    db: AsyncSession,
) -> None:
    """An outage would hand the new agent's runs to one person's subscription (#2545).

    The sign-in is a model of its own too, so this organization has two either way;
    the case pins the outcome the issue asks for, whichever half decides it."""
    organization, ctx = await _organization(db)
    sign_in = ModelProfile(
        organization_id=organization.id,
        label="my ChatGPT",
        provider="openai_codex",
        model="gpt-5.4",
        secret_id=await chatgpt_sign_in(db, organization.id, owner_id=ctx.user_id),
    )
    db.add(sign_in)
    await db.flush()
    keyed = await _profile(db, organization)
    keyed.fallback_profile_ids = [str(sign_in.id)]
    await db.flush()

    assert await _created_model(db, ctx) is None


@pytest.mark.security
async def test_another_organizations_model_is_never_chosen(db: AsyncSession) -> None:
    """Its one model is not this organization's, and neither does it make two here."""
    organization, ctx = await _organization(db)
    other, _ = await _organization(db)
    theirs = await _profile(db, other)

    assert await _created_model(db, ctx) is None

    ours = await _profile(db, organization)
    created = await _created_model(db, ctx)
    assert created == ours.id
    assert created != theirs.id


async def _issue(db: AsyncSession, ctx: AuthContext) -> dict[str, str]:
    created = await ApiKeyService(db).create(
        ctx,
        ApiKeyCreate(
            name="script", scopes=[Perm.AGENTS_VIEW, Perm.AGENTS_EDIT, Perm.AGENTS_PUBLISH]
        ),
    )
    return {"Authorization": f"Bearer {created.key}"}


def _url(path: str) -> str:
    return f"{settings.API_V1_STR}{path}"


async def test_an_agent_created_over_the_api_publishes_untouched(
    db: AsyncSession, client: Client
) -> None:
    organization, ctx = await _organization(db)
    only = await _profile(db, organization)
    headers = await _issue(db, ctx)

    async with client() as http:
        created = await http.post(_url("/agents"), headers=headers, json={"spec": {"name": "Bot"}})
        agent_id = created.json()["id"]
        draft = await http.get(_url(f"/agents/{agent_id}"), headers=headers)
        published = await http.post(
            _url(f"/agents/{agent_id}/publish"), headers=headers, json={"note": None}
        )

    assert created.status_code == 201
    assert draft.json()["draft_spec"]["model_profile_id"] == str(only.id)
    assert published.status_code == 200, published.text


async def test_with_two_models_publish_points_to_the_model_field(
    db: AsyncSession, client: Client
) -> None:
    organization, ctx = await _organization(db)
    await _profile(db, organization)
    await _profile(db, organization, label="second")
    headers = await _issue(db, ctx)

    async with client() as http:
        created = await http.post(_url("/agents"), headers=headers, json={"spec": {"name": "Bot"}})
        agent_id = created.json()["id"]
        draft = await http.get(_url(f"/agents/{agent_id}"), headers=headers)
        refused = await http.post(
            _url(f"/agents/{agent_id}/publish"), headers=headers, json={"note": None}
        )

    assert draft.json()["draft_spec"]["model_profile_id"] is None
    assert refused.status_code == 400
    details = refused.json()["error"]["details"]
    assert details["problems"] == [NO_MODEL]
    assert details["fields"] == [{"field": "model_profile_id", "message": NO_MODEL}]
