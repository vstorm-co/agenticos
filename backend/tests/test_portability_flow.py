"""Reviewed imports preserve bindings, retry safely and never edit reused resources."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec, OrgMcpServerRef
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.solution_installation import SolutionInstallation
from app.schemas.resource_bundle import (
    BundleContentLayer,
    BundleImportChoice,
    BundleImportCreate,
    BundleResource,
    BundleResourceKind,
    ResourceBundle,
)
from app.services.portability.content import ContextContent, McpContent
from app.services.portability.facade import PortabilityService
from app.services.portability.snapshots import agent_snapshot
from app.services.portability.sources import SourceDefinition

pytestmark = pytest.mark.anyio


def actor(role: str = "owner") -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=role)


def request_for(bundle: ResourceBundle) -> BundleImportCreate:
    return BundleImportCreate(
        operation_id=uuid4(),
        bundle=bundle,
        choices={
            item.key: BundleImportChoice(action="create" if item.definition is not None else "skip")
            for item in bundle.resources
        },
    )


def receipts(monkeypatch: pytest.MonkeyPatch) -> tuple[AsyncMock, AsyncMock]:
    get = AsyncMock(return_value=None)
    save = AsyncMock()
    monkeypatch.setattr("app.services.portability.facade.receipts.lock", AsyncMock())
    monkeypatch.setattr("app.services.portability.facade.receipts.get", get)
    monkeypatch.setattr("app.services.portability.facade.receipts.create", save)
    return get, save


async def test_export_enriches_only_accessible_dependencies_and_discovers_nested_references(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = actor()
    identity, context_id, mcp_id, hidden_id = [uuid4() for _ in range(4)]
    spec = AgentSpec(
        name="Researcher",
        instructions="Keep this exact text",
        context_ids=[context_id, hidden_id],
        mcp_servers=[OrgMcpServerRef(connection_id=mcp_id, allowed_tools=["read"], approval="all")],
    )
    monkeypatch.setattr(
        "app.services.portability.facade.AgentRegistryService.get",
        AsyncMock(
            return_value=Agent(id=identity, name=spec.name, draft_spec=spec.model_dump(mode="json"))
        ),
    )
    service = PortabilityService(mock_db_session)

    async def read(
        auth: AuthContext, resource: BundleResource, *, with_content: bool = True
    ) -> SourceDefinition:
        assert auth == ctx
        if resource.kind == BundleResourceKind.AGENT:
            return SourceDefinition(identity, spec.name, spec)
        if resource.source_id == hidden_id:
            raise NotFoundError(message="Not found")
        if resource.source_id == context_id:
            return SourceDefinition(
                context_id, "Policy", ContextContent(name="Policy", content="exact policy")
            )
        return SourceDefinition(
            mcp_id,
            "Notion",
            McpContent(name="notion", url="https://example.org/mcp", allowed_tools=["read"]),
        )

    monkeypatch.setattr(service.sources, "read", read)
    preview = await service.export_agent(ctx, identity)
    by_key = {item.key: item for item in preview.bundle.resources}
    assert by_key[f"context/{context_id}"].definition["content"] == "exact policy"
    assert by_key[f"context/{hidden_id}"].definition is None
    assert by_key[f"context/{hidden_id}"].name == "context"
    assert not next(
        option for option in preview.options if option.key == f"context/{hidden_id}"
    ).available


async def test_import_rebinds_mcp_policy_and_removes_explicitly_skipped_context(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    get, save = receipts(monkeypatch)
    old_mcp, new_mcp, context = uuid4(), uuid4(), uuid4()
    spec = AgentSpec(
        name="Researcher",
        instructions=f"Do not rewrite {old_mcp}",
        context_ids=[context],
        mcp_servers=[
            OrgMcpServerRef(
                connection_id=old_mcp,
                allowed_tools=["read"],
                approval="all",
                tool_approval={"read": "required"},
            )
        ],
    )
    bundle = agent_snapshot(spec)
    request = request_for(bundle)
    request.choices[bundle.roots[0]] = BundleImportChoice(action="create", name="Researcher copy")
    request.choices[f"mcp_connection/{old_mcp}"] = BundleImportChoice(
        action="reuse", destination_id=new_mcp
    )
    service = PortabilityService(mock_db_session)
    monkeypatch.setattr(
        service.sources, "read", AsyncMock(return_value=SourceDefinition(new_mcp, "Mapped"))
    )
    created_id = uuid4()
    create = AsyncMock(return_value=created_id)
    monkeypatch.setattr(service, "_create", create)
    result = await service.import_bundle(actor(), request)
    mapped = AgentSpec.model_validate(create.await_args.args[2])
    assert mapped.name == "Researcher copy"
    assert mapped.instructions == spec.instructions
    assert mapped.context_ids == []
    assert mapped.mcp_servers[0].connection_id == new_mcp
    assert mapped.mcp_servers[0].approval == "all"
    assert mapped.mcp_servers[0].tool_approval == {"read": "required"}
    assert result.created == {bundle.roots[0]: created_id}
    assert result.reused == {f"mcp_connection/{old_mcp}": new_mcp}
    assert f"context/{context}" in result.skipped
    stored = save.await_args.kwargs
    get.return_value = SolutionInstallation(
        manifest_hash=stored["manifest_hash"], resources=stored["resources"]
    )
    assert await service.import_bundle(actor(), request) == result
    assert create.await_count == 1
    changed = request.model_copy(
        update={
            "choices": {
                **request.choices,
                bundle.roots[0]: BundleImportChoice(action="create", name="Different"),
            }
        }
    )
    with pytest.raises(ConflictError, match="different reviewed"):
        await service.import_bundle(actor(), changed)


@pytest.mark.parametrize("mode", ["missing-choice", "skip-root", "viewer"])
async def test_incomplete_or_unauthorized_import_never_creates_resources(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    receipts(monkeypatch)
    request = request_for(agent_snapshot(AgentSpec(name="Agent")))
    if mode == "missing-choice":
        request.choices.clear()
    elif mode == "skip-root":
        request.choices[request.bundle.roots[0]] = BundleImportChoice(action="skip")
    service = PortabilityService(mock_db_session)
    create = AsyncMock()
    monkeypatch.setattr(service, "_create", create)
    with pytest.raises((BadRequestError, AuthorizationError)):
        await service.import_bundle(actor("viewer" if mode == "viewer" else "owner"), request)
    create.assert_not_awaited()


async def test_unreachable_same_id_is_not_reused_and_no_names_leak(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = agent_snapshot(AgentSpec(name="Agent", context_ids=[uuid4()]))
    service = PortabilityService(mock_db_session)
    monkeypatch.setattr(
        service.sources, "read", AsyncMock(side_effect=NotFoundError(message="Not found"))
    )
    preview = await service.preview_import(actor(), bundle)
    assert all(option.reusable_id is None for option in preview.options)
    assert preview.bundle == bundle


async def test_reuse_reads_the_destination_under_current_tenant_authority(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipts(monkeypatch)
    ctx = actor()
    root = agent_snapshot(AgentSpec(name="Agent")).resources[0]
    destination = uuid4()
    bundle = ResourceBundle(roots=(root.key,), resources=(root,))
    request = BundleImportCreate(
        operation_id=uuid4(),
        bundle=bundle,
        choices={root.key: BundleImportChoice(action="reuse", destination_id=destination)},
    )
    service = PortabilityService(mock_db_session)
    read = AsyncMock(side_effect=NotFoundError(message="Not found"))
    monkeypatch.setattr(service.sources, "read", read)
    with pytest.raises(NotFoundError):
        await service.import_bundle(ctx, request)
    assert read.await_args.args[0] == ctx
    assert read.await_args.args[1].source_id == destination


async def test_unknown_content_cannot_be_created_as_a_different_kind(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipts(monkeypatch)
    resource = BundleResource(key="secret/missing", kind=BundleResourceKind.SECRET, name="Secret")
    bundle = ResourceBundle(roots=(resource.key,), resources=(resource,))
    request = BundleImportCreate(
        operation_id=uuid4(),
        bundle=bundle,
        choices={resource.key: BundleImportChoice(action="create")},
    )
    with pytest.raises(AuthorizationError):
        await PortabilityService(mock_db_session).import_bundle(actor(), request)


async def test_inline_preview_and_download_use_the_same_validated_document(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.schemas.resource_bundle import BundleDownloadCreate
    from app.services.portability.documents import parse_document

    service = PortabilityService(mock_db_session)
    preview = await service.preview_document(actor(), "name: Agent")
    assert preview.options[0].can_create
    export = AsyncMock(return_value=preview)
    monkeypatch.setattr(service, "export_agent", export)
    data = await service.download_agent(
        actor(),
        uuid4(),
        BundleDownloadCreate(
            resources={preview.bundle.roots[0]: frozenset({BundleContentLayer.DEFINITION})}
        ),
    )
    assert parse_document(data.decode()) == preview.bundle


async def test_creation_cycles_are_refused_without_writing_partial_resources(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.schemas.resource_bundle import BundleReference
    from app.services.portability.content import ModelContent

    receipts(monkeypatch)
    first, second = uuid4(), uuid4()
    bundle = agent_snapshot(AgentSpec(name="Agent", model_profile_id=first))
    models = []
    for identity, target in [(first, second), (second, first)]:
        models.append(
            BundleResource(
                key=f"model_profile/{identity}",
                kind=BundleResourceKind.MODEL_PROFILE,
                source_id=identity,
                name="Model",
                definition=ModelContent(
                    label="Model", provider="openai", model="gpt-4.1", fallback_profile_ids=[target]
                ).model_dump(mode="json"),
                references=(
                    BundleReference(
                        path=("fallback_profile_ids", 0), target=f"model_profile/{target}"
                    ),
                ),
                included=frozenset({BundleContentLayer.DEFINITION}),
            )
        )
    bundle = bundle.model_copy(update={"resources": (bundle.resources[0], *models)})
    service = PortabilityService(mock_db_session)
    create = AsyncMock()
    monkeypatch.setattr(service, "_create", create)
    with pytest.raises(BadRequestError, match="cycle"):
        await service.import_bundle(actor(), request_for(bundle))
    create.assert_not_awaited()


async def test_version_reuse_resolves_number_against_the_mapped_owner(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from app.agents.spec import SkillBindingSpec

    receipts(monkeypatch)
    skill, destination, version = uuid4(), uuid4(), uuid4()
    bundle = agent_snapshot(
        AgentSpec(
            name="Agent",
            skill_ids=[skill],
            skill_bindings=[SkillBindingSpec(skill_id=skill, version=3)],
        )
    )
    request = request_for(bundle)
    request.choices[f"skill/{skill}"] = BundleImportChoice(
        action="reuse", destination_id=destination
    )
    request.choices[f"skill_version/{skill}-v3"] = BundleImportChoice(
        action="reuse", destination_id=version
    )
    service = PortabilityService(mock_db_session)
    monkeypatch.setattr(
        service.sources, "read", AsyncMock(return_value=SourceDefinition(destination, "Skill"))
    )
    read = AsyncMock(return_value=SimpleNamespace(id=version, number=8, fork_id=None))
    monkeypatch.setattr(
        "app.services.portability.facade.SkillVersionService.export_version_by_id", read
    )
    create = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(service, "_create", create)
    ctx = actor()
    await service.import_bundle(ctx, request)
    read.assert_awaited_once_with(ctx, destination, version)
    assert create.await_args.args[2]["skill_bindings"][0]["version"] == 8
    read.return_value.fork_id = uuid4()
    with pytest.raises(BadRequestError, match="main skill pin"):
        await service.import_bundle(ctx, request.model_copy(update={"operation_id": uuid4()}))

    request.choices[f"skill/{skill}"] = BundleImportChoice(action="skip")
    with pytest.raises(BadRequestError, match="accessible destination owner"):
        await service.import_bundle(ctx, request.model_copy(update={"operation_id": uuid4()}))


async def test_nested_agent_references_are_discovered_and_export_size_is_bounded(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.spec import SkillBindingSpec, SubagentRef
    from app.services.portability.content import SkillContent, SkillSnapshotContent

    root_id, child_id, version_id, skill_id, skill_version_id = [uuid4() for _ in range(5)]
    root = AgentSpec(
        name="Root", subagents=[SubagentRef(agent_id=child_id, agent_version_id=version_id)]
    )
    child = AgentSpec(
        name="Child",
        skill_ids=[skill_id],
        skill_bindings=[SkillBindingSpec(skill_id=skill_id, version=3)],
    )
    monkeypatch.setattr(
        "app.services.portability.facade.AgentRegistryService.get",
        AsyncMock(
            return_value=Agent(id=root_id, name=root.name, draft_spec=root.model_dump(mode="json"))
        ),
    )
    service = PortabilityService(mock_db_session)

    async def read(
        ctx: AuthContext, resource: BundleResource, *, with_content: bool = True
    ) -> SourceDefinition:
        if resource.source_id == root_id:
            return SourceDefinition(root_id, root.name, root)
        if resource.kind in (BundleResourceKind.AGENT, BundleResourceKind.AGENT_VERSION):
            return SourceDefinition(resource.source_id, child.name, child)
        if resource.kind == BundleResourceKind.SKILL:
            return SourceDefinition(
                skill_id,
                "policy",
                SkillContent(name="policy", description="Policy", content="Latest"),
            )
        return SourceDefinition(
            skill_version_id,
            "policy",
            SkillSnapshotContent(
                name="policy", description="Policy", content="Pinned", skill_id=skill_id, number=3
            ),
            parent_id=skill_id,
            version_number=3,
        )

    monkeypatch.setattr(service.sources, "read", read)
    preview = await service.export_agent(actor(), root_id)
    assert f"skill_version/{skill_id}-v3" in {item.key for item in preview.bundle.resources}
    monkeypatch.setattr("app.services.portability.facade.MAX_EXPORT_RESOURCES", 2)
    with pytest.raises(BadRequestError, match="500 linked"):
        await service.export_agent(actor(), root_id)


async def test_copying_a_snapshot_never_changes_a_reused_skill(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.spec import SkillBindingSpec
    from app.schemas.resource_bundle import BundleReference
    from app.services.portability.content import SkillSnapshotContent

    receipts(monkeypatch)
    skill, destination = uuid4(), uuid4()
    bundle = agent_snapshot(
        AgentSpec(
            name="Agent",
            skill_ids=[skill],
            skill_bindings=[SkillBindingSpec(skill_id=skill, version=3)],
        )
    )
    version = next(
        item for item in bundle.resources if item.kind == BundleResourceKind.SKILL_VERSION
    )
    version = version.model_copy(
        update={
            "definition": SkillSnapshotContent(
                name="policy", description="Policy", content="Pinned", skill_id=skill, number=3
            ).model_dump(mode="json"),
            "references": (BundleReference(path=("skill_id",), target=f"skill/{skill}"),),
            "included": frozenset({BundleContentLayer.DEFINITION}),
        }
    )
    bundle = bundle.model_copy(
        update={
            "resources": tuple(
                version if item.key == version.key else item for item in bundle.resources
            )
        }
    )
    request = request_for(bundle)
    request.choices[f"skill/{skill}"] = BundleImportChoice(
        action="reuse", destination_id=destination
    )
    service = PortabilityService(mock_db_session)
    monkeypatch.setattr(
        service.sources, "read", AsyncMock(return_value=SourceDefinition(destination, "Existing"))
    )
    write = AsyncMock()
    monkeypatch.setattr(service, "_write_skill_content", write)
    with pytest.raises(BadRequestError, match="existing skills are never changed"):
        await service.import_bundle(actor(), request)
    write.assert_not_awaited()


async def test_inline_import_does_not_discard_declared_binary_assets(
    mock_db_session: AsyncMock,
) -> None:
    from app.schemas.resource_bundle import BundleAsset

    bundle = agent_snapshot(AgentSpec(name="Agent"))
    root = bundle.resources[0].model_copy(
        update={
            "included": frozenset({BundleContentLayer.DEFINITION, BundleContentLayer.PROJECT_FILES})
        }
    )
    asset = BundleAsset(
        resource=root.key,
        layer=BundleContentLayer.PROJECT_FILES,
        name="data.txt",
        sha256="0" * 64,
        size_bytes=0,
        media_type="text/plain",
    )
    bundle = bundle.model_copy(update={"resources": (root,), "assets": (asset,)})
    with pytest.raises(BadRequestError, match="binary assets"):
        await PortabilityService(mock_db_session).import_bundle(actor(), request_for(bundle))
    mock_db_session.execute.assert_not_awaited()


async def test_renamed_model_copy_uses_the_selected_destination_key(
    mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.schemas.resource_bundle import BundleReference
    from app.services.portability.content import ModelContent

    receipts(monkeypatch)
    model, old_key, new_key, new_model, new_agent = [uuid4() for _ in range(5)]
    bundle = agent_snapshot(AgentSpec(name="Agent", model_profile_id=model))
    profile = bundle.resources[1].model_copy(
        update={
            "definition": ModelContent(
                label="Model",
                provider="openai",
                model="gpt-4.1",
                secret_id=old_key,
                params={"temperature": 0.2},
            ).model_dump(mode="json"),
            "references": (BundleReference(path=("secret_id",), target=f"secret/{old_key}"),),
            "included": frozenset({BundleContentLayer.DEFINITION}),
        }
    )
    secret = BundleResource(
        key=f"secret/{old_key}", kind=BundleResourceKind.SECRET, name="Key", source_id=old_key
    )
    bundle = bundle.model_copy(update={"resources": (bundle.resources[0], profile, secret)})
    request = request_for(bundle)
    request.choices[profile.key] = BundleImportChoice(action="create", name="Copied model")
    request.choices[secret.key] = BundleImportChoice(action="reuse", destination_id=new_key)
    service = PortabilityService(mock_db_session)
    monkeypatch.setattr(
        service.sources,
        "read",
        AsyncMock(return_value=SourceDefinition(new_key, "Destination key")),
    )
    create = AsyncMock(side_effect=[new_model, new_agent])
    monkeypatch.setattr(service, "_create", create)
    await service.import_bundle(actor(), request)
    mapped_model = create.await_args_list[0].args[2]
    assert mapped_model["label"] == "Copied model"
    assert mapped_model["secret_id"] == str(new_key)
    assert mapped_model["params"] == {"temperature": 0.2}
    assert create.await_args_list[1].args[2]["model_profile_id"] == str(new_model)
