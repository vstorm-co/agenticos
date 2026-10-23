"""Starting a page's declared action as the person viewing it (#1976), on real rows.

What the viewer is offered is decided per viewer, from the version served to them; what
they start is checked again on the way in, so a page script that names another version,
another workflow or another person's run is told nothing.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import set_impersonator
from app.core.config import settings
from app.core.exceptions import AuthorizationError, NotFoundError, RateLimitError
from app.core.permissions import AuthContext
from app.core.security import verify_special_token
from app.db.models.artifact import Artifact
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStatus
from app.repositories import artifact_repo
from app.schemas.artifact import ActionRequest, ArtifactActionRunCreate
from app.services.artifact import ArtifactService
from app.services.file_storage import LocalFileStorage
from app.services.workflow_execution import WorkflowExecutionService
from app.services.workflow_execution.exceptions import WorkflowRunInputInvalidError
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from tests.integration.test_artifact_actions import _World, _world
from tests.integration.virtual_table_support import make_user

pytestmark = pytest.mark.anyio

SECRET_INPUT = "card-4111-secret"


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[LocalFileStorage]:
    local = LocalFileStorage(tmp_path)
    with (
        patch("app.services.artifact.get_file_storage", return_value=local),
        patch("app.services.file_storage.get_file_storage", return_value=local),
    ):
        yield local


@pytest.fixture(autouse=True)
def _no_dispatch() -> Iterator[None]:
    with patch.object(WorkflowExecutionService, "_trigger_dispatch"):
        yield


def _graph(fields: list[dict] | None = None) -> dict:
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id="trigger.manual",
        definition_version=1,
        config={"fields": fields or []},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,)).model_dump(mode="json")


async def _live(world: _World, name: str, *, fields: list[dict] | None = None) -> Workflow:
    """A workflow with a published version, started by hand."""
    workflow = await world.workflow(name)
    graph = _graph(fields)
    version = WorkflowVersion(
        id=uuid.uuid4(),
        workflow_id=workflow.id,
        organization_id=world.org.id,
        version=1,
        graph=graph,
    )
    world.db.add(version)
    await world.db.flush()
    workflow.current_version_id = version.id
    workflow.draft_graph = graph
    await world.db.flush()
    return workflow


async def _viewer(world: _World, role: str = "member") -> AuthContext:
    user = await make_user(world.db)
    world.db.add(OrganizationMember(organization_id=world.org.id, user_id=user.id, role=role))
    await world.db.flush()
    return AuthContext(user_id=user.id, organization_id=world.org.id, role=role)


async def _page(world: _World, *workflows: Workflow, labels: bool = True) -> uuid.UUID:
    """A page for everyone in the organization declaring `workflows`."""
    await world.bind(*workflows)
    published = await world.publish(
        actions=[
            ActionRequest(workflow=w.id, label=f"Do {w.name}" if labels else None)
            for w in workflows
        ]
    )
    artifact = await artifact_repo.get(
        world.db, published.artifact_id, organization_id=world.org.id
    )
    assert artifact is not None
    await artifact_repo.update(
        world.db, artifact=artifact, update_data={"visibility": Visibility.ORG.value}
    )
    return published.artifact_id


async def _served_id(db: AsyncSession, ctx: AuthContext, page_id: uuid.UUID) -> uuid.UUID:
    return (await ArtifactService(db).view(ctx, page_id, data=True)).version.id


def _claims(url: str) -> dict:
    """What the content address a view handed out says of its holder."""
    payload = verify_special_token(
        url.rsplit("/", 1)[1], "artifact_view", audience=("member", "public")
    )
    assert payload is not None
    return payload


class TestTheAddressCarriesTheRightToAsk:
    """`acts` is on the page viewer's own address and nowhere else: it is what lets the
    served script offer `run`, so no preview, card or shared link may carry it."""

    async def test_only_the_served_version_with_actions_for_a_member_acting_as_themselves(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        service = ArtifactService(db)
        older = await artifact_repo.latest_version(db, page_id)
        assert older is not None

        for viewer in (world.boss, await _viewer(world)):
            assert _claims((await service.view(viewer, page_id, data=True)).url)["acts"] is True
            # A card or a thumbnail asks for no data, and gets no right to ask.
            assert _claims((await service.view(viewer, page_id)).url)["acts"] is False

        await world.publish("<p>v2</p>", actions=[ActionRequest(workflow=refund.id)])
        past = await service.view(world.boss, page_id, version_id=older.id, data=True)
        assert _claims(past.url)["acts"] is False
        assert _claims((await service.view(world.boss, page_id, data=True)).url)["acts"] is True

        # The newest version declares nothing: there is nothing to ask for.
        await world.publish("<p>v3</p>", actions=[])
        bare = await service.view(world.boss, page_id, data=True)
        assert (_claims(bare.url)["acts"], bare.actions_enabled) == (False, False)

    async def test_public_and_embed_addresses_never_carry_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        service = ArtifactService(db)
        detail = await service.set_public_link(world.boss, page_id)
        assert detail.public_url is not None
        key = detail.public_url.rsplit("/", 1)[-1]

        public = await service.public_view(key)
        assert public.view is not None
        assert "acts" not in _claims(public.view.url)

        embed = await service.embed(key)
        framed = re.search(rb"[\w-]+\.[\w-]+\.[\w-]+(?=[\"'?#])", embed.document)
        assert framed is not None
        payload = verify_special_token(
            framed.group().decode(), "artifact_view", audience=("member", "public")
        )
        assert payload is not None
        assert payload["aud"] == "public"
        assert "acts" not in payload


class TestWhatTheViewerIsOffered:
    async def test_the_served_version_lists_its_runnable_actions_with_real_names(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(
            world, "Refund order", fields=[{"name": "order", "type": "text", "required": True}]
        )
        page_id = await _page(world, refund)
        vera = await _viewer(world)

        shown = await ArtifactService(db).view(vera, page_id, data=True)

        assert shown.actions_enabled is True
        assert [(a.workflow_id, a.name, a.label) for a in shown.actions] == [
            (refund.id, "Refund order", "Do Refund order")
        ]
        assert [(f.name, f.type, f.required) for f in shown.actions[0].fields] == [
            ("order", "text", True)
        ]

    async def test_a_workflow_whose_entry_declares_no_fields_asks_for_none(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        version = await db.get(WorkflowVersion, refund.current_version_id)
        assert version is not None
        version.graph = {}
        await db.flush()
        page_id = await _page(world, refund)

        shown = await ArtifactService(db).view(await _viewer(world), page_id, data=True)

        assert [(a.name, a.fields) for a in shown.actions] == [("Refund", [])]

    async def test_a_view_that_is_not_the_page_viewer_carries_none(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        service = ArtifactService(db)
        older = await artifact_repo.latest_version(db, page_id)
        assert older is not None

        card = await service.view(vera, page_id)

        assert (card.actions_enabled, card.actions) == (False, [])
        await world.publish("<p>v2</p>", actions=[ActionRequest(workflow=refund.id)])
        past = await service.view(await _viewer(world), page_id, version_id=older.id, data=True)
        assert (past.actions_enabled, past.actions) == (False, [])

    @pytest.mark.security
    async def test_an_impersonated_or_non_member_viewer_is_offered_none(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        stranger = AuthContext(
            user_id=(await make_user(db)).id, organization_id=world.org.id, role="member"
        )

        set_impersonator(uuid.uuid4())
        try:
            borrowed = await ArtifactService(db).view(vera, page_id, data=True)
        finally:
            set_impersonator(None)
        outsider = await ArtifactService(db).view(stranger, page_id, data=True)

        assert (borrowed.actions_enabled, borrowed.actions) == (False, [])
        assert (outsider.actions_enabled, outsider.actions) == (False, [])

    async def test_a_public_link_carries_none(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        detail = await ArtifactService(db).set_public_link(world.boss, page_id)
        assert detail.public_url is not None

        public = await ArtifactService(db).public_view(detail.public_url.rsplit("/", 1)[-1])

        assert (public.view.actions_enabled, public.view.actions) == (False, [])

    async def test_an_action_the_viewer_cannot_run_is_left_out_not_named(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        kept = await _live(world, "Kept")
        hidden = await _live(world, "Hidden")
        archived = await _live(world, "Archived")
        retriggered = await _live(world, "Retriggered")
        gone = await _live(world, "Gone")
        page_id = await _page(world, kept, hidden, archived, retriggered, gone)
        hidden.visibility = Visibility.PRIVATE.value
        archived.status = WorkflowStatus.ARCHIVED.value
        retriggered.live_trigger = "trigger.webhook"
        gone.current_version_id = None
        gone.live_trigger = None
        await db.flush()
        vera = await _viewer(world)

        shown = await ArtifactService(db).view(vera, page_id, data=True)

        assert [a.name for a in shown.actions] == ["Kept"]
        assert "Hidden" not in shown.model_dump_json()

    async def test_a_viewer_without_the_run_permission_is_offered_nothing(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        reader = await _viewer(world, role="viewer")

        shown = await ArtifactService(db).view(reader, page_id, data=True)

        assert shown.actions == []


class TestStarting:
    async def _start(
        self,
        db: AsyncSession,
        ctx: AuthContext,
        page_id: uuid.UUID,
        workflow: Workflow,
        *,
        version_id: uuid.UUID | None = None,
        run_input: dict | None = None,
    ):
        return await ArtifactService(db).start_action(
            ctx,
            page_id,
            version_id or await _served_id(db, ctx, page_id),
            workflow.id,
            ArtifactActionRunCreate(input=run_input or {}),
        )

    async def test_the_run_is_the_viewers_own_and_records_where_it_came_from(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund", fields=[{"name": "order", "type": "text"}])
        page_id = await _page(world, refund)
        vera = await _viewer(world)

        started = await self._start(db, vera, page_id, refund, run_input={"order": SECRET_INPUT})

        run = await db.get(WorkflowRun, started.run_id)
        assert run is not None
        assert (run.triggered_by, run.source_artifact_id, run.source_version_number) == (
            "app",
            page_id,
            1,
        )
        assert run.execution_principal_user_id == vera.user_id
        assert run.input == {"order": SECRET_INPUT}
        assert run.public_origin is False
        assert started.status == run.status

    async def test_the_audit_names_the_run_and_never_the_input(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund", fields=[{"name": "order", "type": "text"}])
        page_id = await _page(world, refund)
        vera = await _viewer(world)

        started = await self._start(db, vera, page_id, refund, run_input={"order": SECRET_INPUT})

        entry = (
            await db.execute(
                select(AppAdminAuditLog).where(AppAdminAuditLog.action == "artifact.action_started")
            )
        ).scalar_one()
        assert entry.actor_user_id == vera.user_id
        assert entry.details == {
            "artifact_id": str(page_id),
            "version": 1,
            "workflow_id": str(refund.id),
            "run_id": str(started.run_id),
        }
        assert SECRET_INPUT not in str(entry.details)

    @pytest.mark.security
    async def test_a_workflow_the_version_does_not_declare_is_not_found(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        other = await _live(world, "Other")
        page_id = await _page(world, refund)
        vera = await _viewer(world)

        with pytest.raises(NotFoundError):
            await self._start(db, vera, page_id, other)
        assert (await db.execute(select(WorkflowRun))).first() is None

    @pytest.mark.security
    async def test_a_declared_workflow_the_viewer_may_no_longer_run_is_not_found(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        served = await _served_id(db, vera, page_id)
        refund.live_trigger = "trigger.webhook"
        await db.flush()

        with pytest.raises(NotFoundError):
            await self._start(db, vera, page_id, refund, version_id=served)

    @pytest.mark.security
    async def test_an_older_version_is_refused_even_when_it_declares_the_workflow(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        first = await _served_id(db, vera, page_id)
        await world.publish("<p>v2</p>", actions=[ActionRequest(workflow=refund.id)])

        with pytest.raises(NotFoundError):
            await self._start(db, vera, page_id, refund, version_id=first)
        started = await self._start(db, vera, page_id, refund)
        run = await db.get(WorkflowRun, started.run_id)
        assert run is not None and run.source_version_number == 2

    @pytest.mark.security
    async def test_the_audience_cannot_start_from_a_version_waiting_for_consent(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        served = await _served_id(db, vera, page_id)
        await world.publish("<p>v2</p>", actions=[ActionRequest(workflow=refund.id)])
        newest = await artifact_repo.latest_version(db, page_id)
        assert newest is not None
        newest.consent_state = "pending"
        await db.flush()

        with pytest.raises(NotFoundError):
            await self._start(db, vera, page_id, refund, version_id=newest.id)
        started = await self._start(db, vera, page_id, refund, version_id=served)
        run = await db.get(WorkflowRun, started.run_id)
        assert run is not None and run.source_version_number == 1

    @pytest.mark.security
    async def test_another_organization_finds_no_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        served = await _served_id(db, await _viewer(world), page_id)
        elsewhere = await _world(db)

        with pytest.raises(NotFoundError):
            await ArtifactService(db).start_action(
                elsewhere.boss, page_id, served, refund.id, ArtifactActionRunCreate()
            )

    @pytest.mark.security
    async def test_an_impersonated_session_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        served = await _served_id(db, vera, page_id)

        set_impersonator(uuid.uuid4())
        try:
            with pytest.raises(AuthorizationError):
                await self._start(db, vera, page_id, refund, version_id=served)
        finally:
            set_impersonator(None)
        assert (await db.execute(select(WorkflowRun))).first() is None

    @pytest.mark.security
    async def test_a_member_who_left_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        served = await _served_id(db, vera, page_id)
        user = await db.get(User, vera.user_id)
        assert user is not None
        user.is_active = False
        await db.flush()

        with pytest.raises(AuthorizationError):
            await self._start(db, vera, page_id, refund, version_id=served)

    async def test_input_that_does_not_fit_the_declared_fields_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund", fields=[{"name": "order", "type": "text"}])
        page_id = await _page(world, refund)
        vera = await _viewer(world)

        with pytest.raises(WorkflowRunInputInvalidError):
            await self._start(db, vera, page_id, refund, run_input={"nope": 1})

    async def test_a_page_may_start_only_so_many_runs_a_minute(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        served = await _served_id(db, vera, page_id)

        with patch.object(settings, "RATE_LIMIT_ARTIFACT_ACTIONS_PER_MINUTE", 2):
            await self._start(db, vera, page_id, refund, version_id=served)
            await self._start(db, vera, page_id, refund, version_id=served)
            with pytest.raises(RateLimitError):
                await self._start(db, vera, page_id, refund, version_id=served)


class TestReadingARun:
    async def _started(
        self, world: _World, workflow: Workflow, page_id: uuid.UUID, ctx: AuthContext
    ) -> WorkflowRun:
        started = await ArtifactService(world.db).start_action(
            ctx,
            page_id,
            await _served_id(world.db, ctx, page_id),
            workflow.id,
            ArtifactActionRunCreate(),
        )
        run = await world.db.get(WorkflowRun, started.run_id)
        assert run is not None
        return run

    async def test_a_finished_run_is_projected_without_files_or_internals(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        run = await self._started(world, refund, page_id, vera)
        file_ref = {
            "kind": "file",
            "file_id": str(uuid.uuid4()),
            "content_type": "x/y",
            "byte_size": 1,
        }
        run.status = WorkflowRunStatus.SUCCEEDED.value
        run.output = {
            "text": "Refunded",
            "sources": [{"title": "internal"}],
            "artifacts": [file_ref],
            "structured": {"total": 5, "receipt": file_ref, "lines": [file_ref, {"n": 1}]},
        }
        await db.flush()

        state = await ArtifactService(db).action_run(vera, page_id, run.id)

        assert state.model_dump() == {
            "status": "succeeded",
            "finished": True,
            "paused": False,
            "run_path": None,
            "output_text": "Refunded",
            "output_structured": {"total": 5, "lines": [{"n": 1}]},
            "error_message": None,
        }

    async def test_a_structured_output_that_is_itself_a_file_is_not_shown(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        run = await self._started(world, refund, page_id, vera)
        run.status = WorkflowRunStatus.SUCCEEDED.value
        run.output = {"structured": {"kind": "file", "file_id": str(uuid.uuid4())}}
        await db.flush()

        state = await ArtifactService(db).action_run(vera, page_id, run.id)

        assert state.output_structured is None

    async def test_a_run_waiting_for_a_person_says_so_and_links_the_run_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        run = await self._started(world, refund, page_id, vera)
        run.status = WorkflowRunStatus.WAITING_APPROVAL.value
        await db.flush()

        state = await ArtifactService(db).action_run(vera, page_id, run.id)

        assert (state.paused, state.finished) == (True, False)
        assert state.run_path == f"/workflows/{refund.id}/runs/{run.id}?org={world.org.id}"

    async def test_a_failure_is_told_in_one_short_plain_line(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        run = await self._started(world, refund, page_id, vera)
        run.status = WorkflowRunStatus.FAILED.value
        run.error = {
            "code": "X",
            "message": "The refund failed‮\nTraceback (most recent call last):\n  File x.py",
            "details": {"node": "n1"},
        }
        await db.flush()

        state = await ArtifactService(db).action_run(vera, page_id, run.id)

        assert state.error_message == "The refund failed"
        assert "Traceback" not in state.model_dump_json()

        run.error = {"message": "x" * 250}
        await db.flush()

        long = await ArtifactService(db).action_run(vera, page_id, run.id)

        assert long.error_message == "x" * 200

    @pytest.mark.security
    async def test_only_the_viewers_own_runs_from_this_page_are_found(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        other_page = Artifact(
            id=uuid.uuid4(),
            organization_id=world.org.id,
            name="other",
            title="Other",
            visibility=Visibility.ORG.value,
        )
        db.add(other_page)
        await db.flush()
        mine = await self._started(world, refund, page_id, vera)
        walt = await _viewer(world)
        theirs = await self._started(world, refund, page_id, walt)
        service = ArtifactService(db)

        with pytest.raises(NotFoundError):
            await service.action_run(vera, page_id, theirs.id)
        with pytest.raises(NotFoundError):
            await service.action_run(vera, page_id, uuid.uuid4())
        with pytest.raises(NotFoundError):
            await service.action_run(vera, other_page.id, mine.id)

    @pytest.mark.security
    async def test_a_run_whose_workflow_the_viewer_may_no_longer_see_is_not_found(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await _live(world, "Refund")
        page_id = await _page(world, refund)
        vera = await _viewer(world)
        run = await self._started(world, refund, page_id, vera)
        refund.visibility = Visibility.PRIVATE.value
        await db.flush()

        with pytest.raises(NotFoundError):
            await ArtifactService(db).action_run(vera, page_id, run.id)
