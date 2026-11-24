"""Destination pickers use scoped catalogs and keep published-version ownership explicit."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.schemas.resource_bundle import BundleDestinationQuery, BundleResourceKind
from app.services.portability.destinations import BundleDestinations
from app.services.portability.facade import PortabilityService

pytestmark = pytest.mark.anyio


def actor() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")


@pytest.mark.parametrize(
    "kind,path,shape",
    [
        ("context", "ContextService.list_context", "page"),
        ("skill", "SkillService.list_skills", "page"),
        ("agent", "AgentRegistryService.list_agents", "page"),
        ("agent_version", "AgentRegistryService.list_versions", "page"),
        ("skill_version", "SkillVersionService.list_versions", "items"),
        ("skill_fork", "SkillVersionService.list_forks", "items"),
        ("model_profile", "ModelProfileService.list_profiles", "list"),
        ("mcp_connection", "McpConnectionService.list_for_org", "page"),
        ("secret", "OrganizationSecretService.list_secrets", "list"),
        ("knowledge_base", "KnowledgeBaseService.list_accessible", "list"),
        ("sandbox_connection", "SandboxConnectionService.list_connections", "list"),
    ],
)
async def test_names_are_listed_under_destination_authority_without_loading_definitions(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, kind: str, path: str, shape: str
) -> None:
    row = SimpleNamespace(
        id=uuid4(),
        name="Policy",
        label="Provider",
        version=2,
        number=3,
        sealed_value="NEVER RETURN THIS",
    )
    result = (
        ([row], 1)
        if shape == "page"
        else SimpleNamespace(items=[row], total=1)
        if shape == "items"
        else [row]
    )
    listing = AsyncMock(return_value=result)
    monkeypatch.setattr(f"app.services.portability.destinations.{path}", listing)
    ctx = actor()
    query = BundleDestinationQuery(kind=BundleResourceKind(kind), parent_id=uuid4())
    data = await BundleDestinations(mock_db_session).list(ctx, query)
    assert data.total == 1 and data.items[0].id == row.id
    assert data.items[0].name == (
        "v2"
        if kind == "agent_version"
        else "v3"
        if kind == "skill_version"
        else "Provider"
        if kind in ("model_profile", "mcp_connection")
        else "Policy"
    )
    assert "NEVER RETURN THIS" not in data.model_dump_json()
    assert listing.await_args.args[0] == ctx
    if kind in ("agent_version", "skill_version", "skill_fork"):
        assert listing.await_args.args[1] == query.parent_id


async def test_catalog_search_sort_and_paging_never_promote_uploaded_names(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [SimpleNamespace(id=uuid4(), name=name) for name in ("Zulu key", "Alpha key", "Other")]
    monkeypatch.setattr(
        "app.services.portability.destinations.OrganizationSecretService.list_secrets",
        AsyncMock(return_value=rows),
    )
    service = BundleDestinations(mock_db_session)
    result = await service.list(
        actor(),
        BundleDestinationQuery(kind=BundleResourceKind.SECRET, search="KEY", skip=1, limit=1),
    )
    assert result.total == 2
    assert [item.name for item in result.items] == ["Zulu key"]


async def test_unlabelled_mcp_connections_keep_their_authorized_name(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.portability.destinations.McpConnectionService.list_for_org",
        AsyncMock(return_value=([SimpleNamespace(id=uuid4(), name="github", label=None)], 1)),
    )
    result = await BundleDestinations(mock_db_session).list(
        actor(), BundleDestinationQuery(kind=BundleResourceKind.MCP_CONNECTION)
    )
    assert result.items[0].name == "github"


@pytest.mark.parametrize("kind", ["agent_version", "skill_version", "skill_fork"])
async def test_version_picker_requires_a_destination_parent(
    mock_db_session: AsyncMock, kind: str
) -> None:
    with pytest.raises(BadRequestError, match="existing destination owner"):
        await BundleDestinations(mock_db_session).list(
            actor(), BundleDestinationQuery(kind=BundleResourceKind(kind))
        )


@pytest.mark.parametrize("kind", ["agent", "agent_version", "skill_version"])
async def test_unavailable_name_filter_is_not_silently_ignored(
    mock_db_session: AsyncMock, kind: str
) -> None:
    with pytest.raises(BadRequestError, match="without a name filter"):
        await BundleDestinations(mock_db_session).list(
            actor(), BundleDestinationQuery(kind=BundleResourceKind(kind), search="something")
        )


@pytest.mark.parametrize("kind", ["model_profile", "mcp_connection", "sandbox_connection"])
async def test_catalog_permission_refusal_precedes_the_lookup(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    monkeypatch.setattr(AuthContext, "has", lambda self, permission: False)
    with pytest.raises(AuthorizationError):
        await BundleDestinations(mock_db_session).list(
            actor(), BundleDestinationQuery(kind=BundleResourceKind(kind))
        )
    mock_db_session.execute.assert_not_awaited()


async def test_revocation_or_cross_tenant_failure_is_not_presented_as_an_empty_picker(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.portability.destinations.ContextService.list_context",
        AsyncMock(side_effect=NotFoundError(message="Not found")),
    )
    with pytest.raises(NotFoundError):
        await BundleDestinations(mock_db_session).list(
            actor(), BundleDestinationQuery(kind=BundleResourceKind.CONTEXT)
        )
    with pytest.raises(BadRequestError, match="owning editor"):
        await BundleDestinations(mock_db_session).list(
            actor(), BundleDestinationQuery(kind=BundleResourceKind.TABLE)
        )


async def test_facade_forwards_only_current_authority_and_typed_query(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = AsyncMock(return_value=SimpleNamespace(items=[], total=0))
    monkeypatch.setattr(BundleDestinations, "list", listing)
    ctx, query = actor(), BundleDestinationQuery(kind=BundleResourceKind.CONTEXT)
    await PortabilityService(mock_db_session).destinations(ctx, query)
    listing.assert_awaited_once_with(ctx, query)
