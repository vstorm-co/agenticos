"""Every exported dependency uses its owner's access boundary and a field allowlist."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.schemas.resource_bundle import BundleResource, BundleResourceKind
from app.services.portability.content import (
    ContextContent,
    McpContent,
    ModelContent,
    SkillContent,
    SkillSnapshotContent,
)
from app.services.portability.sources import BundleSources

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("with_content", [True, False])
@pytest.mark.parametrize(
    "kind,method,fields,content_type",
    [
        (
            "agent",
            "AgentRegistryService.get",
            {"name": "Agent", "draft_spec": AgentSpec(name="Agent").model_dump(mode="json")},
            AgentSpec,
        ),
        (
            "agent_version",
            "AgentRegistryService.get_version",
            {"spec": AgentSpec(name="Agent").model_dump(mode="json")},
            AgentSpec,
        ),
        (
            "context",
            "ContextService.get",
            {
                "name": "Policy",
                "description": None,
                "content": "  retain whitespace\n",
                "format": "md",
                "mode": "link",
            },
            ContextContent,
        ),
        (
            "model_profile",
            "ModelProfileService.profile_for_organization",
            {
                "label": "Model",
                "provider": "openai",
                "model": "gpt-4.1",
                "secret_id": None,
                "base_url": None,
                "api": "responses",
                "region": None,
                "params": {"temperature": 0.2},
                "fallback_profile_ids": [],
            },
            ModelContent,
        ),
        (
            "mcp_connection",
            "McpConnectionService.get_org_connection",
            {
                "name": "notion",
                "label": "Notion",
                "url": "https://example.org/mcp",
                "allowed_tools": ["read"],
                "include_instructions": True,
                "trust_read_only_hints": False,
                "catalog_key": None,
                "auth_token": "SEALED ENVELOPE",
                "oauth_payload": {"refresh_token": "POISON"},
            },
            McpContent,
        ),
        (
            "secret",
            "OrganizationSecretService.get_metadata",
            {"name": "API key", "sealed_secret": "POISON"},
            type(None),
        ),
        ("knowledge_base", "KnowledgeBaseService.get", {"name": "Knowledge"}, type(None)),
        ("sandbox_connection", "SandboxConnectionService.get", {"name": "Sandbox"}, type(None)),
    ],
)
async def test_source_adapters_use_scoped_services_and_never_serialize_storage_rows(
    mock_db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    method: str,
    fields: dict[str, object],
    content_type: type,
    with_content: bool,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    identity, parent = uuid4(), uuid4()
    row = SimpleNamespace(id=identity, **fields)
    read = AsyncMock(return_value=row)
    monkeypatch.setattr(f"app.services.portability.sources.{method}", read)
    resource = BundleResource(
        key=f"{kind}/{identity}",
        kind=BundleResourceKind(kind),
        source_id=identity,
        source_parent_id=parent if kind == "agent_version" else None,
        name="Source",
    )
    result = await BundleSources(mock_db_session).read(ctx, resource, with_content=with_content)
    assert result.id == identity
    assert isinstance(result.content, content_type if with_content else type(None))
    assert "POISON" not in str(result.definition)
    assert "SEALED ENVELOPE" not in str(result.definition)
    if kind == "model_profile":
        assert read.await_args.args[0] == ctx.organization_id
        assert read.await_args.kwargs["profile_id"] == identity
    elif kind == "knowledge_base":
        assert read.await_args.kwargs["ctx"] == ctx
    else:
        assert read.await_args.args[0] == ctx


@pytest.mark.parametrize("kind", ["mcp_connection", "model_profile", "sandbox_connection"])
@pytest.mark.security
async def test_configuration_permissions_are_checked_before_the_resource_read(
    mock_db_session: AsyncMock, kind: str
) -> None:
    ctx = AuthContext(
        user_id=uuid4(), organization_id=uuid4(), role="viewer", key_scopes=frozenset()
    )
    resource = BundleResource(
        key=f"{kind}/{uuid4()}", kind=BundleResourceKind(kind), source_id=uuid4(), name="Source"
    )
    with pytest.raises(AuthorizationError):
        await BundleSources(mock_db_session).read(ctx, resource)
    mock_db_session.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "kind,parent,number",
    [
        ("skill_version", False, "3"),
        ("skill_version", True, None),
        ("skill_version", True, "bad"),
        ("agent_version", False, None),
        ("skill_fork", False, None),
        ("app", False, None),
    ],
)
async def test_missing_version_owners_or_unsupported_kinds_are_explicit_refusals(
    mock_db_session: AsyncMock, kind: str, parent: bool, number: str | None
) -> None:
    resource = BundleResource(
        key=f"{kind}/source",
        kind=BundleResourceKind(kind),
        name="Source",
        source_id=uuid4(),
        source_parent_id=uuid4() if parent else None,
        source_version=number,
    )
    with pytest.raises(BadRequestError):
        await BundleSources(mock_db_session).read(
            AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"), resource
        )


@pytest.mark.parametrize("kind", ["context", "skill"])
async def test_reference_without_source_identity_is_not_guessed(
    mock_db_session: AsyncMock, kind: str
) -> None:
    resource = BundleResource(key=f"{kind}/source", kind=BundleResourceKind(kind), name="Source")
    with pytest.raises(BadRequestError, match="source resource"):
        await BundleSources(mock_db_session).read(
            AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"), resource
        )


@pytest.mark.parametrize("kind", ["skill", "skill_version", "skill_fork"])
async def test_skill_copy_reads_the_exact_snapshot_and_its_file_descriptions(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    skill_id, version_id, fork_id = uuid4(), uuid4(), uuid4()
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    monkeypatch.setattr(
        "app.services.portability.sources.SkillVersionService.skill_for",
        AsyncMock(
            return_value=SimpleNamespace(
                id=skill_id, name="policy", category="support", content="latest, not the pin"
            )
        ),
    )
    snapshot = AsyncMock(
        return_value=SimpleNamespace(
            id=version_id,
            number=3,
            description="Pinned description",
            content="Pinned body",
            resources={"reference.md": {"description": "Read this", "size_bytes": 7}},
        )
    )
    monkeypatch.setattr(
        "app.services.portability.sources.SkillVersionService.export_snapshot", snapshot
    )
    monkeypatch.setattr(
        "app.services.portability.sources.SkillVersionService.files_of",
        AsyncMock(return_value={"reference.md": "  exact\n"}),
    )
    monkeypatch.setattr(
        "app.services.portability.sources.SkillVersionService.get_fork",
        AsyncMock(return_value=SimpleNamespace(name="regional")),
    )
    identity = fork_id if kind == "skill_fork" else skill_id if kind == "skill" else None
    resource = BundleResource(
        key=f"{kind}/source",
        kind=BundleResourceKind(kind),
        name="Source",
        source_id=identity,
        source_parent_id=skill_id if kind != "skill" else None,
        source_version="3" if kind == "skill_version" else None,
    )
    result = await BundleSources(mock_db_session).read(ctx, resource)
    assert isinstance(result.content, SkillContent)
    assert result.content.content == "Pinned body"
    assert result.content.files[0].content == "  exact\n"
    assert result.content.files[0].description == "Read this"
    if kind != "skill":
        assert isinstance(result.content, SkillSnapshotContent)
        assert result.content.skill_id == skill_id
        assert result.parent_id == skill_id
    assert snapshot.await_args.kwargs["number"] == (3 if kind == "skill_version" else None)
    assert snapshot.await_args.kwargs["fork_id"] == (fork_id if kind == "skill_fork" else None)


async def test_large_skill_file_manifests_are_refused_before_loading_file_bodies(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = uuid4()
    monkeypatch.setattr(
        "app.services.portability.sources.SkillVersionService.skill_for",
        AsyncMock(return_value=SimpleNamespace(id=identity, name="large", category=None)),
    )
    monkeypatch.setattr(
        "app.services.portability.sources.SkillVersionService.export_snapshot",
        AsyncMock(
            return_value=SimpleNamespace(
                resources={str(index): {"size_bytes": 0} for index in range(1001)}
            )
        ),
    )
    files = AsyncMock()
    monkeypatch.setattr("app.services.portability.sources.SkillVersionService.files_of", files)
    with pytest.raises(BadRequestError, match="file bundle"):
        await BundleSources(mock_db_session).read(
            AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
            BundleResource(
                key=f"skill/{identity}",
                kind=BundleResourceKind.SKILL,
                name="Large",
                source_id=identity,
            ),
        )
    files.assert_not_awaited()


@pytest.mark.parametrize("kind", ["skill", "skill_version", "skill_fork"])
async def test_reusing_a_large_skill_needs_only_identity_and_version_metadata(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    owner, version, fork = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(
        "app.services.portability.sources.SkillVersionService.skill_for",
        AsyncMock(return_value=SimpleNamespace(id=owner, name="policy", category=None)),
    )
    monkeypatch.setattr(
        "app.services.portability.sources.SkillVersionService.export_snapshot",
        AsyncMock(
            return_value=SimpleNamespace(
                id=version,
                number=3,
                resources={str(index): {"size_bytes": 0} for index in range(1001)},
            )
        ),
    )
    monkeypatch.setattr(
        "app.services.portability.sources.SkillVersionService.get_fork",
        AsyncMock(return_value=SimpleNamespace(name="regional")),
    )
    files = AsyncMock(side_effect=AssertionError("Metadata reads must not open file bodies"))
    monkeypatch.setattr("app.services.portability.sources.SkillVersionService.files_of", files)
    resource = BundleResource(
        key=f"{kind}/source",
        kind=BundleResourceKind(kind),
        name="Source",
        source_id=owner if kind == "skill" else fork if kind == "skill_fork" else None,
        source_parent_id=owner if kind != "skill" else None,
        source_version="3" if kind == "skill_version" else None,
    )
    result = await BundleSources(mock_db_session).read(
        AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
        resource,
        with_content=False,
    )
    assert result.content is None
    assert result.id == (owner if kind == "skill" else fork if kind == "skill_fork" else version)
    assert result.parent_id == (None if kind == "skill" else owner)
    files.assert_not_awaited()


@pytest.mark.parametrize("with_content", [True, False])
@pytest.mark.parametrize(
    "kind,method,fields",
    [
        (
            "mcp_connection",
            "McpConnectionService.get_org_connection",
            {
                "name": "custom",
                "label": None,
                "url": "https://mcp.example.test/endpoint?arbitrary=PRIVATE-URL-VALUE",
            },
        ),
        (
            "model_profile",
            "ModelProfileService.profile_for_organization",
            {
                "label": "Custom model",
                "base_url": "https://models.example.test/api?arbitrary=PRIVATE-URL-VALUE",
                "params": {},
            },
        ),
        (
            "model_profile",
            "ModelProfileService.profile_for_organization",
            {
                "label": "Custom model",
                "base_url": None,
                "params": {"extra_headers": {"X-Custom": "PRIVATE-HEADER-VALUE"}},
            },
        ),
    ],
)
async def test_opaque_connection_parameters_are_references_not_exported_credentials(
    mock_db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    with_content: bool,
    kind: str,
    method: str,
    fields: dict[str, object],
) -> None:
    identity = uuid4()
    monkeypatch.setattr(
        f"app.services.portability.sources.{method}",
        AsyncMock(return_value=SimpleNamespace(id=identity, **fields)),
    )
    source = await BundleSources(mock_db_session).read(
        AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
        BundleResource(
            key=f"{kind}/{identity}",
            kind=BundleResourceKind(kind),
            name="Connection",
            source_id=identity,
        ),
        with_content=with_content,
    )
    assert source.id == identity and not source.copyable
    assert source.definition is None
    assert "PRIVATE-" not in source.name


@pytest.mark.parametrize("kind", ["agent", "agent_version", "model_profile"])
async def test_nonfinite_stored_configuration_is_refused_without_exposing_values(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    identity, parent = uuid4(), uuid4()
    if kind == "model_profile":
        method = "ModelProfileService.profile_for_organization"
        fields = {
            "label": "Model",
            "provider": "openai",
            "model": "model",
            "secret_id": None,
            "base_url": None,
            "api": "responses",
            "region": None,
            "params": {"temperature": float("nan")},
            "fallback_profile_ids": [],
        }
    else:
        method = (
            "AgentRegistryService.get" if kind == "agent" else "AgentRegistryService.get_version"
        )
        fields = {
            "name": "Agent",
            "draft_spec" if kind == "agent" else "spec": {
                "name": "Agent",
                "model": {"params": {"temperature": float("nan")}},
            },
        }
    monkeypatch.setattr(
        f"app.services.portability.sources.{method}",
        AsyncMock(return_value=SimpleNamespace(id=identity, **fields)),
    )
    with pytest.raises(BadRequestError, match="cannot be represented") as error:
        await BundleSources(mock_db_session).read(
            AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
            BundleResource(
                key=f"{kind}/source",
                kind=BundleResourceKind(kind),
                name="Source",
                source_id=identity,
                source_parent_id=parent if kind == "agent_version" else None,
            ),
        )
    assert error.value.details is None or "nan" not in str(error.value.details).lower()


async def test_workflow_source_removes_only_run_data_and_unsafe_column_bindings(
    mock_db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.workflow import StoredWorkflowSettings
    from app.services.portability.workflows import WorkflowContent
    from app.workflows.contracts.io import Binding, FileRef, TableIORef
    from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph

    identity = uuid4()
    node = NodeInstance(
        id=uuid4(),
        definition_id="debug.echo",
        definition_version=1,
        config={"message": "Keep"},
        layout=NodePosition(x=0, y=0),
        pinned_output={"text": "Run data"},
    )
    graph = WorkflowGraph(
        entry_node_id=node.id,
        nodes=(node,),
        bindings=(
            Binding(
                target_node_id=node.id,
                target_field="a",
                source=FileRef(file_id=uuid4(), content_type="text/plain", byte_size=1),
            ),
            Binding(
                target_node_id=node.id,
                target_field="b",
                source=TableIORef(table_id=uuid4(), column_ids=(uuid4(),), schema_version=1),
            ),
        ),
    )
    monkeypatch.setattr(
        "app.services.portability.sources.WorkflowRegistryService.get",
        AsyncMock(
            return_value=SimpleNamespace(
                id=identity,
                name="Workflow",
                description=None,
                tags=[],
                settings=StoredWorkflowSettings(error_workflow_run_as=uuid4()),
                draft_graph=graph,
            )
        ),
    )
    resource = BundleResource(
        key=f"workflow/{identity}",
        kind=BundleResourceKind.WORKFLOW,
        name="Source",
        source_id=identity,
    )
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    source = await BundleSources(mock_db_session).read(ctx, resource)
    assert isinstance(source.content, WorkflowContent) and source.content.graph is not None
    assert source.content.graph.nodes[0].pinned_output is None
    assert source.content.graph.nodes[0].config == {"message": "Keep"}
    assert source.content.graph.bindings == ()
    assert len(source.content.omitted) == 2
    assert "error_workflow_run_as" not in source.content.settings.model_dump()
    assert (
        await BundleSources(mock_db_session).read(ctx, resource, with_content=False)
    ).content is None


async def test_a_reused_table_reports_its_current_schema_version(
    mock_db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = uuid4()
    monkeypatch.setattr(
        "app.services.portability.sources.VirtualTableService.describe_table",
        AsyncMock(return_value=SimpleNamespace(id=identity, name="Tasks", schema_version=7)),
    )
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    source = await BundleSources(mock_db_session).read(
        ctx,
        BundleResource(
            key=f"table/{identity}", kind=BundleResourceKind.TABLE, source_id=identity, name="Table"
        ),
    )
    assert source.version_number == 7 and not source.copyable and source.definition is None
