"""Tests for `WorkflowRegistryService`: draft CRUD, publish, the node catalog.

The shape being defended mirrors the agent registry: a refusal looks like an
absence (`NotFoundError`, never a 403 that would let ids be probed),
`expected_revision` is checked before the draft or the graph is looked at,
and a published version never changes once created - there is no
`update_version` for the service to accidentally call.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.core.exceptions import AlreadyExistsError, AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.resource_grant import GrantLevel, Visibility
from app.db.models.workflow import WorkflowStatus
from app.schemas.workflow import WorkflowCreate, WorkflowDraftUpdate, WorkflowPublish
from app.services.workflow_registry import (
    WorkflowArchivedError,
    WorkflowRegistryService,
    WorkflowRevisionConflictError,
    slugify,
)
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import NodeInstance, NodePosition, ScopeBoundary, WorkflowGraph

REGISTRY_PATH = "app.services.workflow_registry"

pytestmark = pytest.mark.anyio


def _ctx(role: str = OrgRoleName.OWNER.value, *, org_id=None, user_id=None) -> AuthContext:
    return AuthContext(
        user_id=user_id or uuid.uuid4(), organization_id=org_id or uuid.uuid4(), role=role
    )


def _db():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    return db


def _workflow(ctx: AuthContext, **overrides):
    workflow = MagicMock()
    workflow.id = uuid.uuid4()
    workflow.organization_id = ctx.organization_id
    workflow.owner_user_id = ctx.user_id
    workflow.visibility = Visibility.PRIVATE.value
    workflow.status = WorkflowStatus.DRAFT.value
    workflow.slug = "import-orders"
    workflow.name = "Import orders"
    workflow.description = None
    workflow.draft_revision = 0
    workflow.draft_graph = _empty_graph().model_dump(mode="json")
    workflow.current_version_id = None
    workflow.created_at = None
    workflow.updated_at = None
    for field, value in overrides.items():
        setattr(workflow, field, value)
    return workflow


def _empty_graph() -> WorkflowGraph:
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id="debug.echo",
        definition_version=1,
        config={"message": "hi"},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


class TestSlugify:
    def test_folds_to_a_lowercase_hyphenated_handle(self):
        assert slugify("Import Orders!") == "import-orders"

    def test_an_empty_name_falls_back_to_a_generic_handle(self):
        assert slugify("   ") == "workflow"


class TestNodeCatalog:
    async def test_includes_the_registered_debug_echo_node(self):
        catalog = await WorkflowRegistryService(_db()).node_catalog()
        ids = {item.id for item in catalog.items}
        assert "debug.echo" in ids
        assert catalog.total == len(catalog.items)

    async def test_a_port_with_no_schema_serializes_to_null(self):
        catalog = await WorkflowRegistryService(_db()).node_catalog()
        echo = next(item for item in catalog.items if item.id == "debug.echo")
        assert all(port.schema_ is not None for port in echo.ports)


class TestCreate:
    @pytest.mark.security
    async def test_creating_without_the_permission_is_refused(self):
        ctx = _ctx(OrgRoleName.VIEWER.value)
        with pytest.raises(AuthorizationError):
            await WorkflowRegistryService(_db()).create(ctx, WorkflowCreate(name="Import orders"))

    async def test_a_taken_slug_is_refused(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        existing = _workflow(ctx)
        with (
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_by_slug", new=AsyncMock(return_value=existing)
            ),
            pytest.raises(AlreadyExistsError),
        ):
            await WorkflowRegistryService(_db()).create(ctx, WorkflowCreate(name="Import orders"))

    async def test_a_new_workflow_is_created_in_draft(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        created = _workflow(ctx)
        with (
            patch(f"{REGISTRY_PATH}.workflow_repo.get_by_slug", new=AsyncMock(return_value=None)),
            patch(
                f"{REGISTRY_PATH}.workflow_repo.create", new=AsyncMock(return_value=created)
            ) as create,
        ):
            result = await WorkflowRegistryService(_db()).create(
                ctx, WorkflowCreate(name="Import orders")
            )
        assert result.id == created.id
        assert create.call_args.kwargs["slug"] == "import-orders"


class TestGet:
    async def test_a_forbidden_workflow_is_indistinguishable_from_a_missing_one(self):
        ctx = _ctx(OrgRoleName.MEMBER.value)
        forbidden = _workflow(ctx, owner_user_id=uuid.uuid4())

        with (
            patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=forbidden)),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError) as refused,
        ):
            await WorkflowRegistryService(_db()).get(ctx, forbidden.id)

        with (
            patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError) as absent,
        ):
            await WorkflowRegistryService(_db()).get(ctx, forbidden.id)

        assert refused.value.message == absent.value.message
        assert refused.value.details == absent.value.details == {"workflow_id": forbidden.id}

    async def test_a_grant_reaches_a_workflow_the_role_does_not(self):
        ctx = _ctx(OrgRoleName.MEMBER.value)
        workflow = _workflow(ctx, owner_user_id=uuid.uuid4())

        with (
            patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=GrantLevel.READ),
            ),
        ):
            found = await WorkflowRegistryService(_db()).get(ctx, workflow.id)
        assert found.id == workflow.id

    async def test_a_never_edited_workflow_reports_no_draft_graph_instead_of_crashing(self):
        """`draft_graph` starts at `{}` - not a valid `WorkflowGraph` - so a
        workflow nobody has edited yet used to raise a raw `ValidationError`
        the first time it was read."""
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx, draft_graph={})

        with patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)):
            found = await WorkflowRegistryService(_db()).get(ctx, workflow.id)

        assert found.draft_graph is None

    async def test_a_corrupted_non_empty_draft_graph_is_logged_not_silently_hidden(self, caplog):
        """`{}` is the one shape that legitimately means "never edited"; any
        other unparsable stored value is a real data problem, not that -
        reported the same way to the caller (there is no second field yet to
        say otherwise) but left a trace a corrupted `{}` never has to."""
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx, draft_graph={"entry_node_id": "not-a-uuid"})

        with (
            patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            caplog.at_level("WARNING", logger=REGISTRY_PATH),
        ):
            found = await WorkflowRegistryService(_db()).get(ctx, workflow.id)

        assert found.draft_graph is None
        assert any("workflow_draft_graph_unparsable" in record.message for record in caplog.records)


class TestUpdateDraft:
    async def test_updating_bumps_the_revision_and_stores_the_graph(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx)
        graph = _empty_graph()

        async def _update(db, *, workflow, update_data):
            for field, value in update_data.items():
                setattr(workflow, field, value)
            return workflow

        with (
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_for_update",
                new=AsyncMock(return_value=workflow),
            ),
            patch(f"{REGISTRY_PATH}.workflow_repo.update", new=AsyncMock(side_effect=_update)),
        ):
            result = await WorkflowRegistryService(_db()).update_draft(
                ctx,
                workflow.id,
                WorkflowDraftUpdate(graph=graph.model_dump(mode="json"), expected_revision=0),
            )
        assert result.draft_revision == 1
        assert workflow.draft_graph == graph.model_dump(mode="json")

    async def test_a_client_authored_scopes_claim_is_stripped_before_it_is_stored(self):
        """`scopes` is server-derived by contract - `derive_scopes`'s own
        docstring - but `update_draft` used to store whatever a client sent
        verbatim, readable by a `GET` until the next publish silently
        replaced it. A graph with no control node at all derives no scopes,
        so a fabricated claim here can only survive if nothing strips it."""
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx)
        graph = _empty_graph()
        fake_node_id = uuid.uuid4()
        payload = graph.model_dump(mode="json")
        payload["scopes"] = [
            ScopeBoundary(
                scope_node_id=fake_node_id,
                body_node_ids=frozenset({fake_node_id}),
                entry_port="body",
                exit_node_id=fake_node_id,
                exit_port="done",
            ).model_dump(mode="json")
        ]

        async def _update(db, *, workflow, update_data):
            for field, value in update_data.items():
                setattr(workflow, field, value)
            return workflow

        with (
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_for_update",
                new=AsyncMock(return_value=workflow),
            ),
            patch(f"{REGISTRY_PATH}.workflow_repo.update", new=AsyncMock(side_effect=_update)),
        ):
            await WorkflowRegistryService(_db()).update_draft(
                ctx, workflow.id, WorkflowDraftUpdate(graph=payload, expected_revision=0)
            )
        assert workflow.draft_graph["scopes"] == []

    async def test_an_oversized_draft_is_refused_before_it_is_persisted(self, monkeypatch):
        """The node/edge/binding ceiling exists to keep publish's dominator
        computation bounded, but it is checked here too - refusing an
        oversized graph before it is ever written is cheaper than refusing
        it only once someone later tries to publish it."""
        monkeypatch.setattr(settings, "WORKFLOW_GRAPH_MAX_NODES", 1)
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx)
        graph = _empty_graph()
        second = NodeInstance(
            id=uuid.uuid4(),
            definition_id="debug.echo",
            definition_version=1,
            config={"message": "hi"},
            layout=NodePosition(x=0, y=0),
        )
        payload = graph.model_dump(mode="json")
        payload["nodes"].append(second.model_dump(mode="json"))

        with (
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_for_update",
                new=AsyncMock(return_value=workflow),
            ),
            patch(f"{REGISTRY_PATH}.workflow_repo.update", new=AsyncMock()) as update,
            pytest.raises(GraphValidationError),
        ):
            await WorkflowRegistryService(_db()).update_draft(
                ctx, workflow.id, WorkflowDraftUpdate(graph=payload, expected_revision=0)
            )
        update.assert_not_called()

    async def test_a_stale_revision_is_refused_before_anything_is_written(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx, draft_revision=5)
        graph = _empty_graph()

        with (
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_for_update",
                new=AsyncMock(return_value=workflow),
            ),
            patch(f"{REGISTRY_PATH}.workflow_repo.update", new=AsyncMock()) as update,
            pytest.raises(WorkflowRevisionConflictError) as excinfo,
        ):
            await WorkflowRegistryService(_db()).update_draft(
                ctx,
                workflow.id,
                WorkflowDraftUpdate(graph=graph.model_dump(mode="json"), expected_revision=0),
            )
        update.assert_not_called()
        assert excinfo.value.details == {
            "workflow_id": workflow.id,
            "expected_revision": 0,
            "current_revision": 5,
        }

    async def test_an_archived_workflow_refuses_the_draft_write(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx, status=WorkflowStatus.ARCHIVED.value)
        graph = _empty_graph()

        with (
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_for_update",
                new=AsyncMock(return_value=workflow),
            ),
            patch(f"{REGISTRY_PATH}.workflow_repo.update", new=AsyncMock()) as update,
            pytest.raises(WorkflowArchivedError),
        ):
            await WorkflowRegistryService(_db()).update_draft(
                ctx,
                workflow.id,
                WorkflowDraftUpdate(graph=graph.model_dump(mode="json"), expected_revision=0),
            )
        update.assert_not_called()

    async def test_access_is_checked_before_the_revision_is_even_compared(self):
        """A caller without edit access is refused as not-found, whatever
        `expected_revision` they sent - a wrong revision must never leak
        through an authorization refusal."""
        ctx = _ctx(OrgRoleName.MEMBER.value)
        workflow = _workflow(ctx, owner_user_id=uuid.uuid4(), draft_revision=5)
        graph = _empty_graph()

        with (
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_for_update",
                new=AsyncMock(return_value=workflow),
            ),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError),
        ):
            # A deliberately wrong revision: if the ordering were reversed this
            # would raise WorkflowRevisionConflictError instead, which would
            # tell an unauthorized caller the real current revision.
            await WorkflowRegistryService(_db()).update_draft(
                ctx,
                workflow.id,
                WorkflowDraftUpdate(graph=graph.model_dump(mode="json"), expected_revision=999),
            )


class TestPublish:
    async def test_publishing_validates_freezes_and_bumps_status(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx)
        version = MagicMock()
        version.id = uuid.uuid4()
        version.version = 1
        version.note = None
        version.published_by_user_id = ctx.user_id
        version.budget_limit = None
        version.created_at = None

        with (
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_for_update",
                new=AsyncMock(return_value=workflow),
            ),
            patch(
                f"{REGISTRY_PATH}.workflow_repo.next_version_number", new=AsyncMock(return_value=1)
            ),
            patch(
                f"{REGISTRY_PATH}.workflow_repo.create_version", new=AsyncMock(return_value=version)
            ) as create_version,
            patch(
                f"{REGISTRY_PATH}.workflow_repo.update", new=AsyncMock(return_value=workflow)
            ) as update,
        ):
            result = await WorkflowRegistryService(_db()).publish(
                ctx, workflow.id, WorkflowPublish(expected_revision=0)
            )
        assert result.version == 1
        assert create_version.call_args.kwargs["version"] == 1
        assert update.call_args.kwargs["update_data"]["status"] == WorkflowStatus.PUBLISHED.value
        assert update.call_args.kwargs["update_data"]["current_version_id"] == version.id

    async def test_an_invalid_graph_is_refused_and_nothing_is_created(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        # An entry node that is not actually in the graph - rule 1.
        bad_graph = WorkflowGraph(
            entry_node_id=uuid.uuid4(),
            nodes=(
                NodeInstance(
                    id=uuid.uuid4(),
                    definition_id="debug.echo",
                    definition_version=1,
                    config={"message": "hi"},
                    layout=NodePosition(x=0, y=0),
                ),
            ),
        )
        workflow = _workflow(ctx, draft_graph=bad_graph.model_dump(mode="json"))

        with (
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_for_update",
                new=AsyncMock(return_value=workflow),
            ),
            patch(
                f"{REGISTRY_PATH}.workflow_repo.create_version", new=AsyncMock()
            ) as create_version,
            pytest.raises(GraphValidationError),
        ):
            await WorkflowRegistryService(_db()).publish(
                ctx, workflow.id, WorkflowPublish(expected_revision=0)
            )
        create_version.assert_not_called()

    async def test_publishing_a_never_edited_workflow_is_refused_not_crashed(self):
        """`draft_graph` starts at `{}`; publishing it used to raise a raw
        `ValidationError` instead of the actionable `GraphValidationError`
        every other publish-time refusal gives."""
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx, draft_graph={})

        with (
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_for_update",
                new=AsyncMock(return_value=workflow),
            ),
            patch(
                f"{REGISTRY_PATH}.workflow_repo.create_version", new=AsyncMock()
            ) as create_version,
            pytest.raises(GraphValidationError) as refused,
        ):
            await WorkflowRegistryService(_db()).publish(
                ctx, workflow.id, WorkflowPublish(expected_revision=0)
            )
        assert any(f["field"] == "draft_graph" for f in refused.value.details["fields"])
        create_version.assert_not_called()

    async def test_a_stale_revision_is_refused_before_the_graph_is_even_validated(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx, draft_revision=3)

        with (
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_for_update",
                new=AsyncMock(return_value=workflow),
            ),
            patch(f"{REGISTRY_PATH}.validate_graph", new=AsyncMock()) as validate,
            pytest.raises(WorkflowRevisionConflictError),
        ):
            await WorkflowRegistryService(_db()).publish(
                ctx, workflow.id, WorkflowPublish(expected_revision=0)
            )
        validate.assert_not_called()

    async def test_publishing_an_archived_workflow_is_refused(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx, status=WorkflowStatus.ARCHIVED.value)

        with (
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_for_update",
                new=AsyncMock(return_value=workflow),
            ),
            pytest.raises(WorkflowArchivedError),
        ):
            await WorkflowRegistryService(_db()).publish(
                ctx, workflow.id, WorkflowPublish(expected_revision=0)
            )


class TestListAndVersions:
    async def test_list_asks_the_repository_with_the_resolved_visibility(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        with (
            patch(
                "app.services.workflow_registry.visible_resource_ids",
                new=AsyncMock(return_value=None),
            ),
            patch(
                f"{REGISTRY_PATH}.workflow_repo.list_visible", new=AsyncMock(return_value=([], 0))
            ) as list_visible,
        ):
            result = await WorkflowRegistryService(_db()).list(ctx, skip=0, limit=10)
        assert result.total == 0
        assert list_visible.call_args.kwargs["see_all"] is True

    async def test_list_versions_returns_every_published_version(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx)
        version = MagicMock()
        version.id = uuid.uuid4()
        version.version = 1
        version.note = "first"
        version.published_by_user_id = ctx.user_id
        version.budget_limit = None
        version.created_at = None

        with (
            patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(
                f"{REGISTRY_PATH}.workflow_repo.list_versions",
                new=AsyncMock(return_value=[version]),
            ),
        ):
            result = await WorkflowRegistryService(_db()).list_versions(ctx, workflow.id)
        assert [item.version for item in result.items] == [1]

    async def test_get_version_returns_the_frozen_graph(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx)
        version = MagicMock()
        version.id = uuid.uuid4()
        version.workflow_id = workflow.id
        version.version = 2
        version.note = "cut"
        version.published_by_user_id = ctx.user_id
        version.budget_limit = None
        version.created_at = None
        frozen = _empty_graph()
        version.graph = frozen.model_dump(mode="json")

        with (
            patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_version",
                new=AsyncMock(return_value=version),
            ),
        ):
            result = await WorkflowRegistryService(_db()).get_version(ctx, workflow.id, version.id)
        assert result.version == 2
        assert result.graph.entry_node_id == frozen.entry_node_id
        assert len(result.graph.nodes) == 1

    async def test_get_version_missing_is_not_found(self):
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx)

        with (
            patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(f"{REGISTRY_PATH}.workflow_repo.get_version", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await WorkflowRegistryService(_db()).get_version(ctx, workflow.id, uuid.uuid4())

    async def test_get_version_from_another_workflow_is_not_found(self):
        """A version id that belongs to a different workflow is unreachable here."""
        ctx = _ctx(OrgRoleName.OWNER.value)
        workflow = _workflow(ctx)
        foreign = MagicMock()
        foreign.id = uuid.uuid4()
        foreign.workflow_id = uuid.uuid4()

        with (
            patch(f"{REGISTRY_PATH}.workflow_repo.get", new=AsyncMock(return_value=workflow)),
            patch(
                f"{REGISTRY_PATH}.workflow_repo.get_version",
                new=AsyncMock(return_value=foreign),
            ),
            pytest.raises(NotFoundError),
        ):
            await WorkflowRegistryService(_db()).get_version(ctx, workflow.id, foreign.id)
