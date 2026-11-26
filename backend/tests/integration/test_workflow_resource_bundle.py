"""Selected workflow imports write private drafts through the normal registry."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.schemas.resource_bundle import BundleImportChoice, BundleImportCreate, BundleResourceKind
from app.services.portability import PortabilityService
from app.services.workflow_registry import WorkflowRegistryService
from tests.integration.test_workflow_portable import _ctx, _graph, _workflow

pytestmark = pytest.mark.anyio


@pytest.mark.security
async def test_cross_tenant_workflow_copy_skips_secret_binding_and_remains_unpublished(
    db: AsyncSession,
) -> None:
    source, target = await _ctx(db), await _ctx(db)
    identity = await _workflow(db, source, _graph(str(uuid4())))
    service = PortabilityService(db)
    preview = await service.export_resource(source, BundleResourceKind.WORKFLOW, identity)
    assert len(preview.bundle.resources) == 2
    choices = {
        item.key: BundleImportChoice(action="create" if item.definition else "skip")
        for item in preview.bundle.resources
    }
    request = BundleImportCreate(operation_id=uuid4(), bundle=preview.bundle, choices=choices)
    receipt = await service.import_bundle(target, request)
    assert await service.import_bundle(target, request) == receipt
    root = preview.bundle.roots[0]
    copied = await WorkflowRegistryService(db).get(target, receipt.roots[root])
    assert copied.current_version_id is None and copied.visibility == "private"
    assert copied.settings.timezone == "Europe/Warsaw"
    assert copied.draft_graph is not None
    assert copied.draft_graph.nodes[1].config["auth"] == {"kind": "bearer"}
    assert receipt.omitted_bindings[root] == (("graph", "nodes", 1, "config", "auth", "secret_id"),)
    with pytest.raises(NotFoundError):
        await WorkflowRegistryService(db).get(source, copied.id)


@pytest.mark.security
async def test_workflow_dependency_cycles_require_explicit_reuse_or_skip(db: AsyncSession) -> None:
    from app.schemas.resource_bundle import (
        BundleContentLayer,
        BundleReference,
        BundleResource,
        ResourceBundle,
    )

    ctx = await _ctx(db)
    a, b = uuid4(), uuid4()
    resources = tuple(
        BundleResource(
            key=f"workflow/{identity}",
            kind=BundleResourceKind.WORKFLOW,
            source_id=identity,
            name="Cycle",
            definition={"name": "Cycle", "settings": {"error_workflow_id": str(other)}},
            included=frozenset({BundleContentLayer.DEFINITION}),
            references=(
                BundleReference(path=("settings", "error_workflow_id"), target=f"workflow/{other}"),
            ),
        )
        for identity, other in ((a, b), (b, a))
    )
    bundle = ResourceBundle(roots=(resources[0].key,), resources=resources)
    request = BundleImportCreate(
        operation_id=uuid4(),
        bundle=bundle,
        choices={item.key: BundleImportChoice(action="create") for item in resources},
    )
    with pytest.raises(BadRequestError, match="cycle"):
        await PortabilityService(db).import_bundle(ctx, request)


@pytest.mark.security
@pytest.mark.parametrize("tags", [[], ["reviewed"]])
async def test_an_empty_workflow_import_preserves_tags_in_an_unpublished_private_draft(
    db: AsyncSession, tags: list[str]
) -> None:
    from app.schemas.resource_bundle import (
        BundleContentLayer,
        BundleResource,
        ResourceBundle,
    )

    ctx = await _ctx(db)
    root = BundleResource(
        key="workflow/empty",
        kind=BundleResourceKind.WORKFLOW,
        name="Empty imported draft",
        definition={"name": "Empty imported draft", "tags": tags},
        included=frozenset({BundleContentLayer.DEFINITION}),
    )
    request = BundleImportCreate(
        operation_id=uuid4(),
        bundle=ResourceBundle(roots=(root.key,), resources=(root,)),
        choices={root.key: BundleImportChoice(action="create")},
    )

    receipt = await PortabilityService(db).import_workflow(ctx, request)
    copied = await WorkflowRegistryService(db).get(ctx, receipt.roots[root.key])
    assert copied.tags == tags
    assert copied.current_version_id is None and copied.visibility == "private"
    assert copied.draft_graph is None
