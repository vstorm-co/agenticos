"""The public API answers what its OpenAPI document says it answers (#1796).

`tests/api/test_public_openapi.py` checks the document on its own: every
reference resolves, every operation needs a key and declares the error
envelope. What only the real app against a real database can show is the other
half - that a call made with an organization key comes back in the shape the
document publishes for it, on success and on refusal, so a client generated from
the document parses what the server sends.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, Perm
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.main import app
from app.schemas.api_key import ApiKeyCreate
from app.services.api_key import ApiKeyService

pytestmark = pytest.mark.anyio

DOCUMENT_URI = "urn:agenticos:public-api"

# Collection reads a fresh organization can answer without a model, a vector
# store or a connected service - one per tag where the tag has one.
READS = (
    "/me/permissions",
    "/roles/catalog",
    "/ml/services",
    "/agents",
    "/agents/capabilities",
    "/agents/templates",
    "/agents/prompt-variables",
    "/runs",
    "/approvals",
    "/spend",
    "/skills",
    "/skills/gallery",
    "/context",
    "/apps",
    "/kb",
)


@pytest.fixture
async def http(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_redis] = lambda: MagicMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def document(http: AsyncClient) -> dict[str, Any]:
    answer = await http.get(f"{settings.API_V1_STR}/public/openapi.json")
    assert answer.status_code == 200
    return answer.json()


async def _owner_and_key(db: AsyncSession, *scopes: Perm) -> str:
    """An organization, its owner, and a key holding `scopes` (all of the owner's by default)."""
    owner = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(owner)
    await db.flush()
    organization = Organization(
        name="Contract", slug=f"contract-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")
    service = ApiKeyService(db)
    granted = list(scopes) or [Perm(scope) for scope in service.scope_catalog(ctx).scopes]
    created = await service.create(ctx, ApiKeyCreate(name="contract", scopes=granted))
    return created.key


def _pointer(*parts: str) -> str:
    return "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


def _assert_matches(document: dict[str, Any], path: str, status: str, body: Any) -> None:
    """Validate `body` against what the document publishes for `GET path` answering `status`."""
    operation = document["paths"][path]["get"]
    assert status in operation["responses"], f"{path} does not document a {status}"
    pointer = _pointer(
        "paths", path, "get", "responses", status, "content", "application/json", "schema"
    )
    registry = Registry().with_resource(
        DOCUMENT_URI, Resource.from_contents(document, default_specification=DRAFT202012)
    )
    validator = Draft202012Validator({"$ref": f"{DOCUMENT_URI}#/{pointer}"}, registry=registry)
    problems = [
        f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in validator.iter_errors(body)
    ]
    assert not problems, f"GET {path} {status} breaks its schema: {problems[:3]}"


@pytest.mark.parametrize("path", READS)
async def test_a_keys_read_answers_the_schema_the_document_publishes(
    db: AsyncSession, http: AsyncClient, document: dict[str, Any], path: str
) -> None:
    key = await _owner_and_key(db)

    answer = await http.get(
        f"{settings.API_V1_STR}{path}", headers={"Authorization": f"Bearer {key}"}
    )

    assert answer.status_code == 200, answer.text
    _assert_matches(document, f"{settings.API_V1_STR}{path}", "200", answer.json())


@pytest.mark.security
async def test_each_refusal_answers_the_envelope_the_document_publishes(
    db: AsyncSession, http: AsyncClient, document: dict[str, Any]
) -> None:
    """No key, a key without the permission, and a row that is not there."""
    narrow = await _owner_and_key(db, Perm.AGENTS_VIEW)
    agents = f"{settings.API_V1_STR}/agents"
    runs = f"{settings.API_V1_STR}/runs"
    one_agent = f"{settings.API_V1_STR}/agents/{{agent_id}}"

    anonymous = await http.get(agents)
    forbidden = await http.get(runs, headers={"Authorization": f"Bearer {narrow}"})
    missing = await http.get(
        f"{agents}/{uuid.uuid4()}", headers={"Authorization": f"Bearer {narrow}"}
    )

    assert (anonymous.status_code, forbidden.status_code, missing.status_code) == (401, 403, 404)
    assert anonymous.headers["WWW-Authenticate"].startswith("Bearer")
    _assert_matches(document, agents, "401", anonymous.json())
    _assert_matches(document, runs, "403", forbidden.json())
    _assert_matches(document, one_agent, "404", missing.json())
