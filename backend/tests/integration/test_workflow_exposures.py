"""A workflow's webhook, schedule or form against a real Postgres (#1792).

Each is a trigger node switched on by publishing: the publish writes the row,
a later publish takes it over, and a publish that starts another way removes it.
What matters here is what only the database can show: that a retried delivery
finds the first one's row and admits nothing, that a schedule's clock and its
run commit together, that the member a fire acts as is read afresh, and that a
webhook's address and secret survive a publish of the same node.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api import deps
from app.core.config import settings
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.channel_bot import ChannelBot
from app.db.models.conversation import Conversation, Message
from app.db.models.mcp_connection import McpConnection
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
from app.schemas.workflow_exposure import (
    WebhookAdmitted,
    WebhookAnswer,
    WebhookSkipped,
    WorkflowExposureUpdate,
    WorkflowFormSubmission,
)
from app.services.channels.base import IncomingMessage
from app.services.portals import PolledEvent, RegisteredWebhook, WebhookRegistrationForbidden
from app.services.workflow_execution import WorkflowExecutionService
from app.services.workflow_execution.exceptions import (
    WorkflowAdmissionQuotaError,
    WorkflowArchivedError,
    WorkflowRunInputInvalidError,
    WorkflowRunInputTooLargeError,
    WorkflowTriggerMismatchError,
    WorkflowWebhookUnansweredError,
)
from app.services.workflow_exposure import WorkflowExposureService
from app.services.workflow_registry import WorkflowRegistryService
from app.services.workflow_webhook_test import (
    WebhookTestTooLargeError,
    WorkflowWebhookTestService,
)
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
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


def _step(definition_id: str, config: dict | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _answering(*steps: tuple[NodeInstance, str]) -> WorkflowGraph:
    """A webhook, then `steps` in a line - each paired with the port it leaves by -
    with every Respond to webhook step answering with the delivery's body."""
    trigger = _step("trigger.webhook")
    line = [(trigger, "out"), *steps]
    edges = tuple(
        Edge(
            id=uuid.uuid4(),
            source_node_id=source.id,
            source_port=port,
            target_node_id=target.id,
            target_port="in",
        )
        for (source, port), (target, _port) in pairwise(line)
    )
    bindings = tuple(
        Binding(
            target_node_id=node.id,
            target_field="body",
            source=NodeOutputRef(node_id=trigger.id, port="out", field_path=("body",)),
        )
        for node, _port in steps
        if node.definition_id == "webhook.respond"
    )
    return WorkflowGraph(
        entry_node_id=trigger.id,
        nodes=tuple(node for node, _port in line),
        edges=edges,
        bindings=bindings,
    )


def _respond(status_code: int = 201, **headers: str) -> tuple[NodeInstance, str]:
    return _step("webhook.respond", {"status_code": status_code, "headers": headers}), "out"


def _runs_each_dispatch(submitted: AsyncMock, factory, graph: WorkflowGraph) -> None:
    """Stand the worker in for Prefect: each submitted dispatch drives its run."""

    async def run_it(*, name: str, parameters: dict[str, str], timeout: int) -> None:
        async with factory() as fresh:
            run = await fresh.get(WorkflowRun, uuid.UUID(parameters["workflow_run_id"]))
            assert run is not None
            principal = await fresh.get(User, run.execution_principal_user_id)
            org = await fresh.get(Organization, run.organization_id)
        assert principal is not None and org is not None
        await drive(SeededRun(run=run, graph=graph, principal=principal, org=org, factory=factory))

    submitted.side_effect = run_it


class TestAnsweringTheSender:
    async def test_the_sender_gets_the_respond_steps_status_headers_and_body(
        self, http, _no_prefect_submission
    ):
        client, workflow_id, factory = http
        graph = _answering(_respond(201, **{"X-Lead": "accepted"}))
        _runs_each_dispatch(_no_prefect_submission, factory, graph)
        published = await _publish_over_http(client, workflow_id, graph)
        exposure, secret = published["exposure"], published["webhook_secret"]
        body = b'{"lead": 1}'
        url = f"{settings.API_V1_STR}/workflow-webhooks/{exposure['id']}"

        first = await client.post(url, content=body, headers=_signed(secret, body))
        again = await client.post(url, content=body, headers=_signed(secret, body))

        for answered in (first, again):
            assert answered.status_code == 201, answered.text
            assert answered.headers["x-lead"] == "accepted"
            assert answered.json() == {"lead": 1}
        async with factory() as fresh:
            (run,) = (await fresh.execute(select(WorkflowRun))).scalars().all()
        assert run.status == WorkflowRunStatus.SUCCEEDED.value

    async def test_the_sender_gets_what_the_wait_returns(
        self, db, tenant, _no_prefect_submission, monkeypatch
    ):
        # The wait itself is covered on its own (test_workflow_webhook_answer);
        # stood in for here, the line handing its answer back runs without a
        # background drive, which the coverage tracer can lose.
        owner, org, workflow = tenant
        graph = _answering(_respond(201))
        exposure_id, secret = await _webhook(db, _ctx(owner, org), workflow, graph)
        answered = WebhookAnswer(status_code=201, headers={}, body={"lead": 3})
        monkeypatch.setattr(WorkflowExposureService, "_answer", AsyncMock(return_value=answered))
        body = b'{"lead": 3}'

        received = await WorkflowExposureService(db).receive_webhook(
            exposure_id, body=body, headers=_signed(secret, body)
        )

        assert received == answered

    async def test_only_the_first_respond_step_answers(
        self, engine, db, tenant, _no_prefect_submission
    ):
        owner, org, workflow = tenant
        graph = _answering(_respond(201), _respond(202))
        exposure_id, secret = await _webhook(db, _ctx(owner, org), workflow, graph)
        _runs_each_dispatch(
            _no_prefect_submission, async_sessionmaker(engine, expire_on_commit=False), graph
        )
        body = b'{"lead": 2}'

        service = WorkflowExposureService(db)
        answer = await service.receive_webhook(
            exposure_id, body=body, headers=_signed(secret, body)
        )
        again = await service.receive_webhook(exposure_id, body=body, headers=_signed(secret, body))

        assert answer == again == WebhookAnswer(status_code=201, headers={}, body={"lead": 2})
        # The sender is answered at the first step; the run goes on to the second.
        (run,) = await _runs(db)
        with anyio.fail_after(30):
            while run.status != WorkflowRunStatus.SUCCEEDED.value:
                await anyio.sleep(0.1)
                await db.refresh(run)
        assert run.webhook_response == {"status_code": 201, "headers": {}, "body": {"lead": 2}}

    async def test_a_run_that_fails_before_answering_says_so(
        self, engine, db, tenant, _no_prefect_submission
    ):
        owner, org, workflow = tenant
        # The condition is false: the run fails on that branch, and never reaches
        # the respond step on the other.
        decides = _step("logic.if", {"condition": "value.missing"})
        waits = _answering((decides, "true"), _respond())
        raises = _step("error.raise", {"code": "NO_LEAD", "message": "No lead"})
        graph = waits.model_copy(
            update={
                "nodes": (*waits.nodes, raises),
                "edges": (
                    *waits.edges,
                    Edge(
                        id=uuid.uuid4(),
                        source_node_id=decides.id,
                        source_port="false",
                        target_node_id=raises.id,
                        target_port="in",
                    ),
                ),
            }
        )
        exposure_id, secret = await _webhook(db, _ctx(owner, org), workflow, graph)
        _runs_each_dispatch(
            _no_prefect_submission, async_sessionmaker(engine, expire_on_commit=False), graph
        )
        body = b"{}"

        with pytest.raises(WorkflowWebhookUnansweredError) as refused:
            await WorkflowExposureService(db).receive_webhook(
                exposure_id, body=body, headers=_signed(secret, body)
            )
        assert refused.value.details["status"] == WorkflowRunStatus.FAILED.value

    async def test_a_run_that_never_reaches_the_step_is_admitted_as_usual(
        self, engine, db, tenant, _no_prefect_submission
    ):
        owner, org, workflow = tenant
        graph = _answering((_step("logic.if", {"condition": "value.missing"}), "true"), _respond())
        exposure_id, secret = await _webhook(db, _ctx(owner, org), workflow, graph)
        _runs_each_dispatch(
            _no_prefect_submission, async_sessionmaker(engine, expire_on_commit=False), graph
        )
        body = b"{}"

        admitted = await WorkflowExposureService(db).receive_webhook(
            exposure_id, body=body, headers=_signed(secret, body)
        )

        assert isinstance(admitted, WebhookAdmitted) and admitted.duplicate is False
        (run,) = await _runs(db)
        await db.refresh(run)
        assert run.status == WorkflowRunStatus.SUCCEEDED.value

    async def test_an_answer_that_takes_too_long_is_admitted_and_the_run_goes_on(
        self, db, tenant, monkeypatch
    ):
        owner, org, workflow = tenant
        exposure_id, secret = await _webhook(db, _ctx(owner, org), workflow, _answering(_respond()))
        monkeypatch.setattr(settings, "WORKFLOW_WEBHOOK_RESPONSE_TIMEOUT_SECONDS", 0.3)
        body = b"{}"

        admitted = await WorkflowExposureService(db).receive_webhook(
            exposure_id, body=body, headers=_signed(secret, body)
        )

        assert isinstance(admitted, WebhookAdmitted) and admitted.duplicate is False
        (run,) = await _runs(db)
        assert run.status != WorkflowRunStatus.SUCCEEDED.value


class _Redis:
    """An in-memory stand-in for the four calls a test URL makes."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        self.store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def getdel(self, key: str) -> str | None:
        return self.store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.store


async def _listening(
    db: AsyncSession, ctx: AuthContext, workflow: Workflow, graph: WorkflowGraph | None = None
) -> tuple[WorkflowWebhookTestService, str, _Redis]:
    workflow.draft_graph = (graph or _graph("trigger.webhook")).model_dump(mode="json")
    await db.flush()
    redis = _Redis()
    service = WorkflowWebhookTestService(db, redis)  # ty: ignore[invalid-argument-type]
    listening = await service.listen(ctx, workflow.id)
    return service, listening.test_token, redis


class TestTheTestUrl:
    async def test_it_keeps_one_call_for_the_editor_and_starts_no_run(self, db, tenant):
        owner, org, workflow = tenant
        ctx = _ctx(owner, org)
        service, token, _redis = await _listening(db, ctx, workflow)
        assert (await service.caught(ctx, workflow.id, token)).state == "listening"

        caught = await service.catch(token, body=b'{"lead": 3}', headers={"x-delivery-id": "t-1"})

        assert caught.captured is True
        capture = await service.caught(ctx, workflow.id, token)
        assert capture.state == "caught"
        assert capture.delivery is not None
        assert capture.delivery.model_dump() == {"body": {"lead": 3}, "delivery_id": "t-1"}
        with pytest.raises(NotFoundError):
            await service.catch(token, body=b"{}", headers={})
        assert await _runs(db) == []

    async def test_a_call_that_names_no_delivery_gets_an_id_of_its_own(self, db, tenant):
        owner, org, workflow = tenant
        ctx = _ctx(owner, org)
        service, token, _redis = await _listening(db, ctx, workflow)
        await service.catch(token, body=b"{}", headers={})
        capture = await service.caught(ctx, workflow.id, token)
        assert capture.delivery is not None and capture.delivery.delivery_id.startswith("test-")

    async def test_a_url_that_closed_without_a_call_says_so(self, db, tenant):
        owner, org, workflow = tenant
        ctx = _ctx(owner, org)
        service, token, redis = await _listening(db, ctx, workflow)
        redis.store.pop(f"workflow:webhook-test:{token}:open")
        assert (await service.caught(ctx, workflow.id, token)).state == "expired"
        with pytest.raises(NotFoundError):
            await service.catch(token, body=b"{}", headers={})

    async def test_a_call_it_cannot_keep_leaves_it_listening(self, db, tenant):
        owner, org, workflow = tenant
        ctx = _ctx(owner, org)
        service, token, _redis = await _listening(db, ctx, workflow)
        with pytest.raises(BadRequestError):
            await service.catch(token, body=b"[1]", headers={})
        huge = json.dumps({"text": "x" * 70_000}).encode()
        with pytest.raises(WebhookTestTooLargeError):
            await service.catch(token, body=huge, headers={})
        assert (await service.caught(ctx, workflow.id, token)).state == "listening"

    async def test_a_url_that_went_between_the_check_and_the_catch_keeps_nothing(self, db, tenant):
        owner, org, workflow = tenant
        ctx = _ctx(owner, org)
        service, token, redis = await _listening(db, ctx, workflow)
        # Another call caught it after this one found it open.
        redis.getdel = AsyncMock(return_value=None)  # ty: ignore[invalid-assignment]
        with pytest.raises(NotFoundError):
            await service.catch(token, body=b"{}", headers={})
        assert f"workflow:webhook-test:{token}:caught" not in redis.store

    async def test_only_a_draft_that_starts_from_a_webhook_has_one(self, db, tenant):
        owner, org, workflow = tenant
        with pytest.raises(BadRequestError):
            await _listening(db, _ctx(owner, org), workflow, _graph())

    async def test_an_archived_workflow_has_none(self, db, tenant):
        owner, org, workflow = tenant
        workflow.status = WorkflowStatus.ARCHIVED.value
        with pytest.raises(WorkflowArchivedError):
            await _listening(db, _ctx(owner, org), workflow)

    @pytest.mark.security
    async def test_only_the_workflows_editors_read_what_it_caught(self, db, tenant):
        owner, org, workflow = tenant
        ctx = _ctx(owner, org)
        service, token, _redis = await _listening(db, ctx, workflow)
        other = await _another_workflow(db, org, owner)
        operator = await _user(db)
        await _member(db, org=org, user=operator, role="operator")
        stranger = await _user(db)
        elsewhere = await _org(db, owner=stranger)

        for reader, workflow_id in (
            (ctx, other.id),
            (_ctx(operator, org, "operator"), workflow.id),
            (_ctx(stranger, elsewhere), workflow.id),
        ):
            with pytest.raises(NotFoundError):
                await service.caught(reader, workflow_id, token)
        with pytest.raises(NotFoundError):
            await service.caught(ctx, workflow.id, "not-a-token")

    async def test_listening_over_http_catches_the_call_and_answers_that_it_kept_it(self, http):
        client, workflow_id, _factory = http
        app.dependency_overrides[deps.get_redis] = _Redis
        redis = _Redis()
        app.dependency_overrides[deps.get_redis] = lambda: redis
        base = f"{settings.API_V1_STR}/workflows/{workflow_id}"
        draft = (await client.get(base)).json()
        saved = await client.patch(
            f"{base}/draft",
            json={
                "graph": _graph("trigger.webhook").model_dump(mode="json"),
                "expected_revision": draft["draft_revision"],
            },
        )
        assert saved.status_code == 200, saved.text

        listening = await client.post(f"{base}/webhook-test")
        assert listening.status_code == 201, listening.text
        token = listening.json()["test_token"]
        assert listening.json()["url"].endswith(f"/api/v1/workflow-webhook-tests/{token}")
        caught = await client.post(
            f"{settings.API_V1_STR}/workflow-webhook-tests/{token}", content=b'{"lead": 4}'
        )
        read = await client.get(f"{base}/webhook-test/{token}")

        assert (caught.status_code, caught.json()) == (200, {"captured": True})
        assert read.json()["state"] == "caught"
        assert read.json()["delivery"]["body"] == {"lead": 4}


FORM = {
    "title": "Talk to us",
    "description": "We answer within a day.",
    "fields": [
        {"name": "name", "type": "text", "required": True},
        {"name": "seats", "type": "integer", "required": False},
        {"name": "topic", "type": "choice", "options": ["Demo", "Pricing"]},
    ],
}


async def _form(
    db: AsyncSession, ctx: AuthContext, workflow: Workflow, config: dict | None = None
) -> WorkflowPublished:
    published = await _publish(db, ctx, workflow, _graph("trigger.form", config or FORM))
    assert published.exposure is not None and published.exposure.form_token is not None
    return published


class TestForms:
    async def test_publishing_gives_the_form_a_link_that_survives_the_next_publish(
        self, db, tenant
    ):
        owner, org, workflow = tenant
        graph = _graph("trigger.form", FORM)
        first = await _publish(db, _ctx(owner, org), workflow, graph)
        assert first.exposure is not None and first.webhook_secret is None
        token = first.exposure.form_token
        assert token is not None and len(token) >= 32
        assert first.exposure.form_url == f"{settings.FRONTEND_URL.rstrip('/')}/f/{token}"
        assert first.exposure.webhook_url is None

        again = await _publish(db, _ctx(owner, org), workflow, graph)

        assert again.exposure is not None
        assert (again.exposure.id, again.exposure.form_token) == (first.exposure.id, token)
        assert again.exposure.version_number == 2

    async def test_the_page_shows_the_forms_words_and_fields(self, db, tenant):
        owner, org, workflow = tenant
        token = (await _form(db, _ctx(owner, org), workflow)).exposure.form_token

        page = await WorkflowExposureService(db).form_page(token)

        assert (page.title, page.description, page.submit_label) == (
            "Talk to us",
            "We answer within a day.",
            "Submit",
        )
        assert [field.name for field in page.fields] == ["name", "seats", "topic"]

    async def test_answers_that_fit_start_one_run_as_the_publisher(self, db, tenant):
        owner, org, workflow = tenant
        published = await _form(db, _ctx(owner, org), workflow)
        answers = {"name": "Ada", "seats": 12, "topic": "Demo"}

        thanks = await WorkflowExposureService(db).submit_form(
            published.exposure.form_token, WorkflowFormSubmission(values=answers)
        )

        assert thanks.message == "Thank you - your answers were sent."
        (run,) = await _runs(db)
        assert run.triggered_by == WorkflowRunTrigger.FORM.value
        assert (run.input, run.execution_principal_user_id) == (answers, owner.id)
        assert run.workflow_version_id == published.id
        exposure = await db.get(WorkflowExposure, published.exposure.id)
        assert exposure is not None and exposure.last_run_id == run.id

    async def test_answers_that_do_not_fit_are_named_and_start_nothing(self, db, tenant):
        owner, org, workflow = tenant
        token = (await _form(db, _ctx(owner, org), workflow)).exposure.form_token

        with pytest.raises(WorkflowRunInputInvalidError) as refused:
            await WorkflowExposureService(db).submit_form(
                token, WorkflowFormSubmission(values={"seats": "12", "topic": "Lunch"})
            )

        fields = {problem["field"] for problem in refused.value.details["problems"]}
        assert fields == {"name", "seats", "topic"}
        assert await _runs(db) == []

    @pytest.mark.security
    async def test_a_filled_in_trap_is_thanked_and_starts_nothing(self, db, tenant):
        owner, org, workflow = tenant
        token = (await _form(db, _ctx(owner, org), workflow)).exposure.form_token

        thanks = await WorkflowExposureService(db).submit_form(
            token, WorkflowFormSubmission(values={"name": "x"}, website="spam.example")
        )

        assert thanks.message == "Thank you - your answers were sent."
        assert await _runs(db) == []

    @pytest.mark.security
    async def test_a_replaced_paused_or_orphaned_link_is_no_form(self, db, tenant):
        owner, org, workflow = tenant
        service = WorkflowExposureService(db)
        published = await _form(db, _ctx(owner, org), workflow)
        old = published.exposure.form_token

        renewed = await service.renew_form_link(
            _ctx(owner, org), workflow.id, published.exposure.id
        )

        assert renewed.form_token not in (None, old)
        with pytest.raises(NotFoundError):
            await service.form_page(old)
        await service.set_active(
            _ctx(owner, org), workflow.id, renewed.id, WorkflowExposureUpdate(is_active=False)
        )
        with pytest.raises(NotFoundError):
            await service.form_page(renewed.form_token)
        await service.set_active(
            _ctx(owner, org), workflow.id, renewed.id, WorkflowExposureUpdate(is_active=True)
        )
        await db.execute(delete(OrganizationMember).where(OrganizationMember.user_id == owner.id))
        with pytest.raises(NotFoundError):
            await service.submit_form(
                renewed.form_token, WorkflowFormSubmission(values={"name": "Ada", "topic": "Demo"})
            )
        assert await _runs(db) == []

    async def test_only_a_form_has_a_link_to_replace(self, db, tenant):
        owner, org, workflow = tenant
        exposure_id, _secret = await _webhook(db, _ctx(owner, org), workflow)
        with pytest.raises(BadRequestError):
            await WorkflowExposureService(db).renew_form_link(
                _ctx(owner, org), workflow.id, exposure_id
            )

    async def test_a_form_asks_for_at_least_one_field(self, db, tenant):
        owner, org, workflow = tenant
        with pytest.raises(BadRequestError):
            await _publish(
                db, _ctx(owner, org), workflow, _graph("trigger.form", {"title": "Empty"})
            )

    async def test_a_test_run_of_a_form_draft_is_checked_against_its_fields(self, db, tenant):
        owner, org, workflow = tenant
        workflow.draft_graph = _graph("trigger.form", FORM).model_dump(mode="json")
        await db.flush()
        service = WorkflowExecutionService(db)
        with pytest.raises(WorkflowRunInputInvalidError):
            await service.start(
                _ctx(owner, org), workflow.id, mode=WorkflowRunMode.TEST, run_input={}
            )
        started = await service.start(
            _ctx(owner, org),
            workflow.id,
            mode=WorkflowRunMode.TEST,
            run_input={"name": "Ada", "topic": "Pricing"},
        )
        assert started.mode == WorkflowRunMode.TEST

    async def test_a_form_is_read_submitted_and_renewed_over_http(self, http):
        client, workflow_id, factory = http
        published = await _publish_over_http(client, workflow_id, _graph("trigger.form", FORM))
        token = published["exposure"]["form_token"]
        url = f"{settings.API_V1_STR}/public/workflow-forms/{token}"

        page = await client.get(url)
        refused = await client.post(url, json={"values": {"topic": "Demo"}})
        sent = await client.post(url, json={"values": {"name": "Ada", "topic": "Demo"}})

        assert (page.status_code, page.json()["title"]) == (200, "Talk to us")
        assert refused.status_code == 422
        assert refused.json()["error"]["details"]["problems"][0]["field"] == "name"
        assert (sent.status_code, sent.json()) == (
            201,
            {"message": "Thank you - your answers were sent."},
        )
        async with factory() as fresh:
            (run,) = (await fresh.execute(select(WorkflowRun))).scalars().all()
            assert run.triggered_by == "form"

        base = f"{settings.API_V1_STR}/workflows/{workflow_id}"
        renewed = await client.post(
            f"{base}/exposures/{published['exposure']['id']}/renew-form-link"
        )
        assert renewed.json()["form_url"].endswith(renewed.json()["form_token"])
        assert (await client.get(url)).status_code == 404


async def _bot(db: AsyncSession, org: Organization, platform: str = "slack") -> ChannelBot:
    bot = ChannelBot(
        id=uuid.uuid4(),
        organization_id=org.id,
        platform=platform,
        name="Support",
        token_encrypted="sealed",
        secret_key_version=1,
    )
    db.add(bot)
    await db.flush()
    return bot


def _message(bot: ChannelBot, text: str = "refund order 42", chat_type: str = "private"):
    return IncomingMessage(
        platform=bot.platform,
        bot_id=str(bot.id),
        platform_user_id="U1",
        platform_chat_id="C1:1700.1",
        chat_type=chat_type,
        text=text,
        platform_username="ada",
        platform_display_name="Ada",
        message_id="1700.2",
    )


class TestChannelMessages:
    async def test_a_message_that_fits_starts_a_run_with_where_to_answer_it(self, db, tenant):
        owner, org, workflow = tenant
        bot = await _bot(db, org)
        published = await _publish(
            db,
            _ctx(owner, org),
            workflow,
            _graph("trigger.channel_message", {"bot_id": str(bot.id), "text_contains": "REFUND"}),
        )
        assert published.exposure is not None and published.exposure.channel_bot_id == bot.id
        service = WorkflowExposureService(db)
        member = uuid.uuid4()

        taken = await service.receive_channel_message(bot, _message(bot), sender_user_id=member)

        assert taken is True
        (run,) = await _runs(db)
        assert run.triggered_by == WorkflowRunTrigger.CHANNEL_MESSAGE.value
        assert run.execution_principal_user_id == owner.id
        assert run.input == {
            "platform": "slack",
            "bot_id": str(bot.id),
            "channel_id": "C1",
            "thread_id": "1700.1",
            "chat_type": "private",
            "message_id": "1700.2",
            "text": "refund order 42",
            "sender": {
                "platform_user_id": "U1",
                "username": "ada",
                "display_name": "Ada",
                "user_id": str(member),
            },
        }

    async def test_what_does_not_fit_is_left_to_the_bots_agent(self, db, tenant):
        owner, org, workflow = tenant
        bot = await _bot(db, org)
        config = {"bot_id": str(bot.id), "chat_types": ["group"], "text_contains": "refund"}
        published = await _publish(
            db, _ctx(owner, org), workflow, _graph("trigger.channel_message", config)
        )
        service = WorkflowExposureService(db)
        other = await _bot(db, org)

        assert not await service.receive_channel_message(bot, _message(bot), sender_user_id=None)
        assert not await service.receive_channel_message(
            bot, _message(bot, "hello", "group"), sender_user_id=None
        )
        assert not await service.receive_channel_message(
            other, _message(other), sender_user_id=None
        )
        assert await service.receive_channel_message(
            bot, _message(bot, chat_type="group"), sender_user_id=None
        )
        await service.set_active(
            _ctx(owner, org),
            workflow.id,
            published.exposure.id,
            WorkflowExposureUpdate(is_active=False),
        )
        assert not await service.receive_channel_message(
            bot, _message(bot, chat_type="group"), sender_user_id=None
        )
        assert len(await _runs(db)) == 1

    @pytest.mark.security
    async def test_a_listener_whose_publisher_left_starts_nothing(self, db, tenant):
        owner, org, workflow = tenant
        bot = await _bot(db, org)
        await _publish(
            db,
            _ctx(owner, org),
            workflow,
            _graph("trigger.channel_message", {"bot_id": str(bot.id)}),
        )
        await db.execute(delete(OrganizationMember).where(OrganizationMember.user_id == owner.id))

        taken = await WorkflowExposureService(db).receive_channel_message(
            bot, _message(bot), sender_user_id=None
        )

        assert taken is False and await _runs(db) == []

    async def test_a_bots_messages_start_one_workflow_at_most(self, db, tenant):
        owner, org, workflow = tenant
        bot = await _bot(db, org)
        graph = _graph("trigger.channel_message", {"bot_id": str(bot.id)})
        first = await _publish(db, _ctx(owner, org), workflow, graph)
        again = await _publish(db, _ctx(owner, org), workflow, graph)
        assert again.exposure is not None and again.exposure.id == first.exposure.id

        other = await _another_workflow(db, org, owner)
        with pytest.raises(AlreadyExistsError):
            await _publish(
                db,
                _ctx(owner, org),
                other,
                _graph("trigger.channel_message", {"bot_id": str(bot.id)}),
            )

    @pytest.mark.security
    async def test_listening_to_a_bot_needs_channels_manage(self, db, tenant):
        owner, org, workflow = tenant
        bot = await _bot(db, org)
        builder = await _user(db)
        await _member(db, org=org, user=builder, role="builder")
        own = await _workflow(db, org=org, owner=builder)
        with pytest.raises(BadRequestError):
            await _publish(
                db,
                _ctx(builder, org, "builder"),
                own,
                _graph("trigger.channel_message", {"bot_id": str(bot.id)}),
            )


GITHUB = {"repository": "acme/api", "events": ["issues", "pull_request"], "actions": ["opened"]}


def _github_delivery(
    secret: str,
    *,
    event: str = "issues",
    action: str | None = "opened",
    repository: str | None = "acme/api",
    delivery: str | None = "g-1",
) -> tuple[bytes, dict[str, str]]:
    payload: dict[str, object] = {"sender": {"login": "ada"}}
    if repository is not None:
        payload["repository"] = {"full_name": repository}
    if action is not None:
        payload["action"] = action
    body = json.dumps(payload).encode()
    headers = {
        "x-hub-signature-256": "sha256="
        + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
        "x-github-event": event,
    }
    if delivery is not None:
        headers["x-github-delivery"] = delivery
    return body, headers


class _GithubAccount:
    """The organization's GitHub account and the hooks it registers, recorded."""

    def __init__(self, connection: McpConnection, *, refuses: bool = False) -> None:
        self.registered: list[dict] = []
        self.deleted: list[str] = []
        self.refuses = refuses
        self.connection = connection

    async def register_webhook(self, **kwargs):
        if self.refuses:
            raise WebhookRegistrationForbidden(details={})
        self.registered.append(kwargs)
        return RegisteredWebhook(provider_webhook_id=f"hook-{len(self.registered)}")

    async def delete_webhook(self, *, access_token, target, provider_webhook_id):
        self.deleted.append(provider_webhook_id)

    @contextlib.contextmanager
    def connected(self, token: str | None = "gho_token"):
        service = "app.services.workflow_exposure"
        with (
            patch(f"{service}.portals.get_adapter", return_value=self),
            patch(
                f"{service}.mcp_connection_repo.get_org_scoped_by_catalog_key",
                AsyncMock(return_value=self.connection),
            ),
            patch(
                f"{service}.McpConnectionService.webhook_access_token",
                AsyncMock(return_value=token),
            ),
        ):
            yield


async def _account(db: AsyncSession, org: Organization, *, refuses: bool = False):
    connection = McpConnection(
        id=uuid.uuid4(),
        scope="org",
        organization_id=org.id,
        name=f"github-{uuid.uuid4().hex[:8]}",
        url="https://api.githubcopilot.com/mcp/",
        secret_key_version=1,
    )
    db.add(connection)
    await db.flush()
    return _GithubAccount(connection, refuses=refuses)


class TestGithub:
    async def test_without_an_account_the_secret_is_shown_once_to_paste(self, db, tenant):
        owner, org, workflow = tenant
        graph = _graph("trigger.github", GITHUB)
        with patch(
            "app.services.workflow_exposure.mcp_connection_repo.get_org_scoped_by_catalog_key",
            AsyncMock(return_value=None),
        ):
            first = await _publish(db, _ctx(owner, org), workflow, graph)
            again = await _publish(db, _ctx(owner, org), workflow, graph)

        assert first.exposure is not None and first.webhook_secret is not None
        assert first.exposure.webhook_url == (
            f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/v1/workflow-github/{first.exposure.id}"
        )
        assert first.exposure.registered_on_provider is False
        assert again.webhook_secret is None and again.exposure.id == first.exposure.id

    async def test_a_delivery_it_names_starts_a_run_once(self, db, tenant):
        owner, org, workflow = tenant
        published = await _publish(
            db,
            _ctx(owner, org),
            workflow,
            _graph("trigger.github", {**GITHUB, "register_with_account": False}),
        )
        service = WorkflowExposureService(db)
        body, headers = _github_delivery(published.webhook_secret)

        first = await service.receive_github(published.exposure.id, body=body, headers=headers)
        again = await service.receive_github(published.exposure.id, body=body, headers=headers)

        assert (first.duplicate, again.duplicate, again.run_id) == (False, True, first.run_id)
        (run,) = await _runs(db)
        assert run.triggered_by == WorkflowRunTrigger.GITHUB.value
        assert run.input["event"] == "issues" and run.input["action"] == "opened"
        assert (run.input["repository"], run.input["sender"]) == ("acme/api", "ada")
        assert run.input["payload"]["repository"] == {"full_name": "acme/api"}

    @pytest.mark.parametrize(
        "delivery",
        [
            {"event": "ping", "action": None},
            {"event": "push", "action": None},
            {"action": "closed"},
            {"repository": "acme/other"},
            {"repository": None},
            {"event": ""},
        ],
        ids=[
            "ping",
            "another-event",
            "another-action",
            "another-repository",
            "no-repository",
            "no-event",
        ],
    )
    async def test_a_delivery_it_does_not_name_is_skipped(self, db, tenant, delivery):
        owner, org, workflow = tenant
        published = await _publish(
            db,
            _ctx(owner, org),
            workflow,
            _graph("trigger.github", {**GITHUB, "register_with_account": False}),
        )
        body, headers = _github_delivery(published.webhook_secret, **delivery)

        skipped = await WorkflowExposureService(db).receive_github(
            published.exposure.id, body=body, headers=headers
        )

        assert isinstance(skipped, WebhookSkipped) and await _runs(db) == []

    @pytest.mark.security
    async def test_a_delivery_it_cannot_trust_or_name_is_refused(self, db, tenant):
        owner, org, workflow = tenant
        published = await _publish(
            db,
            _ctx(owner, org),
            workflow,
            _graph("trigger.github", {**GITHUB, "register_with_account": False}),
        )
        service = WorkflowExposureService(db)
        forged, forged_headers = _github_delivery("wrong")
        unnamed, unnamed_headers = _github_delivery(published.webhook_secret, delivery=None)

        with pytest.raises(AuthorizationError):
            await service.receive_github(published.exposure.id, body=forged, headers=forged_headers)
        with pytest.raises(BadRequestError):
            await service.receive_github(
                published.exposure.id, body=unnamed, headers=unnamed_headers
            )
        with pytest.raises(NotFoundError):
            await service.receive_github(uuid.uuid4(), body=forged, headers=forged_headers)
        await db.execute(delete(OrganizationMember).where(OrganizationMember.user_id == owner.id))
        body, headers = _github_delivery(published.webhook_secret)
        with pytest.raises(AuthorizationError):
            await service.receive_github(published.exposure.id, body=body, headers=headers)
        assert await _runs(db) == []

    async def test_the_account_registers_the_hook_and_every_publish_registers_it_again(
        self, db, tenant
    ):
        owner, org, workflow = tenant
        account = await _account(db, org)
        with account.connected():
            first = await _publish(db, _ctx(owner, org), workflow, _graph("trigger.github", GITHUB))
            again = await _publish(
                db,
                _ctx(owner, org),
                workflow,
                _graph("trigger.github", {**GITHUB, "repository": "acme/web"}),
            )

        assert first.webhook_secret is None and first.exposure.registered_on_provider
        assert again.exposure.provider_target == "acme/web"
        assert [one["target"] for one in account.registered] == ["acme/api", "acme/web"]
        assert account.registered[0]["events"] == ("issues", "pull_request")
        assert account.registered[0]["webhook_url"] == first.exposure.webhook_url
        assert account.deleted == ["hook-1"]

    async def test_a_hook_the_account_no_longer_registers_is_handed_over_to_paste(self, db, tenant):
        owner, org, workflow = tenant
        graph = _graph("trigger.github", GITHUB)
        with (await _account(db, org)).connected():
            await _publish(db, _ctx(owner, org), workflow, graph)
        refusing = await _account(db, org, refuses=True)
        with refusing.connected():
            again = await _publish(db, _ctx(owner, org), workflow, graph)

        assert again.webhook_secret is not None
        assert again.exposure.registered_on_provider is False

    async def test_a_new_secret_registers_the_hook_again(self, db, tenant):
        owner, org, workflow = tenant
        account = await _account(db, org)
        with account.connected():
            published = await _publish(
                db, _ctx(owner, org), workflow, _graph("trigger.github", GITHUB)
            )
            rotated = await WorkflowExposureService(db).rotate_secret(
                _ctx(owner, org), workflow.id, published.exposure.id
            )

        assert account.registered[-1]["secret"] == rotated.reveal_secret
        assert account.deleted == ["hook-1"]

    async def test_a_publish_that_starts_another_way_takes_the_hook_down(self, db, tenant):
        owner, org, workflow = tenant
        account = await _account(db, org)
        with account.connected():
            await _publish(db, _ctx(owner, org), workflow, _graph("trigger.github", GITHUB))
            await _publish(db, _ctx(owner, org), workflow, _graph())

        assert account.deleted == ["hook-1"]
        assert (await db.execute(select(WorkflowExposure))).scalars().all() == []

    async def test_a_hook_it_cannot_take_down_does_not_stop_the_publish(self, db, tenant):
        owner, org, workflow = tenant
        account = await _account(db, org)
        with account.connected():
            await _publish(db, _ctx(owner, org), workflow, _graph("trigger.github", GITHUB))
        account.delete_webhook = AsyncMock(side_effect=RuntimeError("GitHub is down"))
        with account.connected():
            published = await _publish(db, _ctx(owner, org), workflow, _graph())
        assert published.exposure is None

    async def test_an_account_without_webhook_permission_leaves_it_to_paste(self, db, tenant):
        owner, org, workflow = tenant
        with (await _account(db, org)).connected(token=None):
            published = await _publish(
                db, _ctx(owner, org), workflow, _graph("trigger.github", GITHUB)
            )
        assert published.webhook_secret is not None

    async def test_github_delivered_over_http(self, http):
        client, workflow_id, factory = http
        graph = _graph("trigger.github", {**GITHUB, "register_with_account": False})
        published = await _publish_over_http(client, workflow_id, graph)
        body, headers = _github_delivery(published["webhook_secret"])
        ping, ping_headers = _github_delivery(published["webhook_secret"], event="ping")
        url = f"{settings.API_V1_STR}/workflow-github/{published['exposure']['id']}"

        admitted = await client.post(url, content=body, headers=headers)
        skipped = await client.post(url, content=ping, headers=ping_headers)

        assert admitted.status_code == 202 and admitted.json()["duplicate"] is False
        assert skipped.status_code == 202 and "ping" in skipped.json()["skipped"]


async def _mailbox(db: AsyncSession, org: Organization) -> McpConnection:
    grant = McpConnection(
        id=uuid.uuid4(),
        scope="org",
        organization_id=org.id,
        name="gmail",
        url="https://gmail.googleapis.com",
        secret_key_version=1,
        purpose="portal",
        portal_key="google",
    )
    db.add(grant)
    await db.flush()
    return grant


def _mail(message_id: str = "m1", **fields: object) -> PolledEvent:
    payload = {
        "subject": "Invoice 42 overdue",
        "from": "Billing <billing@acme.com>",
        "to": "ops@example.com",
        "labels": ["INBOX", "IMPORTANT"],
        "text": "Please pay invoice 42.",
        "snippet": "Please pay",
        "message_id": message_id,
        **fields,
    }
    return PolledEvent(delivery_id=f"gmail:{message_id}", payload=payload)


class TestGmail:
    async def test_publishing_needs_a_connected_mailbox(self, db, tenant):
        owner, org, workflow = tenant
        with pytest.raises(BadRequestError, match="Gmail mailbox"):
            await _publish(db, _ctx(owner, org), workflow, _graph("trigger.gmail"))

    async def test_a_message_that_fits_starts_one_run_however_often_it_is_read(self, db, tenant):
        owner, org, workflow = tenant
        await _mailbox(db, org)
        published = await _publish(
            db,
            _ctx(owner, org),
            workflow,
            _graph("trigger.gmail", {"subject_contains": "INVOICE", "label": "IMPORTANT"}),
        )
        assert published.exposure is not None and published.exposure.webhook_url is None
        service = WorkflowExposureService(db)
        mail = [_mail("m1"), _mail("m2", subject="Lunch?"), _mail("m3", labels=["INBOX"])]

        assert await service.receive_polled_email(organization_id=org.id, events=mail)
        assert await service.receive_polled_email(organization_id=org.id, events=mail)

        (run,) = await _runs(db)
        assert run.triggered_by == WorkflowRunTrigger.GMAIL.value
        assert run.execution_principal_user_id == owner.id
        assert run.input == {
            "message_id": "m1",
            "sender": "Billing <billing@acme.com>",
            "to": "ops@example.com",
            "subject": "Invoice 42 overdue",
            "text": "Please pay invoice 42.",
            "snippet": "Please pay",
            "labels": ["INBOX", "IMPORTANT"],
        }

    async def test_a_paused_one_or_one_whose_publisher_left_starts_nothing(self, db, tenant):
        owner, org, workflow = tenant
        await _mailbox(db, org)
        published = await _publish(db, _ctx(owner, org), workflow, _graph("trigger.gmail"))
        service = WorkflowExposureService(db)
        await service.set_active(
            _ctx(owner, org),
            workflow.id,
            published.exposure.id,
            WorkflowExposureUpdate(is_active=False),
        )
        assert await service.receive_polled_email(organization_id=org.id, events=[_mail()])
        await service.set_active(
            _ctx(owner, org),
            workflow.id,
            published.exposure.id,
            WorkflowExposureUpdate(is_active=True),
        )
        await db.execute(delete(OrganizationMember).where(OrganizationMember.user_id == owner.id))
        assert await service.receive_polled_email(organization_id=org.id, events=[_mail()])
        assert await _runs(db) == []

    async def test_a_message_with_no_room_is_left_for_the_next_poll(self, db, tenant):
        owner, org, workflow = tenant
        await _mailbox(db, org)
        await _publish(db, _ctx(owner, org), workflow, _graph("trigger.gmail"))
        service = WorkflowExposureService(db)
        refused = WorkflowAdmissionQuotaError(
            scope="organization", limit=1, outstanding=1, requested=1
        )
        with patch.object(service.runs, "admit_pinned", AsyncMock(side_effect=refused)):
            assert not await service.receive_polled_email(organization_id=org.id, events=[_mail()])
        assert (await db.execute(select(WorkflowWebhookDelivery))).scalars().all() == []

        assert await service.receive_polled_email(organization_id=org.id, events=[_mail()])
        assert len(await _runs(db)) == 1

    async def test_a_message_too_large_to_run_is_not_read_again(self, db, tenant):
        owner, org, workflow = tenant
        await _mailbox(db, org)
        await _publish(db, _ctx(owner, org), workflow, _graph("trigger.gmail"))
        service = WorkflowExposureService(db)
        too_large = WorkflowRunInputTooLargeError(limit=1, size=2)
        with patch.object(service.runs, "admit_pinned", AsyncMock(side_effect=too_large)):
            assert await service.receive_polled_email(organization_id=org.id, events=[_mail()])
        assert await _runs(db) == []
