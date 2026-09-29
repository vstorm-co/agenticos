"""A workflow's webhook or schedule against a real Postgres (#1792).

Each is a trigger node switched on by publishing: the publish writes the row,
a later publish takes it over, and a publish that starts another way removes it.
What matters here is what only the database can show: that a retried delivery
finds the first one's row and admits nothing, that a schedule's clock and its
run commit together, that the member a fire acts as is read afresh, and that a
webhook's address and secret survive a publish of the same node.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_exposure import WorkflowExposure, WorkflowWebhookDelivery
from app.db.models.workflow_run import (
    WorkflowRun,
    WorkflowRunMode,
    WorkflowRunStatus,
    WorkflowRunTrigger,
)
from app.main import app
from app.schemas.conversation import MessageRead
from app.schemas.workflow import WorkflowPublish, WorkflowPublished
from app.schemas.workflow_exposure import WorkflowExposureUpdate
from app.services.workflow_execution import WorkflowExecutionService
from app.services.workflow_execution.exceptions import (
    WorkflowArchivedError,
    WorkflowTriggerMismatchError,
)
from app.services.workflow_exposure import WorkflowExposureService
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import SeededRun, drive

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_prefect_submission():
    """A run's first dispatch is submitted after a real commit here, and would
    otherwise reach for a Prefect deployment that does not exist in a test."""
    with patch("app.worker.tasks.workflow_tasks.run_deployment", new=AsyncMock()) as submitted:
        yield submitted


async def _user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _member(db: AsyncSession, *, org: Organization, user: User, role: str) -> None:
    db.add(OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role))
    await db.flush()


async def _org(db: AsyncSession, *, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    await _member(db, org=org, user=owner, role="owner")
    return org


def _ctx(user: User, org: Organization, role: str = "owner") -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=org.id, role=role)


def _graph(definition_id: str = "core.input", config: dict | None = None) -> WorkflowGraph:
    """A workflow of one trigger node - which is all a trigger needs to be switched on."""
    entry = NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=entry.id, nodes=(entry,))


HOURLY = {"schedule_kind": "interval", "interval_seconds": 3600}


async def _publish(
    db: AsyncSession, ctx: AuthContext, workflow: Workflow, graph: WorkflowGraph
) -> WorkflowPublished:
    """Make `graph` the draft and publish it, as a member does in the editor."""
    workflow.draft_graph = graph.model_dump(mode="json")
    await db.flush()
    return await WorkflowRegistryService(db).publish(
        ctx, workflow.id, WorkflowPublish(expected_revision=workflow.draft_revision)
    )


async def _workflow(db: AsyncSession, *, org: Organization, owner: User) -> Workflow:
    workflow = Workflow(
        id=uuid.uuid4(),
        organization_id=org.id,
        owner_user_id=owner.id,
        slug=f"wf-{uuid.uuid4().hex[:8]}",
        name="Echo",
        status=WorkflowStatus.DRAFT.value,
        visibility=Visibility.ORG.value,
    )
    db.add(workflow)
    await db.flush()
    return workflow


@pytest.fixture
async def tenant(db: AsyncSession) -> tuple[User, Organization, Workflow]:
    owner = await _user(db)
    org = await _org(db, owner=owner)
    workflow = await _workflow(db, org=org, owner=owner)
    return owner, org, workflow


async def _another_workflow(db: AsyncSession, org: Organization, owner: User) -> Workflow:
    return await _workflow(db, org=org, owner=owner)


def _signed(secret: str, body: bytes, delivery: str | None = "d-1") -> dict[str, str]:
    headers = {
        "x-signature-256": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    }
    if delivery is not None:
        headers["x-delivery-id"] = delivery
    return headers


async def _webhook(
    db: AsyncSession, ctx: AuthContext, workflow: Workflow, graph: WorkflowGraph | None = None
) -> tuple[uuid.UUID, str]:
    published = await _publish(db, ctx, workflow, graph or _graph("trigger.webhook"))
    assert published.exposure is not None and published.webhook_secret is not None
    return published.exposure.id, published.webhook_secret


async def _schedule(
    db: AsyncSession, ctx: AuthContext, workflow: Workflow, **config: object
) -> uuid.UUID:
    published = await _publish(db, ctx, workflow, _graph("trigger.schedule", {**HOURLY, **config}))
    assert published.exposure is not None
    return published.exposure.id


async def _runs(db: AsyncSession) -> list[WorkflowRun]:
    return list((await db.execute(select(WorkflowRun))).scalars().all())


async def _due(db: AsyncSession, exposure_id: uuid.UUID) -> datetime:
    """Make a schedule due a minute ago, and return that instant."""
    exposure = await db.get(WorkflowExposure, exposure_id)
    assert exposure is not None
    exposure.next_fire_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.flush()
    return exposure.next_fire_at


class TestPublishingSwitchesItOn:
    @pytest.mark.security
    async def test_a_webhook_reveals_its_secret_once_and_says_where_to_deliver(self, db, tenant):
        owner, org, workflow = tenant
        graph = _graph("trigger.webhook")
        published = await _publish(db, _ctx(owner, org), workflow, graph)

        created, secret = published.exposure, published.webhook_secret
        assert published.trigger == "trigger.webhook" and workflow.live_trigger == "trigger.webhook"
        assert created is not None and secret is not None and len(secret) >= 32
        assert created.webhook_url == (
            f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/workflow-webhooks/{created.id}"
        )
        assert (created.version_number, created.node_instance_id) == (1, graph.entry_node_id)
        assert created.execution_principal_user_id == owner.id
        read = await WorkflowExposureService(db).get_for_workflow(_ctx(owner, org), workflow.id)
        assert read is not None and read.id == created.id
        assert "reveal_secret" not in read.model_dump()
        stored = await db.get(WorkflowExposure, created.id)
        assert stored is not None and secret not in (stored.secret_encrypted or "")
        audit = (
            await db.execute(
                select(AppAdminAuditLog).where(
                    AppAdminAuditLog.action == "workflow.exposure_created"
                )
            )
        ).scalar_one()
        assert secret not in json.dumps(audit.details)

    @pytest.mark.security
    async def test_a_new_version_of_the_same_node_keeps_the_address_and_the_secret(
        self, db, tenant
    ):
        owner, org, workflow = tenant
        graph = _graph("trigger.webhook")
        exposure_id, secret = await _webhook(db, _ctx(owner, org), workflow, graph)
        admin = await _user(db)
        await _member(db, org=org, user=admin, role="admin")

        again = await _publish(db, _ctx(admin, org, "admin"), workflow, graph)

        assert again.exposure is not None and again.webhook_secret is None
        assert (again.exposure.id, again.exposure.version_number) == (exposure_id, 2)
        # Whoever published the version it now runs answers for it.
        assert again.exposure.execution_principal_user_id == admin.id
        body = b"{}"
        admitted = await WorkflowExposureService(db).receive_webhook(
            exposure_id, body=body, headers=_signed(secret, body)
        )
        (run,) = await _runs(db)
        assert run.id == admitted.run_id and run.workflow_version_id == again.id

    async def test_a_publish_that_starts_another_way_removes_it(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id, _secret = await _webhook(db, _ctx(owner, org), workflow)

        schedule = await _publish(
            db, _ctx(owner, org), workflow, _graph("trigger.schedule", HOURLY)
        )
        assert schedule.exposure is not None and schedule.exposure.id != exposure_id
        assert await db.get(WorkflowExposure, exposure_id) is None

        manual = await _publish(db, _ctx(owner, org), workflow, _graph())
        assert (manual.trigger, manual.exposure) == ("core.input", None)
        assert (
            await WorkflowExposureService(db).get_for_workflow(_ctx(owner, org), workflow.id)
        ) is None
        assert workflow.live_trigger == "core.input"

    async def test_a_new_webhook_node_gets_a_new_address(self, db, tenant):
        owner, org, workflow = tenant
        first_id, _secret = await _webhook(db, _ctx(owner, org), workflow)
        second_id, _other = await _webhook(db, _ctx(owner, org), workflow)
        assert second_id != first_id
        assert await db.get(WorkflowExposure, first_id) is None

    async def test_a_schedule_starts_its_clock_from_now_and_keeps_it_across_publishes(
        self, db, tenant
    ):
        owner, org, workflow = tenant
        before = datetime.now(UTC)
        graph = _graph("trigger.schedule", {**HOURLY, "input": {"region": "eu"}})
        hourly = (await _publish(db, _ctx(owner, org), workflow, graph)).exposure

        assert hourly is not None and hourly.webhook_url is None
        assert hourly.next_fire_at is not None
        assert (
            before + timedelta(minutes=59)
            < hourly.next_fire_at
            <= datetime.now(UTC) + timedelta(hours=1)
        )
        assert hourly.run_input == {"region": "eu"}

        same = (await _publish(db, _ctx(owner, org), workflow, graph)).exposure
        assert same is not None and same.next_fire_at == hourly.next_fire_at

        cron = NodeInstance(
            **{
                **graph.nodes[0].model_dump(),
                "config": {"schedule_kind": "cron", "cron_expression": "0 9 * * *"},
            }
        )
        daily = (
            await _publish(
                db,
                _ctx(owner, org),
                workflow,
                WorkflowGraph(entry_node_id=cron.id, nodes=(cron,)),
            )
        ).exposure
        assert daily is not None and daily.id == hourly.id
        assert (daily.schedule_kind, daily.interval_seconds) == ("cron", None)
        assert daily.next_fire_at is not None
        assert (daily.next_fire_at.hour, daily.next_fire_at.minute) == (9, 0)

    async def test_publishing_resumes_a_paused_schedule_from_now(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id = await _schedule(db, _ctx(owner, org), workflow)
        stored = await db.get(WorkflowExposure, exposure_id)
        assert stored is not None
        stored.is_active = False
        stored.next_fire_at = datetime.now(UTC) - timedelta(days=3)
        await db.flush()

        graph = WorkflowGraph.model_validate(workflow.draft_graph)
        resumed = (await _publish(db, _ctx(owner, org), workflow, graph)).exposure
        assert resumed is not None and resumed.is_active is True
        assert resumed.next_fire_at is not None and resumed.next_fire_at > datetime.now(UTC)

    @pytest.mark.security
    async def test_a_publisher_who_may_not_run_it_cannot_make_it_run_as_them(self, db, tenant):
        owner, org, workflow = tenant
        # No role edits without running; a grant model that allows it one day
        # must still be refused here, since every fire acts as the publisher.
        with (
            patch(
                "app.services.workflow_triggers.resolve_access", new=AsyncMock(return_value=False)
            ),
            pytest.raises(AuthorizationError),
        ):
            await _publish(db, _ctx(owner, org), workflow, _graph("trigger.webhook"))

    @pytest.mark.security
    async def test_another_organization_cannot_see_or_touch_it(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id, _secret = await _webhook(db, _ctx(owner, org), workflow)
        stranger = await _user(db)
        elsewhere = await _org(db, owner=stranger)
        service = WorkflowExposureService(db)
        with pytest.raises(NotFoundError):
            await service.get_for_workflow(_ctx(stranger, elsewhere), workflow.id)
        with pytest.raises(NotFoundError):
            await service.set_active(
                _ctx(stranger, elsewhere),
                workflow.id,
                exposure_id,
                WorkflowExposureUpdate(is_active=False),
            )


class TestPausingOne:
    async def test_pausing_and_resuming_restarts_the_clock_and_keeps_the_publisher(
        self, db, tenant
    ):
        owner, org, workflow = tenant
        exposure_id = await _schedule(db, _ctx(owner, org), workflow)
        admin = await _user(db)
        await _member(db, org=org, user=admin, role="admin")
        service = WorkflowExposureService(db)

        paused = await service.set_active(
            _ctx(admin, org, "admin"),
            workflow.id,
            exposure_id,
            WorkflowExposureUpdate(is_active=False),
        )
        assert paused.is_active is False
        assert paused.execution_principal_user_id == owner.id

        stored = await db.get(WorkflowExposure, exposure_id)
        assert stored is not None
        stored.next_fire_at = datetime.now(UTC) - timedelta(days=3)
        await db.flush()
        resumed = await service.set_active(
            _ctx(owner, org), workflow.id, exposure_id, WorkflowExposureUpdate(is_active=True)
        )
        assert resumed.is_active is True
        assert resumed.next_fire_at is not None and resumed.next_fire_at > datetime.now(UTC)
        again = await service.set_active(
            _ctx(owner, org), workflow.id, exposure_id, WorkflowExposureUpdate(is_active=True)
        )
        assert again.next_fire_at == resumed.next_fire_at
        actions = (
            (
                await db.execute(
                    select(AppAdminAuditLog.action).where(
                        AppAdminAuditLog.action.in_(
                            ["workflow.exposure_paused", "workflow.exposure_resumed"]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        assert sorted(actions) == [
            "workflow.exposure_paused",
            "workflow.exposure_resumed",
            "workflow.exposure_resumed",
        ]

    async def test_an_archived_workflow_is_not_paused_or_resumed(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id = await _schedule(db, _ctx(owner, org), workflow)
        workflow.status = WorkflowStatus.ARCHIVED.value
        await db.flush()
        with pytest.raises(WorkflowArchivedError):
            await WorkflowExposureService(db).set_active(
                _ctx(owner, org), workflow.id, exposure_id, WorkflowExposureUpdate(is_active=True)
            )

    @pytest.mark.security
    async def test_a_member_who_may_only_run_it_cannot_pause_it(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id = await _schedule(db, _ctx(owner, org), workflow)
        operator = await _user(db)
        await _member(db, org=org, user=operator, role="operator")
        with pytest.raises(NotFoundError):
            await WorkflowExposureService(db).set_active(
                _ctx(operator, org, "operator"),
                workflow.id,
                exposure_id,
                WorkflowExposureUpdate(is_active=False),
            )

    @pytest.mark.security
    async def test_an_editor_who_may_not_run_it_cannot_resume_it(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id = await _schedule(db, _ctx(owner, org), workflow)
        with (
            patch(
                "app.services.workflow_exposure.resolve_access",
                new=AsyncMock(side_effect=[True, False]),
            ),
            pytest.raises(AuthorizationError),
        ):
            await WorkflowExposureService(db).set_active(
                _ctx(owner, org), workflow.id, exposure_id, WorkflowExposureUpdate(is_active=True)
            )

    async def test_an_unknown_exposure_is_not_found(self, db, tenant):
        owner, org, workflow = tenant
        await _schedule(db, _ctx(owner, org), workflow)
        with pytest.raises(NotFoundError):
            await WorkflowExposureService(db).set_active(
                _ctx(owner, org), workflow.id, uuid.uuid4(), WorkflowExposureUpdate(is_active=True)
            )

    @pytest.mark.security
    async def test_a_schedule_has_no_secret_to_rotate(self, db, tenant):
        owner, org, workflow = tenant
        schedule_id = await _schedule(db, _ctx(owner, org), workflow)
        with pytest.raises(BadRequestError):
            await WorkflowExposureService(db).rotate_secret(
                _ctx(owner, org), workflow.id, schedule_id
            )

    @pytest.mark.security
    async def test_rotating_the_secret_retires_the_old_one(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id, old = await _webhook(db, _ctx(owner, org), workflow)
        service = WorkflowExposureService(db)
        rotated = await service.rotate_secret(_ctx(owner, org), workflow.id, exposure_id)
        assert rotated.reveal_secret and rotated.reveal_secret != old
        body = b"{}"

        with pytest.raises(AuthorizationError):
            await service.receive_webhook(exposure_id, body=body, headers=_signed(old, body))
        admitted = await service.receive_webhook(
            exposure_id, body=body, headers=_signed(rotated.reveal_secret, body)
        )
        assert admitted.duplicate is False


class TestWebhookDeliveries:
    async def test_a_retried_delivery_answers_with_the_first_run_and_admits_nothing(
        self, db, tenant
    ):
        owner, org, workflow = tenant
        exposure_id, secret = await _webhook(db, _ctx(owner, org), workflow)
        body = json.dumps({"issue": 7, "run_as": str(uuid.uuid4())}).encode()
        service = WorkflowExposureService(db)

        first = await service.receive_webhook(exposure_id, body=body, headers=_signed(secret, body))
        again = await service.receive_webhook(exposure_id, body=body, headers=_signed(secret, body))

        assert first.duplicate is False and again.duplicate is True
        assert again.run_id == first.run_id
        (run,) = await _runs(db)
        assert run.triggered_by == WorkflowRunTrigger.WEBHOOK.value
        assert run.workflow_version_id == workflow.current_version_id
        # The payload's `run_as` is data for the graph, never whose authority it runs with.
        assert run.execution_principal_user_id == owner.id
        assert run.input == {
            "body": {"issue": 7, "run_as": json.loads(body)["run_as"]},
            "delivery_id": "d-1",
        }
        deliveries = (await db.execute(select(WorkflowWebhookDelivery))).scalars().all()
        assert [(d.delivery_id, d.workflow_run_id) for d in deliveries] == [("d-1", run.id)]
        stored = await db.get(WorkflowExposure, exposure_id)
        assert stored is not None and stored.last_run_id == run.id

    async def test_githubs_own_headers_are_accepted(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id, secret = await _webhook(db, _ctx(owner, org), workflow)
        body = b'{"action": "opened"}'
        headers = {
            "x-hub-signature-256": _signed(secret, body)["x-signature-256"],
            "x-github-delivery": "gh-1",
        }
        admitted = await WorkflowExposureService(db).receive_webhook(
            exposure_id, body=body, headers=headers
        )
        assert admitted.duplicate is False

    @pytest.mark.security
    async def test_a_delivery_that_is_not_signed_by_its_secret_is_refused(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id, _secret = await _webhook(db, _ctx(owner, org), workflow)
        body = b"{}"
        with pytest.raises(AuthorizationError):
            await WorkflowExposureService(db).receive_webhook(
                exposure_id, body=body, headers=_signed("not-the-secret", body)
            )
        assert await _runs(db) == []

    @pytest.mark.parametrize(
        ("body", "delivery"),
        [(b"{}", None), (b"{}", "x" * 256), (b"not json", "d"), (b"[1, 2]", "d"), (b"\xff", "d")],
        ids=["no-delivery-id", "delivery-id-too-long", "not-json", "not-an-object", "not-utf8"],
    )
    async def test_a_delivery_it_cannot_admit_is_a_bad_request(self, db, tenant, body, delivery):
        owner, org, workflow = tenant
        exposure_id, secret = await _webhook(db, _ctx(owner, org), workflow)
        with pytest.raises(BadRequestError):
            await WorkflowExposureService(db).receive_webhook(
                exposure_id, body=body, headers=_signed(secret, body, delivery)
            )
        assert await _runs(db) == []

    async def test_an_unknown_paused_or_scheduled_id_has_no_webhook(self, db, tenant):
        owner, org, workflow = tenant
        service = WorkflowExposureService(db)
        paused_id, secret = await _webhook(db, _ctx(owner, org), workflow)
        await service.set_active(
            _ctx(owner, org), workflow.id, paused_id, WorkflowExposureUpdate(is_active=False)
        )
        other = await _another_workflow(db, org, owner)
        schedule_id = await _schedule(db, _ctx(owner, org), other)
        body = b"{}"
        for exposure_id in (uuid.uuid4(), paused_id, schedule_id):
            with pytest.raises(NotFoundError):
                await service.receive_webhook(exposure_id, body=body, headers=_signed(secret, body))

    @pytest.mark.security
    async def test_a_webhook_whose_member_left_runs_nothing(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id, secret = await _webhook(db, _ctx(owner, org), workflow)
        await db.execute(delete(OrganizationMember).where(OrganizationMember.user_id == owner.id))
        body = b"{}"
        with pytest.raises(AuthorizationError):
            await WorkflowExposureService(db).receive_webhook(
                exposure_id, body=body, headers=_signed(secret, body)
            )
        assert await _runs(db) == []


class TestSchedules:
    async def test_a_due_schedule_runs_its_pinned_version_with_its_input_and_moves_on(
        self, db, tenant
    ):
        owner, org, workflow = tenant
        exposure_id = await _schedule(db, _ctx(owner, org), workflow, input={"region": "eu"})
        idle_id = await _schedule(db, _ctx(owner, org), await _another_workflow(db, org, owner))
        await _due(db, exposure_id)
        now = datetime.now(UTC)

        pairs = await WorkflowExposureService(db).fire_due(now=now)

        (run,) = await _runs(db)
        assert [run_id for run_id, _node in pairs] == [run.id]
        assert run.triggered_by == WorkflowRunTrigger.SCHEDULE.value
        assert run.input == {"fired_at": now.isoformat(), "input": {"region": "eu"}}
        assert run.execution_principal_user_id == owner.id
        fired = await db.get(WorkflowExposure, exposure_id)
        idle = await db.get(WorkflowExposure, idle_id)
        assert fired is not None and idle is not None
        assert fired.last_run_id == run.id and fired.last_fired_at == now
        assert fired.next_fire_at == now + timedelta(hours=1)
        assert idle.last_run_id is None

    async def test_a_schedule_waits_behind_its_own_live_run(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id = await _schedule(db, _ctx(owner, org), workflow)
        service = WorkflowExposureService(db)
        await _due(db, exposure_id)
        await service.fire_due(now=datetime.now(UTC))

        await _due(db, exposure_id)
        assert await service.fire_due(now=datetime.now(UTC)) == []
        assert len(await _runs(db)) == 1

        (run,) = await _runs(db)
        run.status = WorkflowRunStatus.SUCCEEDED.value
        await db.flush()
        await _due(db, exposure_id)
        assert len(await service.fire_due(now=datetime.now(UTC))) == 1

    @pytest.mark.security
    async def test_a_schedule_nobody_can_run_is_switched_off_and_audited(self, db, tenant):
        owner, org, workflow = tenant
        gone = await _schedule(db, _ctx(owner, org), workflow)
        orphan = await _schedule(db, _ctx(owner, org), await _another_workflow(db, org, owner))
        await _due(db, gone)
        await _due(db, orphan)
        orphaned = await db.get(WorkflowExposure, orphan)
        assert orphaned is not None
        orphaned.execution_principal_user_id = None
        await db.execute(delete(OrganizationMember).where(OrganizationMember.user_id == owner.id))
        await db.flush()

        assert await WorkflowExposureService(db).fire_due(now=datetime.now(UTC)) == []

        assert await _runs(db) == []
        for exposure_id in (gone, orphan):
            exposure = await db.get(WorkflowExposure, exposure_id)
            assert exposure is not None and exposure.is_active is False
        disabled = (
            (
                await db.execute(
                    select(AppAdminAuditLog).where(
                        AppAdminAuditLog.action == "workflow.exposure_disabled"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(disabled) == 2

    async def test_an_archived_workflows_schedule_is_switched_off(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id = await _schedule(db, _ctx(owner, org), workflow)
        await _due(db, exposure_id)
        workflow.status = WorkflowStatus.ARCHIVED.value
        await db.flush()
        assert await WorkflowExposureService(db).fire_due(now=datetime.now(UTC)) == []
        exposure = await db.get(WorkflowExposure, exposure_id)
        assert exposure is not None and exposure.is_active is False

    async def test_a_refused_admission_spends_only_its_tick(self, db, tenant, monkeypatch):
        owner, org, workflow = tenant
        exposure_id = await _schedule(db, _ctx(owner, org), workflow)
        await _due(db, exposure_id)
        monkeypatch.setattr(settings, "WORKFLOW_MAX_ACTIVE_NODE_RUNS_PER_ORG", 0)
        now = datetime.now(UTC)

        assert await WorkflowExposureService(db).fire_due(now=now) == []

        assert await _runs(db) == []
        exposure = await db.get(WorkflowExposure, exposure_id)
        assert exposure is not None
        assert exposure.is_active is True
        assert exposure.next_fire_at == now + timedelta(hours=1)


class TestAnsweringInTheChat:
    async def test_a_chat_run_writes_its_answer_to_its_conversation_once(self, engine, db, tenant):
        owner, org, workflow = tenant
        graph = _graph("trigger.chat")
        await _publish(db, _ctx(owner, org), workflow, graph)
        conversation = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id)
        db.add(conversation)
        await db.commit()

        started = await WorkflowExecutionService(db).start(
            _ctx(owner, org),
            workflow.id,
            triggered_by=WorkflowRunTrigger.CHAT,
            run_input={
                "prompt": "hello",
                "conversation_id": str(conversation.id),
                "user_id": str(owner.id),
            },
            reply_conversation_id=conversation.id,
        )
        await db.commit()
        run = await db.get(WorkflowRun, started.id)
        assert run is not None
        factory = async_sessionmaker(engine, expire_on_commit=False)
        ended = await drive(
            SeededRun(run=run, graph=graph, principal=owner, org=org, factory=factory)
        )
        assert ended.status == WorkflowRunStatus.SUCCEEDED.value

        async with factory() as fresh:
            messages = (
                (
                    await fresh.execute(
                        select(Message).where(Message.conversation_id == conversation.id)
                    )
                )
                .scalars()
                .all()
            )
        (answer,) = messages
        assert answer.role == "assistant"
        assert answer.parts == [
            {
                "type": "workflow_run",
                "run_id": str(run.id),
                "workflow_id": str(workflow.id),
                "workflow_name": "Echo",
                "status": "succeeded",
            }
        ]
        # What the conversation endpoint serializes: the entry has to be one the
        # message schema accepts, or reopening the chat would fail on it.
        read = MessageRead.model_validate({**answer.__dict__, "tool_calls": [], "files": []})
        assert read.parts is not None and read.parts[0].run_id == str(run.id)

    async def test_a_cancelled_chat_run_says_so_where_it_was_asked(self, db, tenant):
        owner, org, workflow = tenant
        await _publish(db, _ctx(owner, org), workflow, _graph("trigger.chat"))
        conversation = Conversation(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id)
        db.add(conversation)
        await db.flush()
        service = WorkflowExecutionService(db)
        started = await service.start(
            _ctx(owner, org),
            workflow.id,
            triggered_by=WorkflowRunTrigger.CHAT,
            reply_conversation_id=conversation.id,
        )
        await service.cancel(_ctx(owner, org), started.id)
        (answer,) = (
            (await db.execute(select(Message).where(Message.conversation_id == conversation.id)))
            .scalars()
            .all()
        )
        assert answer.parts is not None and answer.parts[0]["status"] == "cancelled"

    async def test_a_run_started_elsewhere_writes_to_no_conversation(self, db, tenant):
        owner, org, workflow = tenant
        await _publish(db, _ctx(owner, org), workflow, _graph())
        service = WorkflowExecutionService(db)
        started = await service.start(_ctx(owner, org), workflow.id)
        await service.cancel(_ctx(owner, org), started.id)
        assert (await db.execute(select(Message))).scalars().all() == []


class TestOnlyItsOwnDoorStartsIt:
    @pytest.mark.parametrize(
        ("trigger", "door"),
        [
            ("trigger.webhook", WorkflowRunTrigger.API),
            ("trigger.chat", WorkflowRunTrigger.WEBSOCKET),
            ("core.input", WorkflowRunTrigger.CHAT),
        ],
    )
    async def test_a_live_version_is_not_started_through_another_trigger_s_door(
        self, db, tenant, trigger, door
    ):
        owner, org, workflow = tenant
        await _publish(db, _ctx(owner, org), workflow, _graph(trigger))
        with pytest.raises(WorkflowTriggerMismatchError) as refused:
            await WorkflowExecutionService(db).start(
                _ctx(owner, org), workflow.id, triggered_by=door
            )
        assert refused.value.details == {
            "workflow_id": workflow.id,
            "trigger": trigger,
            "door": door.value,
        }
        assert await _runs(db) == []

    async def test_a_test_run_of_the_draft_takes_any_trigger(self, db, tenant):
        owner, org, workflow = tenant
        await _publish(db, _ctx(owner, org), workflow, _graph("trigger.webhook"))
        started = await WorkflowExecutionService(db).start(
            _ctx(owner, org),
            workflow.id,
            mode=WorkflowRunMode.TEST,
            run_input={"body": {"lead": 1}, "delivery_id": "sample"},
        )
        assert started.mode == WorkflowRunMode.TEST


@pytest.fixture
async def http(engine: AsyncEngine, mock_redis: MagicMock):
    """The app with the real service behind it and a session that commits, as
    `DBSession` does."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        owner = await _user(setup)
        org = await _org(setup, owner=owner)
        workflow = await _workflow(setup, org=org, owner=owner)
        await setup.commit()
        workflow_id = workflow.id

    async def session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as opened:
            try:
                yield opened
                await opened.commit()
            except BaseException:
                await opened.rollback()
                raise

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_auth_context] = lambda: _ctx(owner, org)
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis

    @asynccontextmanager
    async def open_client() -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client

    async with open_client() as client:
        yield client, workflow_id, factory
    app.dependency_overrides.clear()


async def _publish_over_http(client: AsyncClient, workflow_id: uuid.UUID, graph: WorkflowGraph):
    base = f"{settings.API_V1_STR}/workflows/{workflow_id}"
    draft = (await client.get(base)).json()
    saved = await client.patch(
        f"{base}/draft",
        json={"graph": graph.model_dump(mode="json"), "expected_revision": draft["draft_revision"]},
    )
    assert saved.status_code == 200, saved.text
    published = await client.post(
        f"{base}/publish", json={"expected_revision": saved.json()["draft_revision"]}
    )
    assert published.status_code == 200, published.text
    return published.json()


class TestOverHttp:
    async def test_a_webhook_published_and_delivered_to_over_http_admits_one_run(self, http):
        client, workflow_id, factory = http
        published = await _publish_over_http(client, workflow_id, _graph("trigger.webhook"))
        exposure, secret = published["exposure"], published["webhook_secret"]
        body = b'{"lead": 1}'
        url = f"{settings.API_V1_STR}/workflow-webhooks/{exposure['id']}"

        first = await client.post(url, content=body, headers=_signed(secret, body))
        again = await client.post(url, content=body, headers=_signed(secret, body))

        assert (first.status_code, again.status_code) == (202, 202)
        assert again.json() == {"run_id": first.json()["run_id"], "duplicate": True}
        async with factory() as fresh:
            assert len((await fresh.execute(select(WorkflowRun))).scalars().all()) == 1

        base = f"{settings.API_V1_STR}/workflows/{workflow_id}"
        read = await client.get(f"{base}/exposure")
        assert read.json()["id"] == exposure["id"]
        rotated = await client.post(f"{base}/exposures/{exposure['id']}/rotate-secret")
        assert rotated.json()["reveal_secret"] != secret
        paused = await client.patch(f"{base}/exposures/{exposure['id']}", json={"is_active": False})
        assert paused.json()["is_active"] is False

    async def test_a_workflow_that_starts_by_hand_has_no_exposure(self, http):
        client, workflow_id, _factory = http
        await _publish_over_http(client, workflow_id, _graph())
        read = await client.get(f"{settings.API_V1_STR}/workflows/{workflow_id}/exposure")
        assert (read.status_code, read.json()) == (200, None)

    async def test_a_bad_signature_is_a_403_and_writes_nothing(self, http):
        client, workflow_id, factory = http
        published = await _publish_over_http(client, workflow_id, _graph("trigger.webhook"))
        body = b"{}"
        refused = await client.post(
            f"{settings.API_V1_STR}/workflow-webhooks/{published['exposure']['id']}",
            content=body,
            headers=_signed("wrong", body),
        )
        assert refused.status_code == 403
        async with factory() as fresh:
            assert (await fresh.execute(select(WorkflowRun))).scalars().all() == []
